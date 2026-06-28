"""ChatTTS 引擎 — 本地中文语音合成（无精确语速控制）。

ChatTTS 是一个开源中文 TTS 引擎（MIT 许可证），输出 24kHz WAV 音频。
它没有 speed/rate 参数，依赖上游翻译时长约束 + 下游 rubberband 变速对齐。

GitHub: https://github.com/2noise/ChatTTS
License: MIT License
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from src.config import TTSConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine

try:
    import ChatTTS  # type: ignore[import-untyped]
    import torch
    import torchaudio
    from pydub import AudioSegment
except ImportError as e:
    raise ImportError(
        f"ChatTTS 依赖未安装: {e}. 请运行: pip install ChatTTS torch torchaudio"
    ) from e

logger = logging.getLogger("video_translator")

_SAMPLE_RATE = 24000  # ChatTTS 固定输出采样率


class ChatTTSEngine(TTSEngine):
    """基于 ChatTTS 的本地 TTS 引擎。

    ChatTTS 不支持语速参数，合成语速由模型决定。
    管线通过上游翻译时长约束和下游 rubberband 变速来对齐时长。
    """

    def __init__(self, config: TTSConfig) -> None:
        super().__init__(config)
        logger.info("TTS | ChatTTS | 加载模型...")
        self._chat = ChatTTS.Chat()
        self._chat.load(compile=False)
        logger.info("TTS | ChatTTS | 模型加载完成")

    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        process_registry: list[subprocess.Popen[bytes]] | None = None,
    ) -> list[SubtitleSegment]:
        """逐段合成语音，填充 audio_path 和 audio_duration。

        Args:
            segments: 字幕段落列表，每段需包含 translated_text。
            temp_dir: 临时目录，音频片段保存到 temp_dir/segments/ 下。
            progress_callback: 可选进度回调。
            process_registry: 未使用（ChatTTS 不启动子进程）。

        Returns:
            更新后的字幕段落列表。

        Raises:
            PipelineError: 合成过程中发生错误。
        """
        total = len(segments)
        if total == 0:
            return segments

        output_dir = temp_dir / "segments"
        output_dir.mkdir(parents=True, exist_ok=True)

        completed = 0
        for seg in segments:
            if not seg.translated_text.strip():
                completed += 1
                if progress_callback:
                    progress_callback(
                        ProgressEvent(
                            stage="TTS",
                            progress=completed / total,
                            message=f"TTS ChatTTS: {completed}/{total}",
                        )
                    )
                continue

            output_path = output_dir / f"{seg.index:04d}.wav"
            self._synthesize_segment(seg.translated_text, output_path)
            seg.audio_path = output_path
            seg.audio_duration = self._read_duration(output_path)
            completed += 1

            if progress_callback:
                progress_callback(
                    ProgressEvent(
                        stage="TTS",
                        progress=completed / total,
                        message=f"TTS ChatTTS: {completed}/{total}",
                    )
                )

        return segments

    def _synthesize_segment(self, text: str, output_path: Path) -> None:
        """调用 ChatTTS 推理一段文本并保存为 WAV。

        Args:
            text: 待合成文本。
            output_path: WAV 输出路径。

        Raises:
            PipelineError: 推理失败或无输出时抛出。
        """
        try:
            wavs = self._chat.infer([text])
            if not wavs or wavs[0] is None:
                raise PipelineError(
                    "ChatTTS 未返回音频",
                    stage="TTS",
                    suggestion="请检查输入文本是否为空",
                )
            audio_tensor = torch.from_numpy(wavs[0]).unsqueeze(0)
            torchaudio.save(str(output_path), audio_tensor, _SAMPLE_RATE)
        except PipelineError:
            raise
        except Exception as e:
            raise PipelineError(
                f"ChatTTS 合成失败: {e}",
                stage="TTS",
                suggestion="将自动降级到 Edge-TTS",
            ) from e

    @staticmethod
    def _read_duration(path: Path) -> float:
        """读取 WAV 文件时长（秒）。

        Args:
            path: WAV 文件路径。

        Returns:
            音频时长（秒），精确到毫秒。
        """
        audio = AudioSegment.from_wav(str(path))
        return len(audio) / 1000.0
