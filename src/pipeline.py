from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import threading
import time
from pathlib import Path

from src.config import AppConfig
from src.exceptions import PipelineError
from src.models import PipelineResult, StageState, StageStatus, SubtitleSegment
from src.signals import PipelineSignals

logger = logging.getLogger("video_translator")

STAGE_NAMES = ["音频提取", "ASR", "翻译", "TTS", "语速自适应", "合成"]


class Pipeline:
    """六阶段翻译管线编排器，在后台线程中执行。"""

    def __init__(self, config: AppConfig, signals: PipelineSignals) -> None:
        self.config = config.model_copy(deep=True)
        self.signals = signals
        self.states: dict[str, StageState] = {name: StageState(name) for name in STAGE_NAMES}
        self._current_stage: str = STAGE_NAMES[0]

    def start(self, video_path: Path, output_dir: Path) -> None:
        """在后台守护线程中启动管线。"""
        thread = threading.Thread(
            target=self._run_in_thread,
            args=(video_path, output_dir),
            daemon=True,
        )
        thread.start()

    def _run_in_thread(self, video_path: Path, output_dir: Path) -> None:
        try:
            self.process(video_path, output_dir)
        except Exception:
            logger.exception("管线 | 未捕获异常")
            self.signals.pipeline_finished.emit()

    def process(self, video_path: Path, output_dir: Path) -> PipelineResult:
        """主编排方法：六阶段顺序执行。"""
        temp_dir: Path | None = None
        try:
            temp_dir = self._create_temp_dir(output_dir, video_path)

            # 阶段 1: 音频提取（本 Story 实际实现）
            self._start_stage("音频提取")
            audio_path = self._extract_audio(video_path, temp_dir)
            self._complete_stage("音频提取")

            # 阶段 2-6: 占位实现，后续 Story 逐个替换
            self._start_stage("ASR")
            segments = self._run_asr(audio_path)
            self._complete_stage("ASR")

            self._start_stage("翻译")
            segments = self._run_translation(segments)
            self._complete_stage("翻译")

            self._start_stage("TTS")
            segments = self._run_tts(segments, temp_dir)
            self._complete_stage("TTS")

            self._start_stage("语速自适应")
            segments = self._run_alignment(segments, temp_dir)
            self._complete_stage("语速自适应")

            self._start_stage("合成")
            self._compose(video_path, segments, temp_dir, output_dir)
            self._complete_stage("合成")

            self._cleanup_temp(temp_dir)

            result = PipelineResult(
                video_path=video_path,
                output_dir=output_dir,
                audio_path=audio_path,
            )
            self.signals.pipeline_finished.emit()
            return result

        except PipelineError as e:
            self._fail_stage(e.stage, str(e))
            result = PipelineResult(
                video_path=video_path,
                output_dir=output_dir,
                success=False,
                error=str(e),
            )
            self.signals.pipeline_finished.emit()
            return result
        except Exception as e:
            self._fail_stage(self._current_stage, str(e))
            result = PipelineResult(
                video_path=video_path,
                output_dir=output_dir,
                success=False,
                error=str(e),
            )
            self.signals.pipeline_finished.emit()
            return result

    # ── 临时目录管理 ──────────────────────────────────────────

    def _create_temp_dir(self, output_dir: Path, video_path: Path) -> Path:
        """创建 output/.temp/{video_hash}/ 临时目录。"""
        raw = f"{video_path.name}_{video_path.stat().st_size}".encode()
        video_hash = hashlib.md5(raw).hexdigest()[:8]
        temp_dir = output_dir / ".temp" / video_hash
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info("临时目录 | 创建 | path=%s", temp_dir)
        return temp_dir

    def _cleanup_temp(self, temp_dir: Path) -> None:
        """管线成功完成后删除临时目录。"""
        try:
            shutil.rmtree(temp_dir)
            logger.info("临时目录 | 清理 | path=%s", temp_dir)
        except OSError:
            logger.warning("临时目录 | 清理失败 | path=%s", temp_dir)

    # ── 阶段状态管理 ──────────────────────────────────────────

    def _start_stage(self, name: str) -> None:
        self._current_stage = name
        state = self.states[name]
        state.status = StageStatus.RUNNING
        state.start_time = time.monotonic()
        state.progress = 0.0
        self.signals.stage_started.emit(name)
        logger.info("%s | START", name)

    def _complete_stage(self, name: str) -> None:
        state = self.states[name]
        state.status = StageStatus.COMPLETED
        state.end_time = time.monotonic()
        state.progress = 1.0
        duration = state.duration or 0.0
        self.signals.stage_completed.emit(name, duration)
        logger.info("%s | DONE | duration=%.1fs", name, duration)

    def _fail_stage(self, name: str, error: str) -> None:
        state = self.states[name]
        state.status = StageStatus.FAILED
        state.end_time = time.monotonic()
        state.error = error
        self.signals.stage_failed.emit(name, error)
        logger.error("%s | ERROR | msg=%s", name, error)

    # ── 阶段 1: 音频提取 ────────────────────────────────────

    def _extract_audio(self, video_path: Path, temp_dir: Path) -> Path:
        """通过 ffmpeg 从视频提取 WAV 音频（16kHz 单声道 PCM）。"""
        output_path = temp_dir / "audio.wav"
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            str(output_path),
        ]
        try:
            subprocess.run(
                cmd,
                capture_output=True,
                timeout=60,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            raise PipelineError(
                f"音频提取失败: {stderr_text[:200]}",
                stage="音频提取",
                suggestion="请确认视频文件有效且 ffmpeg 已安装",
            ) from e
        except subprocess.TimeoutExpired as e:
            raise PipelineError(
                "音频提取超时（60秒）",
                stage="音频提取",
                suggestion="请确认视频文件不是过大或损坏",
            ) from e
        except FileNotFoundError as e:
            raise PipelineError(
                "ffmpeg 未找到",
                stage="音频提取",
                suggestion="请安装 ffmpeg: brew install ffmpeg",
            ) from e

        logger.info("音频提取 | output=%s", output_path)
        return output_path

    # ── 占位阶段（后续 Story 实现） ───────────────────────────

    def _run_asr(self, audio_path: Path) -> list[SubtitleSegment]:
        """ASR 占位 — Story 4-2 实现。"""
        logger.info("ASR | PLACEHOLDER | 将由 Story 4-2 实现")
        return []

    def _run_translation(self, segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
        """翻译占位 — Story 4-3 实现。"""
        logger.info("翻译 | PLACEHOLDER | 将由 Story 4-3 实现")
        return segments

    def _run_tts(self, segments: list[SubtitleSegment], temp_dir: Path) -> list[SubtitleSegment]:
        """TTS 占位 — Story 4-4 实现。"""
        logger.info("TTS | PLACEHOLDER | 将由 Story 4-4 实现")
        return segments

    def _run_alignment(
        self, segments: list[SubtitleSegment], temp_dir: Path,
    ) -> list[SubtitleSegment]:
        """语速自适应占位 — Story 4-5 实现。"""
        logger.info("语速自适应 | PLACEHOLDER | 将由 Story 4-5 实现")
        return segments

    def _compose(
        self, video_path: Path, segments: list[SubtitleSegment],
        temp_dir: Path, output_dir: Path,
    ) -> Path:
        """音视频合成占位 — Story 4-6 实现。"""
        logger.info("合成 | PLACEHOLDER | 将由 Story 4-6 实现")
        return video_path
