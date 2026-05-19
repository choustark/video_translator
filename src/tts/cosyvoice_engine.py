from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Callable

from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine

logger = logging.getLogger("video_translator")


class CosyVoiceEngine(TTSEngine):
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        """使用 CosyVoice 将翻译后的字幕段落合成为语音文件。

        尚未实现，保留接口占位。当前通过 importlib.util.find_spec 检测
        CosyVoice 是否已安装，未安装时抛出 PipelineError 提示降级到 Edge-TTS；
        已安装时同样抛出 PipelineError 提示功能尚未完成。

        Args:
            segments: 待合成的字幕段落列表。
            temp_dir: 临时目录。
            progress_callback: 可选的进度回调函数。

        Returns:
            更新后的字幕段落列表（当前始终不会正常返回）。

        Raises:
            PipelineError: CosyVoice 未安装或完整合成尚未实现时抛出。
        """
        if importlib.util.find_spec("cosyvoice") is None:
            logger.warning("TTS | CosyVoice 未安装，降级到 Edge-TTS")
            raise PipelineError(
                "CosyVoice 未安装，已降级到 Edge-TTS",
                stage="TTS",
                suggestion="安装 CosyVoice 或使用 Edge-TTS 引擎",
            )

        raise PipelineError(
            "CosyVoice 完整合成尚未实现（v1 降级存根）",
            stage="TTS",
            suggestion="请使用 Edge-TTS 引擎，或等待 CosyVoice 完整支持",
        )
