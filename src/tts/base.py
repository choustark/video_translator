from __future__ import annotations

import subprocess
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
        process_registry: list[subprocess.Popen[bytes]] | None = None,
    ) -> list[SubtitleSegment]:
        """将翻译后的字幕段落合成为语音文件。

        Args:
            segments: 待合成的字幕段落列表，每段需包含 translated_text。
            temp_dir: 临时目录，用于存放生成的音频片段文件。
            progress_callback: 可选的进度回调函数，用于报告合成进度。
            process_registry: 可选列表，引擎创建的 subprocess.Popen 对象会追加到此列表，
                              供 Pipeline.abort() 安全终止。

        Returns:
            更新后的字幕段落列表，每段填充了 audio_path 和 audio_duration。

        Raises:
            PipelineError: 合成过程中发生错误时抛出。
        """
        ...
