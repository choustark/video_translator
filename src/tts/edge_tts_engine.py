"""Edge-TTS 引擎 — 微软免费云语音合成。

Edge-TTS 是微软提供的免费文本转语音服务（MIT License）。
支持 `rate` 参数控制语速，基于 `CHARS_PER_SEC`（4字/秒）自动计算。
异步 API 在同步管线线程中通过事件循环管理。

GitHub: https://github.com/rany2/edge-tts
License: MIT License

GitHub: https://github.com/rany2/edge-tts
License: MIT License
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

import edge_tts
from pydub import AudioSegment  # type: ignore[import-untyped]
from tenacity import (
    RetryCallState,
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.config import CHARS_PER_SEC
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine

logger = logging.getLogger("video_translator")

_VOICE_MAP: dict[str, str] = {
    "default": "zh-CN-YunxiNeural",
}

_MAX_RATE_OFFSET = 50

# 与 GLM Provider 一致：3 次尝试（1 次原始 + 2 次重试），指数退避 1-10 秒
_MAX_ATTEMPTS = 3

# 仅对网络相关异常重试；其他异常（RuntimeError、配置错误等）立即抛出
_RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = (
    edge_tts.exceptions.NoAudioReceived,
    edge_tts.exceptions.WebSocketError,
)


class EdgeTTSEngine(TTSEngine):
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        process_registry: list[subprocess.Popen[bytes]] | None = None,
    ) -> list[SubtitleSegment]:
        """使用 Edge-TTS 将翻译后的字幕段落合成为 MP3 语音文件。

        遍历每条字幕段落，跳过空文本，调用 Edge-TTS API 生成音频，
        并通过 pydub 获取音频时长。语速参数映射：0.5→-50%，2.0→+50%。

        Args:
            segments: 待合成的字幕段落列表，每段需包含 translated_text。
            temp_dir: 临时目录，音频片段保存到 temp_dir/segments/ 下。
            progress_callback: 可选的进度回调函数，报告当前合成进度。

        Returns:
            更新后的字幕段落列表，每段填充了 audio_path（MP3）和 audio_duration。

        Raises:
            PipelineError: Edge-TTS 调用失败或音频时长读取失败时抛出。
        """
        total = len(segments)
        if total == 0:
            return segments

        processable = [seg for seg in segments if seg.translated_text.strip()]
        processable_total = len(processable)

        voice = _VOICE_MAP.get(self.config.voice, self.config.voice)
        base_rate_str = f"{int(self.config.speed * 100 - 100):+d}%"
        segments_dir = temp_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        processed = 0
        for seg in processable:
            processed += 1

            output_path = segments_dir / f"{seg.index:04d}.mp3"
            target_duration = seg.end_time - seg.start_time
            rate_str = self._compute_rate(seg.translated_text, target_duration, base_rate_str)
            segment_progress = processed / processable_total
            self._synthesize_segment(
                seg.translated_text, voice, rate_str, output_path,
                progress_callback=progress_callback,
                segment_progress=segment_progress,
            )

            seg.audio_path = output_path
            seg.audio_duration = self._get_duration(output_path)

            if progress_callback:
                progress_callback(ProgressEvent(
                    stage="TTS",
                    progress=segment_progress,
                    message=f"正在合成 {processed}/{processable_total}",
                ))

        skipped = total - processable_total
        summary = f"合成完成 {processable_total}/{processable_total}"
        if skipped:
            summary += f"（跳过 {skipped} 段）"
        if progress_callback:
            progress_callback(ProgressEvent(
                stage="TTS", progress=1.0, message=summary,
            ))

        return segments

    def _compute_rate(self, text: str, target_duration: float, base_rate_str: str) -> str:
        char_count = len(text)
        if char_count < 4 or target_duration <= 0.5:
            return base_rate_str

        target_speed = char_count / target_duration
        offset = round((target_speed / CHARS_PER_SEC - 1) * 100)
        offset = max(-_MAX_RATE_OFFSET, min(_MAX_RATE_OFFSET, offset))
        if offset == 0:
            return base_rate_str
        return f"{offset:+d}%"

    def _synthesize_segment(
        self,
        text: str,
        voice: str,
        rate: str,
        output_path: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        segment_progress: float = 0.0,
    ) -> None:
        """合成单段语音，对网络异常自动重试（最多 3 次）。

        - NoAudioReceived / WebSocketError：可重试（网络抖动）
        - 其他异常（RuntimeError 等）：立即抛出，不重试
        """
        try:
            self._do_tts_call(
                text, voice, rate, output_path,
                progress_callback=progress_callback,
                segment_progress=segment_progress,
            )
        except RetryError as e:
            raise PipelineError(
                f"TTS 合成失败（已重试 {_MAX_ATTEMPTS} 次）: {e.last_attempt.exception()}",
                stage="TTS",
                suggestion="请检查网络连接或稍后重试",
            ) from e

    def _do_tts_call(
        self,
        text: str,
        voice: str,
        rate: str,
        output_path: Path,
        progress_callback: Callable[[ProgressEvent], None] | None,
        segment_progress: float,
    ) -> None:
        """用 tenacity Retrying 包装实际 API 调用，仅重试网络异常。"""
        retrying = Retrying(
            stop=stop_after_attempt(_MAX_ATTEMPTS),
            wait=wait_exponential(min=1, max=10),
            retry=retry_if_exception_type(_RETRYABLE_EXCEPTIONS),
            before_sleep=self._make_retry_before_sleep(progress_callback, segment_progress),
        )
        retrying(self._execute_tts_request, text, voice, rate, output_path)

    def _make_retry_before_sleep(
        self,
        callback: Callable[[ProgressEvent], None] | None,
        segment_progress: float,
    ) -> Callable[[RetryCallState], None]:
        """构造 before_sleep 钩子，重试时上报"正在重试 (n/3)..."进度。"""
        def _before_sleep(retry_state: RetryCallState) -> None:
            attempt = retry_state.attempt_number
            logger.warning("TTS 重试 | attempt=%d/%d", attempt, _MAX_ATTEMPTS)
            if callback is None:
                return
            callback(ProgressEvent(
                stage="TTS",
                progress=segment_progress,
                message=f"正在重试 ({attempt}/{_MAX_ATTEMPTS})...",
            ))
        return _before_sleep

    def _execute_tts_request(
        self, text: str, voice: str, rate: str, output_path: Path,
    ) -> None:
        """实际调用 Edge-TTS API；网络异常直接抛出由 tenacity 处理。"""
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            communicate.save_sync(str(output_path))
        except (_RETRYABLE_EXCEPTIONS):
            raise
        except Exception as e:
            # 非网络异常：不可重试，立即包装为 PipelineError
            raise PipelineError(
                f"TTS 合成失败: {e}",
                stage="TTS",
                suggestion="请检查网络连接或尝试切换 TTS 引擎",
            ) from e

    def _get_duration(self, mp3_path: Path) -> float:
        try:
            audio = AudioSegment.from_mp3(str(mp3_path))
            return round(float(audio.duration_seconds), 3)
        except Exception as e:
            raise PipelineError(
                f"TTS 音频时长读取失败: {e}",
                stage="TTS",
                suggestion="请确认 ffmpeg 已安装且音频文件有效",
            ) from e
