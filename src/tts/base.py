from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Callable

from src.config import TTSConfig
from src.models import ProgressEvent, SubtitleSegment


class TTSEngine(ABC):
    def __init__(self, config: TTSConfig) -> None:
        self.config = config

    @abstractmethod
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]: ...
