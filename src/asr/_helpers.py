"""ASR 引擎共享辅助函数：专有名词引导、碎片段合并、内存检查。"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

import psutil

from src.exceptions import PipelineError
from src.models import SubtitleSegment

_DEFAULT_PROPER_NOUNS: list[str] = [
    "Claude Code",
    "GPT-4",
    "PySide6",
    "ffmpeg",
    "OpenAI",
    "DeepSeek",
    "Homebrew",
    "Apple Silicon",
    "Metal",
    "MPS",
    "MLX",
    "Whisper",
    "CosyVoice",
    "macOS",
]


def _build_proper_nouns_list(
    user_nouns: list[str],
    use_default: bool = True,
) -> list[str]:
    """根据用户配置构建最终的专有名词列表。

    Args:
        user_nouns: 用户在配置中指定的专有名词列表。
        use_default: 是否包含默认技术词汇列表。

    Returns:
        合并后的专有名词列表，去重，保持用户词汇优先顺序。
    """
    result: list[str] = []
    seen: set[str] = set()

    for noun in user_nouns:
        key = noun.strip().casefold()
        if not key or key in seen:
            continue
        result.append(noun)
        seen.add(key)

    if use_default:
        for noun in _DEFAULT_PROPER_NOUNS:
            key = noun.strip().casefold()
            if key in seen:
                continue
            result.append(noun)
            seen.add(key)

    return result


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
    """对 ASR 输出段进行专有名词模糊替换校正。"""
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
                text = text[:pos] + noun + text[pos + len(lower_noun) :]
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
    """合并相邻短片段（时长 <1s），减少碎片化字幕。"""
    if len(segments) <= 1:
        return segments

    merged: list[SubtitleSegment] = [segments[0]]

    for i in range(1, len(segments)):
        prev = merged[-1]
        curr = segments[i]
        duration = curr.end_time - curr.start_time
        gap = curr.start_time - prev.end_time
        is_last = i == len(segments) - 1
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


def _check_memory(requirement_gb: float = 6.0) -> None:
    available = psutil.virtual_memory().available
    available_gb = available / (1024**3)
    if available_gb < requirement_gb:
        raise PipelineError(
            f"可用内存不足: {available_gb:.1f}GB，ASR 至少需要 {requirement_gb:.0f}GB",
            stage="ASR",
            suggestion="请关闭其他应用释放内存",
        )
