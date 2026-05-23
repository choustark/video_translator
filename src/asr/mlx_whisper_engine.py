from __future__ import annotations

import gc
import logging
import re
import sys
from difflib import SequenceMatcher
from typing import Callable

import psutil

from src.asr.base import ASREngine
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

logger = logging.getLogger("video_translator")

_DEFAULT_PROPER_NOUNS: list[str] = [
    "Claude Code", "GPT-4", "PySide6", "ffmpeg", "OpenAI",
    "DeepSeek", "Homebrew", "Apple Silicon", "Metal", "MPS",
    "MLX", "Whisper", "CosyVoice", "macOS",
]


def _build_initial_prompt(nouns: list[str]) -> str:
    """将专有名词列表嵌入自然英文语句，作为 Whisper initial_prompt。

    Whisper 的 initial_prompt 被视为"前文转录文本"，裸词列表不符合训练分布，
    缺乏句法和语义锚定。自然语句格式能让模型在上下文约束下正确识别专有名词。
    最重要的词放在句末（Whisper 对尾部 ~224 tokens 权重最高）。
    """
    if not nouns:
        return ""
    if len(nouns) == 1:
        terms = nouns[0]
    elif len(nouns) == 2:
        terms = f"{nouns[0]} and {nouns[1]}"
    else:
        terms = ", ".join(nouns[:-1]) + ", and " + nouns[-1]
    return f"This technical discussion covers {terms}."


def _apply_proper_noun_replacements(
    segments: list[SubtitleSegment],
    nouns: list[str],
) -> list[SubtitleSegment]:
    if not nouns:
        return segments

    # 长名词优先匹配，避免短名词先替换破坏长名词
    # 例如 "Claude" 不能比 "Claude Code" 先匹配
    nouns = sorted(nouns, key=len, reverse=True)

    for seg in segments:
        text = seg.source_text
        for noun in nouns:
            lower_noun = noun.lower()
            lower_text = text.lower()
            pos = lower_text.find(lower_noun)
            if pos >= 0:
                text = text[:pos] + noun + text[pos + len(lower_noun):]
                continue

            noun_words = noun.split()
            if len(noun_words) < 2:
                continue

            tokens = re.split(r"(\s+)", text)
            clean_tokens = [re.sub(r"[^\w]", "", t).lower() for t in tokens]
            n_noun = len(noun_words)
            clean_noun_parts = [re.sub(r"[^\w]", "", w).lower() for w in noun_words]

            for i in range(len(tokens)):
                all_match = True
                for j in range(n_noun):
                    ti = i + j * 2
                    if ti >= len(clean_tokens):
                        all_match = False
                        break
                    ratio = SequenceMatcher(None, clean_tokens[ti], clean_noun_parts[j]).ratio()
                    if ratio < 0.40:
                        all_match = False
                        break

                if all_match:
                    first_idx = i
                    last_idx = i + (n_noun - 1) * 2
                    last_token = tokens[last_idx]
                    m = re.search(r"[^\w]+$", last_token)
                    trailing = m.group() if m else ""
                    tokens[first_idx] = noun + trailing
                    for _ in range(n_noun - 1):
                        tokens.pop(first_idx + 1)
                        if first_idx + 1 < len(tokens):
                            tokens.pop(first_idx + 1)
                    text = "".join(tokens)
                    break

        seg.source_text = text

    return segments


_MIN_SEGMENT_DURATION = 1.0
_MIN_GAP_BETWEEN_SEGMENTS = 0.1
_EXCEPTION_FOR_LAST = 0.5


def _merge_short_segments(
    segments: list[SubtitleSegment],
) -> list[SubtitleSegment]:
    if len(segments) <= 1:
        return segments

    merged: list[SubtitleSegment] = [segments[0]]

    for i in range(1, len(segments)):
        prev = merged[-1]
        curr = segments[i]
        duration = curr.end_time - curr.start_time
        gap = curr.start_time - prev.end_time
        is_last = (i == len(segments) - 1)
        prev_short = (prev.end_time - prev.start_time) < _MIN_SEGMENT_DURATION

        should_merge = False
        is_last_exception = is_last and duration < _EXCEPTION_FOR_LAST
        if duration < _MIN_SEGMENT_DURATION and not is_last_exception:
            should_merge = True
        elif 0 <= gap < _MIN_GAP_BETWEEN_SEGMENTS and prev_short:
            should_merge = True

        if should_merge:
            prev.end_time = curr.end_time
            prev.source_text += curr.source_text
        else:
            curr.index = len(merged)
            merged.append(curr)

    for idx, seg in enumerate(merged):
        seg.index = idx

    return merged


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

        all_nouns = _DEFAULT_PROPER_NOUNS + [
            n for n in self.config.proper_nouns if n not in _DEFAULT_PROPER_NOUNS
        ]
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
        available = psutil.virtual_memory().available
        available_gb = available / (1024 ** 3)
        if available_gb < requirement_gb:
            raise PipelineError(
                f"可用内存不足: {available_gb:.1f}GB，"
                f"ASR 至少需要 {requirement_gb:.0f}GB",
                stage="ASR",
                suggestion="请关闭其他应用释放内存",
            )

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
