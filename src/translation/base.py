from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from src.config import TranslationConfig
from src.models import ProgressEvent, SubtitleSegment


class TranslationProvider(ABC):
    def __init__(self, config: TranslationConfig) -> None:
        self.config = config

    @abstractmethod
    def translate(
        self,
        segments: list[SubtitleSegment],
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]: ...
