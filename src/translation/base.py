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
    ) -> list[SubtitleSegment]:
        """翻译字幕片段列表，将 source_text 翻译为 translated_text。

        Args:
            segments: 待翻译的字幕片段列表，每段包含 source_text。
            progress_callback: 翻译进度回调，接收 ProgressEvent。

        Returns:
            翻译完成后的字幕片段列表，translated_text 已填充。

        Raises:
            NotImplementedError: 子类必须实现此方法。
        """
        ...
