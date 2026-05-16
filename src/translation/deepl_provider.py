from __future__ import annotations

from typing import Callable

from src.config import TranslationConfig
from src.models import ProgressEvent, SubtitleSegment
from src.translation.base import TranslationProvider


class DeepLProvider(TranslationProvider):
    def __init__(self, config: TranslationConfig) -> None:
        super().__init__(config)

    def translate(
        self,
        segments: list[SubtitleSegment],
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        raise NotImplementedError("DeepLProvider not yet implemented")
