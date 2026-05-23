from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from pydub import AudioSegment  # type: ignore[import-untyped]

from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

logger = logging.getLogger("video_translator")

_MAX_SPEED_RATIO = 1.5
_SINGLE_DEVIATION_THRESHOLD = 0.15
_GLOBAL_DEVIATION_THRESHOLD = 0.10

_rubberband_available: bool | None = None


def _check_rubberband() -> bool:
    """检测 ffmpeg 是否支持 rubberband 滤镜（结果缓存）。"""
    global _rubberband_available
    if _rubberband_available is not None:
        return _rubberband_available
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"],
            capture_output=True, text=True, timeout=10,
        )
        _rubberband_available = "rubberband" in result.stdout
    except Exception:
        _rubberband_available = False
    if not _rubberband_available:
        logger.warning("rubberband 滤镜不可用，降级使用 atempo")
    return _rubberband_available


# 模块加载时预检测，避免首次 _speed_up() 调用的 1-3 秒延迟
_check_rubberband()


class SpeedAdapter:
    """语速自适应对齐 — ffmpeg atempo 加速 + apad 静音填充。"""

    def align(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        """将每段中文配音的时长对齐到原始英文字幕的时间窗口。

        对于时长短于目标窗口的音频，使用 ffmpeg apad 填充静音；
        对于时长超出的音频，使用 ffmpeg atempo 加速，但当加速比超过 1.5x 时
        跳过加速并保留原始音频。对齐后检测单段偏差（>15%）和全局偏差（>10%）。

        Args:
            segments: 字幕段落列表，每段需包含 audio_path 和 audio_duration。
            temp_dir: 临时目录，对齐后的音频将写入其 ``aligned`` 子目录。
            progress_callback: 可选的进度回调，每完成一段触发一次。

        Returns:
            更新了 audio_path 的字幕段落列表（原地修改后返回）。

        Raises:
            PipelineError: ffmpeg 执行失败、超时或未安装时抛出。
        """
        total = len(segments)
        if total == 0:
            return segments

        processable = [seg for seg in segments if seg.audio_path and seg.audio_duration > 0]
        processable_total = len(processable)

        aligned_dir = temp_dir / "aligned"
        aligned_dir.mkdir(parents=True, exist_ok=True)

        processed = 0
        for seg in processable:
            processed += 1

            target_duration = seg.end_time - seg.start_time
            actual_duration = seg.audio_duration
            output_path = aligned_dir / f"{seg.index:04d}.wav"
            original_path = seg.audio_path

            if actual_duration < target_duration:
                self._pad(original_path, target_duration, output_path)
            elif actual_duration > target_duration:
                speed_ratio = actual_duration / target_duration
                if speed_ratio <= _MAX_SPEED_RATIO:
                    self._speed_up(original_path, speed_ratio, output_path)
                else:
                    logger.warning(
                        "对齐 | 跳过加速 | seg=%d ratio=%.2f > %.1fx",
                        seg.index,
                        speed_ratio,
                        _MAX_SPEED_RATIO,
                    )
                    self._copy(original_path, output_path)
            else:
                self._copy(original_path, output_path)

            seg.audio_path = output_path
            logger.info("对齐 | 原始=%s → 对齐=%s", original_path, output_path)

            self._check_deviation(seg, target_duration)

            if progress_callback:
                progress_callback(ProgressEvent(
                    stage="语速自适应",
                    progress=processed / processable_total,
                    message=f"正在对齐 {processed}/{processable_total}",
                ))

        self._check_global_deviation(segments)

        skipped = total - processable_total
        summary = f"对齐完成 {processable_total}/{processable_total}"
        if skipped:
            summary += f"（跳过 {skipped} 段）"
        if progress_callback:
            progress_callback(ProgressEvent(
                stage="语速自适应",
                progress=1.0,
                message=summary,
            ))

        return segments

    def _pad(self, input_path: Path, target_duration: float, output_path: Path) -> None:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-filter:a", f"apad=whole_dur={target_duration:.3f}",
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(output_path),
        ]
        self._run_ffmpeg(cmd)

    def _speed_up(self, input_path: Path, speed_ratio: float, output_path: Path) -> None:
        if _check_rubberband():
            filter_str = f"rubberband=tempo={speed_ratio:.4f}"
        else:
            filter_str = f"atempo={speed_ratio:.4f}"
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-filter:a", filter_str,
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(output_path),
        ]
        self._run_ffmpeg(cmd)

    def _copy(self, input_path: Path, output_path: Path) -> None:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
            str(output_path),
        ]
        self._run_ffmpeg(cmd)

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=True)
        except subprocess.CalledProcessError as e:
            stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            raise PipelineError(
                f"ffmpeg 对齐失败: {stderr_text[:200]}",
                stage="语速自适应",
                suggestion="请确认 ffmpeg 已安装且音频文件有效",
            ) from e
        except subprocess.TimeoutExpired as e:
            raise PipelineError(
                "ffmpeg 对齐超时（30秒）",
                stage="语速自适应",
                suggestion="音频文件可能过大",
            ) from e
        except FileNotFoundError as e:
            raise PipelineError(
                "ffmpeg 未找到",
                stage="语速自适应",
                suggestion="请安装 ffmpeg: brew install ffmpeg",
            ) from e

    def _check_deviation(self, seg: SubtitleSegment, target_duration: float) -> None:
        try:
            audio = AudioSegment.from_wav(str(seg.audio_path))
            actual = round(float(audio.duration_seconds), 3)
        except Exception:
            logger.warning("对齐 | 偏差检查失败 | seg=%d path=%s", seg.index, seg.audio_path)
            return

        seg.audio_duration = actual
        if target_duration > 0:
            deviation = abs(actual - target_duration) / target_duration
            if deviation > _SINGLE_DEVIATION_THRESHOLD:
                logger.warning(
                    "对齐 | 偏差过大 | seg=%d target=%.3f actual=%.3f deviation=%.1f%%",
                    seg.index, target_duration, actual, deviation * 100,
                )

    def _check_global_deviation(self, segments: list[SubtitleSegment]) -> None:
        total_actual = 0.0
        total_target = 0.0
        for seg in segments:
            if seg.audio_duration > 0:
                total_actual += seg.audio_duration
                total_target += seg.end_time - seg.start_time

        if total_target > 0:
            global_deviation = abs(total_actual - total_target) / total_target
            if global_deviation > _GLOBAL_DEVIATION_THRESHOLD:
                logger.warning(
                    "对齐 | 全局偏差 | total_actual=%.1f total_target=%.1f deviation=%.1f%%",
                    total_actual, total_target, global_deviation * 100,
                )
