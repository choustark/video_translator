from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from src.config import ASRConfig
from src.models import ProgressEvent, SubtitleSegment


class ASREngine(ABC):
    def __init__(self, config: ASRConfig) -> None:
        self.config = config

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]: ...
