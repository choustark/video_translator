from __future__ import annotations

from typing import Callable

from src.config import TranslationConfig
from src.models import ProgressEvent, SubtitleSegment
from src.translation.base import TranslationProvider


class DeepSeekProvider(TranslationProvider):
    def __init__(self, config: TranslationConfig) -> None:
        super().__init__(config)

    def translate(
        self,
        segments: list[SubtitleSegment],
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        """尚未实现，保留接口占位。"""
        raise NotImplementedError("DeepSeekProvider not yet implemented")
