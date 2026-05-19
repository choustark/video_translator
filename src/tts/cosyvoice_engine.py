from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Callable

from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine

logger = logging.getLogger("video_translator")


class CosyVoiceEngine(TTSEngine):
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        if importlib.util.find_spec("cosyvoice") is None:
            logger.warning("TTS | CosyVoice 未安装，降级到 Edge-TTS")
            raise PipelineError(
                "CosyVoice 未安装，已降级到 Edge-TTS",
                stage="TTS",
                suggestion="安装 CosyVoice 或使用 Edge-TTS 引擎",
            )

        raise PipelineError(
            "CosyVoice 完整合成尚未实现（v1 降级存根）",
            stage="TTS",
            suggestion="请使用 Edge-TTS 引擎，或等待 CosyVoice 完整支持",
        )
