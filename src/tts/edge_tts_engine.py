"""Edge-TTS 引擎 — 微软免费云语音合成。

Edge-TTS 是微软提供的免费文本转语音服务（MIT License）。
支持 `rate` 参数控制语速，基于 `CHARS_PER_SEC`（4字/秒）自动计算。
异步 API 在同步管线线程中通过事件循环管理。

GitHub: https://github.com/rany2/edge-tts
License: MIT License

GitHub: https://github.com/rany2/edge-tts
License: MIT License
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

import edge_tts
from pydub import AudioSegment  # type: ignore[import-untyped]

from src.config import CHARS_PER_SEC
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine

logger = logging.getLogger("video_translator")

_VOICE_MAP: dict[str, str] = {
    "default": "zh-CN-YunxiNeural",
}

_MAX_RATE_OFFSET = 50


class EdgeTTSEngine(TTSEngine):
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        process_registry: list[subprocess.Popen[bytes]] | None = None,
    ) -> list[SubtitleSegment]:
        """使用 Edge-TTS 将翻译后的字幕段落合成为 MP3 语音文件。

        遍历每条字幕段落，跳过空文本，调用 Edge-TTS API 生成音频，
        并通过 pydub 获取音频时长。语速参数映射：0.5→-50%，2.0→+50%。

        Args:
            segments: 待合成的字幕段落列表，每段需包含 translated_text。
            temp_dir: 临时目录，音频片段保存到 temp_dir/segments/ 下。
            progress_callback: 可选的进度回调函数，报告当前合成进度。

        Returns:
            更新后的字幕段落列表，每段填充了 audio_path（MP3）和 audio_duration。

        Raises:
            PipelineError: Edge-TTS 调用失败或音频时长读取失败时抛出。
        """
        total = len(segments)
        if total == 0:
            return segments

        processable = [seg for seg in segments if seg.translated_text.strip()]
        processable_total = len(processable)

        voice = _VOICE_MAP.get(self.config.voice, self.config.voice)
        base_rate_str = f"{int(self.config.speed * 100 - 100):+d}%"
        segments_dir = temp_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        processed = 0
        for seg in processable:
            processed += 1

            output_path = segments_dir / f"{seg.index:04d}.mp3"
            target_duration = seg.end_time - seg.start_time
            rate_str = self._compute_rate(seg.translated_text, target_duration, base_rate_str)
            self._synthesize_segment(seg.translated_text, voice, rate_str, output_path)

            seg.audio_path = output_path
            seg.audio_duration = self._get_duration(output_path)

            if progress_callback:
                progress_callback(ProgressEvent(
                    stage="TTS",
                    progress=processed / processable_total,
                    message=f"正在合成 {processed}/{processable_total}",
                ))

        skipped = total - processable_total
        summary = f"合成完成 {processable_total}/{processable_total}"
        if skipped:
            summary += f"（跳过 {skipped} 段）"
        if progress_callback:
            progress_callback(ProgressEvent(
                stage="TTS", progress=1.0, message=summary,
            ))

        return segments

    def _compute_rate(self, text: str, target_duration: float, base_rate_str: str) -> str:
        char_count = len(text)
        if char_count < 4 or target_duration <= 0.5:
            return base_rate_str

        target_speed = char_count / target_duration
        offset = round((target_speed / CHARS_PER_SEC - 1) * 100)
        offset = max(-_MAX_RATE_OFFSET, min(_MAX_RATE_OFFSET, offset))
        if offset == 0:
            return base_rate_str
        return f"{offset:+d}%"

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
