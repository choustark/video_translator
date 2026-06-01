from __future__ import annotations

import gc
import logging
from typing import Callable

from src.asr._helpers import (
    _apply_proper_noun_replacements,
    _build_initial_prompt,
    _build_proper_nouns_list,
    _check_memory,
    _merge_short_segments,
)
from src.asr.base import ASREngine
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

logger = logging.getLogger("video_translator")


class FasterWhisperEngine(ASREngine):
    """基于 faster-whisper (CTranslate2) 的 ASR 引擎，CPU-only 跨平台方案。"""

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        self._check_memory(self.memory_warning_gb)

        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except ImportError as e:
            raise PipelineError(
                "faster-whisper 未安装",
                stage="ASR",
                suggestion="请运行 uv add faster-whisper",
            ) from e

        all_nouns = _build_proper_nouns_list(
            user_nouns=self.config.proper_nouns,
            use_default=self.config.use_default_proper_nouns,
        )
        initial_prompt = _build_initial_prompt(all_nouns)

        logger.info("ASR | 开始 | audio=%s, model=%s, device=cpu, compute_type=int8", audio_path, self.config.model_path)

        try:
            model = WhisperModel(
                self.config.model_path,
                device="cpu",
                compute_type="int8",
            )
        except Exception as e:
            raise PipelineError(
                f"ASR 模型加载失败: {e}",
                stage="ASR",
                suggestion="请确认模型路径有效且 faster-whisper 已正确安装",
            ) from e

        try:
            segments_iter, info = model.transcribe(
                audio_path,
                language=self.config.language,
                initial_prompt=initial_prompt,
            )
        except Exception as e:
            raise PipelineError(
                f"ASR 转录失败: {e}",
                stage="ASR",
                suggestion="请确认模型路径有效且音频格式正确",
            ) from e

        duration = info.duration

        segments: list[SubtitleSegment] = []
        for seg in segments_iter:
            text = seg.text.strip()
            if not text:
                continue
            segments.append(SubtitleSegment(
                index=len(segments),
                start_time=seg.start,
                end_time=seg.end,
                source_text=text,
            ))
            if progress_callback and duration > 0:
                progress_callback(ProgressEvent(
                    stage="ASR",
                    progress=min(seg.end / duration, 1.0),
                    message=f"已识别 {len(segments)} 段",
                ))

        segments = _apply_proper_noun_replacements(segments, all_nouns)
        segments = _merge_short_segments(segments)

        logger.info("ASR | 完成 | segments=%d", len(segments))

        gc.collect()

        return segments

    def _check_memory(self, requirement_gb: float = 6.0) -> None:
        _check_memory(requirement_gb)
