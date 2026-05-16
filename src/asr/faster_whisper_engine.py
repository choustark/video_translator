from __future__ import annotations

from typing import Callable

from src.asr.base import ASREngine
from src.config import ASRConfig
from src.models import ProgressEvent, SubtitleSegment


class FasterWhisperEngine(ASREngine):
    def __init__(self, config: ASRConfig) -> None:
        super().__init__(config)

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        raise NotImplementedError("FasterWhisperEngine not yet implemented")
