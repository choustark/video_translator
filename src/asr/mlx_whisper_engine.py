"""MLX-Whisper 引擎 — Apple Silicon 优化的 Whisper ASR。

MLX-Whisper 是 Whisper 模型的 Apple Silicon 优化实现（MIT License）。
利用 MPS/Metal 加速，支持 M 系列 GPU，提供本地高质量语音识别。
OOM 时可能直接 segfault，加载前必须用 psutil 预检可用内存。

GitHub: https://github.com/ml-explore/mlx-examples/tree/main/whisper
License: MIT License

GitHub: https://github.com/ml-explore/mlx-whisper
License: MIT License
"""
from __future__ import annotations

import gc
import logging
import sys
from typing import Callable

from src.asr._helpers import (
    _apply_proper_noun_replacements,
    _build_initial_prompt,
    _build_proper_nouns_list,
    _check_memory,
    _merge_short_segments,
)
from src.asr.base import ASREngine
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

logger = logging.getLogger("video_translator")


class MLXWhisperEngine(ASREngine):
    """基于 mlx-whisper 的 ASR 引擎，针对 Apple Silicon MPS/Metal 加速。"""

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        self._check_memory(self.memory_warning_gb)

        try:
            import mlx_whisper  # type: ignore[import-untyped]
        except ImportError as e:
            raise PipelineError(
                "mlx-whisper 未安装",
                stage="ASR",
                suggestion="请运行 uv add mlx-whisper",
            ) from e

        all_nouns = _build_proper_nouns_list(user_nouns=self.config.proper_nouns)
        initial_prompt = _build_initial_prompt(all_nouns)

        logger.info("ASR | 开始 | audio=%s, model=%s", audio_path, self.config.model_path)

        try:
            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=self.config.model_path,
                language=self.config.language,
                word_timestamps=True,
                verbose=False,
                initial_prompt=initial_prompt,
            )
        except Exception as e:
            raise PipelineError(
                f"ASR 转录失败: {e}",
                stage="ASR",
                suggestion="请确认模型路径有效且音频格式正确",
            ) from e

        raw_segments = result.get("segments", [])
        segments: list[SubtitleSegment] = []
        for seg in raw_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            start = seg.get("start")
            end = seg.get("end")
            if start is None or end is None:
                continue
            segments.append(SubtitleSegment(
                index=len(segments),
                start_time=start,
                end_time=end,
                source_text=text,
            ))

        segments = _apply_proper_noun_replacements(segments, all_nouns)
        segments = _merge_short_segments(segments)

        logger.info("ASR | 完成 | segments=%d", len(segments))

        self._report_progress(segments, progress_callback)

        # 主动释放 ASR 模型内存：删除原始结果 + 清 Python GC + 清 MLX Metal 缓存
        del result
        self._release_mlx_memory()

        return segments

    def _release_mlx_memory(self) -> None:
        """释放 MLX Metal 缓存，归还 GPU 内存。best-effort，不阻断管线。"""
        gc.collect()

        mx = sys.modules.get("mlx.core")
        if mx is None:
            logger.debug("ASR | 内存释放 | mlx.core 未加载，跳过 Metal 缓存清理")
            return

        try:
            mx.synchronize()
            mx.clear_cache()
            logger.info(
                "ASR | 内存释放 | active=%.0fMB cache=%.0fMB",
                mx.get_active_memory() / 1024 / 1024,
                mx.get_cache_memory() / 1024 / 1024,
            )
        except Exception:
            logger.debug("ASR | 内存释放 | MLX 缓存清理异常（可忽略）", exc_info=True)

    def _check_memory(self, requirement_gb: float = 6.0) -> None:
        _check_memory(requirement_gb)

    @staticmethod
    def _report_progress(
        segments: list[SubtitleSegment],
        callback: Callable[[ProgressEvent], None] | None,
    ) -> None:
        if callback is None or not segments:
            return
        total = len(segments)
        steps = min(10, total)
        for step in range(1, steps + 1):
            idx = min(round(total * step / steps), total)
            callback(ProgressEvent(
                stage="ASR",
                progress=step / steps,
                message=f"已识别 {idx}/{total} 段",
            ))
