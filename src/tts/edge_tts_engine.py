from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import edge_tts
from pydub import AudioSegment  # type: ignore[import-untyped]

from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine

logger = logging.getLogger("video_translator")

_VOICE_MAP: dict[str, str] = {
    "default": "zh-CN-YunxiNeural",
}


class EdgeTTSEngine(TTSEngine):
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        total = len(segments)
        if total == 0:
            return segments

        voice = _VOICE_MAP.get(self.config.voice, self.config.voice)
        rate_str = f"{int(self.config.speed * 100 - 100):+d}%"
        segments_dir = temp_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        for i, seg in enumerate(segments):
            if not seg.translated_text.strip():
                continue

            output_path = segments_dir / f"{seg.index:04d}.mp3"
            self._synthesize_segment(seg.translated_text, voice, rate_str, output_path)

            seg.audio_path = output_path
            seg.audio_duration = self._get_duration(output_path)

            if progress_callback:
                progress_callback(ProgressEvent(
                    stage="TTS",
                    progress=(i + 1) / total,
                    message=f"正在合成 {i + 1}/{total}",
                ))

        if progress_callback:
            progress_callback(ProgressEvent(
                stage="TTS", progress=1.0, message=f"合成完成 {total}/{total}",
            ))

        return segments

    def _synthesize_segment(
        self, text: str, voice: str, rate: str, output_path: Path,
    ) -> None:
        try:
            communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
            communicate.save_sync(str(output_path))
        except edge_tts.exceptions.NoAudioReceived as e:
            raise PipelineError(
                f"TTS 未收到音频（文本可能为空或语音名无效）: {e}",
                stage="TTS",
                suggestion="请检查网络连接和语音配置",
            ) from e
        except edge_tts.exceptions.WebSocketError as e:
            raise PipelineError(
                f"TTS WebSocket 错误: {e}",
                stage="TTS",
                suggestion="请检查网络连接后重试",
            ) from e
        except Exception as e:
            raise PipelineError(
                f"TTS 合成失败: {e}",
                stage="TTS",
                suggestion="请检查网络连接或尝试切换 TTS 引擎",
            ) from e

    def _get_duration(self, mp3_path: Path) -> float:
        try:
            audio = AudioSegment.from_mp3(str(mp3_path))
            return round(float(audio.duration_seconds), 3)
        except Exception as e:
            raise PipelineError(
                f"TTS 音频时长读取失败: {e}",
                stage="TTS",
                suggestion="请确认 ffmpeg 已安装且音频文件有效",
            ) from e
