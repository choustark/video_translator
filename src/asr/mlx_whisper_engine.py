from __future__ import annotations

import gc
import logging
from typing import Callable

import psutil

from src.asr.base import ASREngine
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

logger = logging.getLogger("video_translator")

_ASR_MEMORY_REQUIREMENT_GB = 6.0


class MLXWhisperEngine(ASREngine):
    """基于 mlx-whisper 的 ASR 引擎，针对 Apple Silicon MPS/Metal 加速。"""

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        """使用 mlx-whisper 将音频转录为字幕段。

        内存预检确保至少有 6GB 可用，转录完成后执行 gc.collect() 释放模型内存。
        进度回调在转录完成后分 10 步模拟推送（mlx-whisper 为阻塞调用，无原生进度）。
        """
        self._check_memory()

        try:
            import mlx_whisper  # type: ignore[import-untyped]
        except ImportError as e:
            raise PipelineError(
                "mlx-whisper 未安装",
                stage="ASR",
                suggestion="请运行 uv add mlx-whisper",
            ) from e

        logger.info("ASR | 开始 | audio=%s, model=%s", audio_path, self.config.model_path)

        try:
            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=self.config.model_path,
                language=self.config.language,
                word_timestamps=True,
                verbose=False,
            )
        except Exception as e:
            raise PipelineError(
                f"ASR 转录失败: {e}",
                stage="ASR",
                suggestion="请确认模型路径有效且音频格式正确",
            ) from e

        raw_segments = result.get("segments", [])
        segments: list[SubtitleSegment] = []
        for seg in raw_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            start = seg.get("start")
            end = seg.get("end")
            if start is None or end is None:
                continue
            segments.append(SubtitleSegment(
                index=len(segments),
                start_time=start,
                end_time=end,
                source_text=text,
            ))

        logger.info("ASR | 完成 | segments=%d", len(segments))

        self._report_progress(segments, progress_callback)

        gc.collect()

        return segments

    def _check_memory(self) -> None:
        available = psutil.virtual_memory().available
        available_gb = available / (1024 ** 3)
        if available_gb < _ASR_MEMORY_REQUIREMENT_GB:
            raise PipelineError(
                f"可用内存不足: {available_gb:.1f}GB，"
                f"ASR 至少需要 {_ASR_MEMORY_REQUIREMENT_GB:.0f}GB",
                stage="ASR",
                suggestion="请关闭其他应用释放内存",
            )

    @staticmethod
    def _report_progress(
        segments: list[SubtitleSegment],
        callback: Callable[[ProgressEvent], None] | None,
    ) -> None:
        if callback is None or not segments:
            return
        total = len(segments)
        steps = min(10, total)
        for step in range(1, steps + 1):
            idx = min(round(total * step / steps), total)
            callback(ProgressEvent(
                stage="ASR",
                progress=step / steps,
                message=f"已识别 {idx}/{total} 段",
            ))
