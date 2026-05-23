from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from src.config import ASRConfig
from src.models import ProgressEvent, SubtitleSegment


class ASREngine(ABC):
    """ASR 语音识别引擎抽象基类，定义统一的转录接口。"""

    def __init__(self, config: ASRConfig) -> None:
        self.config = config
        self.memory_warning_gb: float = 6.0

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        """将音频文件转录为字幕段列表。

        Args:
            audio_path: 音频文件路径（WAV 16kHz 单声道）。
            progress_callback: 可选的进度回调，接收 ProgressEvent。

        Returns:
            按时间排序的 SubtitleSegment 列表，每个段包含 source_text。

        Raises:
            PipelineError: 转录失败时抛出，stage="ASR"。
        """
