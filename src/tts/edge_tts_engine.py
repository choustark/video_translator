from __future__ import annotations

from typing import Callable

from src.config import TTSConfig
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine


class EdgeTTSEngine(TTSEngine):
    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)

    def synthesize(
        self,
        segments: list[SubtitleSegment],
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        raise NotImplementedError("EdgeTTSEngine not yet implemented")
