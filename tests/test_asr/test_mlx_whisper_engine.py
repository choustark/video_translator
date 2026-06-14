from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.asr._helpers import (
    _apply_proper_noun_replacements,
    _build_initial_prompt,
    _build_proper_nouns_list,
    _merge_short_segments,
)
from src.asr.mlx_whisper_engine import MLXWhisperEngine
from src.config import ASRConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

_ASR_MEMORY_REQUIREMENT_GB = 6.0


def _make_config() -> ASRConfig:
    return ASRConfig(engine="mlx-whisper", model_path="models/asr/whisper-large-v3-turbo")


def _mock_transcribe_result() -> dict:
    return {
        "text": "Hello world. This is a test.",
        "language": "en",
        "segments": [
            {"start": 0.0, "end": 2.5, "text": "Hello world."},
            {"start": 2.5, "end": 5.0, "text": " This is a test."},
        ],
    }


def _mock_mlx_whisper() -> MagicMock:
    return MagicMock()


class TestProperNounsList:
    def test_deduplicates_user_nouns_case_insensitively(self) -> None:
        nouns = _build_proper_nouns_list(
            ["OpenAI", "openai", "MyCustomTool", "MyCustomTool"],
        )

        assert nouns.count("OpenAI") == 1
        assert nouns.count("MyCustomTool") == 1


class TestTranscribe:
    def test_returns_subtitle_segments(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = _mock_transcribe_result()

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024**3 + 1,
            )
            segments = engine.transcribe("/tmp/audio.wav")

        assert len(segments) == 2
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 2.5
        assert segments[0].source_text == "Hello world."
        assert segments[0].index == 0
        assert segments[1].source_text == "This is a test."

    def test_filters_empty_segments(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {
            "text": "Hello.",
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello."},
                {"start": 1.0, "end": 2.0, "text": "   "},
                {"start": 2.0, "end": 3.0, "text": ""},
            ],
        }

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024**3 + 1,
            )
            segments = engine.transcribe("/tmp/audio.wav")

        assert len(segments) == 1
        assert segments[0].source_text == "Hello."

    def test_calls_mlx_whisper_with_correct_params(self) -> None:
        config = _make_config()
        engine = MLXWhisperEngine(config)
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {"text": "", "segments": []}

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024**3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        expected_prompt = _build_initial_prompt([])
        mock_mlx.transcribe.assert_called_once_with(
            "/tmp/audio.wav",
            path_or_hf_repo=config.model_path,
            language=config.language,
            word_timestamps=True,
            verbose=False,
            initial_prompt=expected_prompt,
        )

    def test_includes_custom_proper_nouns_in_prompt(self) -> None:
        config = ASRConfig(
            engine="mlx-whisper",
            model_path="models/asr/test",
            proper_nouns=["MyCustomTool"],
        )
        engine = MLXWhisperEngine(config)
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {"text": "", "segments": []}

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024**3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        call_kwargs = mock_mlx.transcribe.call_args
        prompt = call_kwargs.kwargs.get("initial_prompt", call_kwargs[1].get("initial_prompt", ""))
        assert "MyCustomTool" in prompt


class TestMemoryCheck:
    def test_raises_when_memory_low(self) -> None:
        engine = MLXWhisperEngine(_make_config())

        with patch("src.asr._helpers.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=1 * 1024**3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "内存不足" in str(exc_info.value)

    def test_passes_when_memory_sufficient(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {"text": "", "segments": []}

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            segments = engine.transcribe("/tmp/audio.wav")

        assert segments == []


class TestImportError:
    def test_raises_when_mlx_whisper_not_installed(self) -> None:
        engine = MLXWhisperEngine(_make_config())

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            # sys.modules[name]=None 强制 import 抛 ImportError
            patch.dict(sys.modules, {"mlx_whisper": None}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "mlx-whisper" in str(exc_info.value)

    def test_raises_when_transcribe_fails(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.side_effect = RuntimeError("model not found")

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "ASR 转录失败" in str(exc_info.value)


class TestProgressCallback:
    def test_emits_completion_event(self) -> None:
        """D22 v2.0-4-2：转录完成后必须发 progress=1.0 完成事件（不再按段 fake 模拟）。"""
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = _mock_transcribe_result()
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        # 完成事件存在，stage="ASR"，progress=1.0
        assert any(e.stage == "ASR" and e.progress == 1.0 for e in events), (
            f"未找到 progress=1.0 的完成事件，events={events}"
        )

    def test_all_events_use_asr_stage(self) -> None:
        """D22 v2.0-4-2：所有 ProgressEvent 必须用 stage='ASR'。"""
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = _mock_transcribe_result()
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        assert len(events) > 0, "未发出任何 ProgressEvent"
        assert all(e.stage == "ASR" for e in events)

    def test_no_callback_when_none(self) -> None:
        """D22 v2.0-4-2：progress_callback=None 必须不崩。"""
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = _mock_transcribe_result()

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            segments = engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=None,
            )

        assert len(segments) == 2


class TestRealTimeProgress:
    """D22 v2.0-4-2：mlx-whisper 实时进度回调（策略 A：RTF 估算 + 周期 timer）。

    验证 ASR 转录"期间"发出 ProgressEvent（不再转录完成后才模拟）。
    """

    def test_emits_progress_during_transcription(self) -> None:
        """转录"期间"必须有 ProgressEvent 发出（核心 AC3）。

        通过 mock transcribe 的 side_effect 为 time.sleep(0.3) 模拟阻塞，
        并 patch 周期间隔为 0.1s（避免测试慢），断言 callback 被多次调用。
        """
        import time as _time

        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        # 模拟 transcribe 阻塞 0.3s
        mock_mlx.transcribe.side_effect = lambda *a, **kw: (
            _time.sleep(0.3) or _mock_transcribe_result()
        )
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
            patch("src.asr.mlx_whisper_engine._PROGRESS_INTERVAL_SECONDS", 0.1),
            patch.object(engine, "_get_audio_duration", return_value=60.0),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        # 关键断言：转录期间（0.3s）应至少触发 1 次进度（排除完成事件后 ≥1）
        in_progress_events = [e for e in events if e.progress < 1.0]
        assert len(in_progress_events) >= 1, f"转录期间未发出 ProgressEvent，events={events}"

    def test_progress_monotonic_non_decreasing(self) -> None:
        """AC2：progress 序列必须单调不减。"""
        import time as _time

        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.side_effect = lambda *a, **kw: (
            _time.sleep(0.3) or _mock_transcribe_result()
        )
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
            patch("src.asr.mlx_whisper_engine._PROGRESS_INTERVAL_SECONDS", 0.1),
            patch.object(engine, "_get_audio_duration", return_value=60.0),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        progresses = [e.progress for e in events]
        for prev, curr in zip(progresses, progresses[1:]):
            assert curr >= prev, f"progress 非单调：{prev} → {curr}，全序列={progresses}"

    def test_emits_completion_progress(self) -> None:
        """AC4：转录完成后最后一次 progress 必须 == 1.0。"""
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = _mock_transcribe_result()
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
            patch("src.asr.mlx_whisper_engine._PROGRESS_INTERVAL_SECONDS", 0.05),
            patch.object(engine, "_get_audio_duration", return_value=60.0),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        assert events, "未发出任何 ProgressEvent"
        assert events[-1].progress == 1.0, f"完成事件 progress != 1.0，events={events}"
        assert "已识别" in events[-1].message, (
            f"完成 message 不含'已识别'，msg={events[-1].message!r}"
        )

    def test_progress_capped_at_95_percent_during_transcription(self) -> None:
        """AC2 边界：估算进度不应超过 0.95，避免完成后卡在 100%。

        通过 mock 极长 sleep（强制多次 timer 触发），断言转录期间发出的
        progress 全部 <= 0.95。
        """
        import time as _time

        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        # 0.5s 阻塞 + audio_duration=0.5s（很短，让 elapsed/total 很快接近 1.0）
        mock_mlx.transcribe.side_effect = lambda *a, **kw: (
            _time.sleep(0.5) or _mock_transcribe_result()
        )
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
            patch("src.asr.mlx_whisper_engine._PROGRESS_INTERVAL_SECONDS", 0.1),
            patch.object(engine, "_get_audio_duration", return_value=0.5),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        in_progress = [e.progress for e in events if e.progress < 1.0]
        # 转录期间 progress 全部 <= 0.95（防止 fake 撞到 1.0 后等待真实完成）
        assert all(p <= 0.95 for p in in_progress), (
            f"转录期间 progress 超过 0.95 上限：{in_progress}"
        )


class TestGCRelease:
    def test_calls_gc_collect(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {"text": "", "segments": []}

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc") as mock_gc,
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe("/tmp/audio.wav")

        mock_gc.collect.assert_called_once()

    def test_clears_mlx_cache_when_available(self) -> None:
        mock_mx = MagicMock()
        mock_mx.get_active_memory.return_value = 100 * 1024 * 1024
        mock_mx.get_cache_memory.return_value = 500 * 1024 * 1024

        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {"text": "", "segments": []}

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(
                sys.modules,
                {
                    "mlx_whisper": mock_mlx,
                    "mlx.core": mock_mx,
                },
            ),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            engine.transcribe("/tmp/audio.wav")

        mock_mx.synchronize.assert_called_once()
        mock_mx.clear_cache.assert_called_once()

    def test_mlx_cache_exception_does_not_fail_transcribe(self) -> None:
        mock_mx = MagicMock()
        mock_mx.synchronize.side_effect = RuntimeError("Metal error")

        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {"text": "", "segments": []}

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(
                sys.modules,
                {
                    "mlx_whisper": mock_mlx,
                    "mlx.core": mock_mx,
                },
            ),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024**3,
            )
            segments = engine.transcribe("/tmp/audio.wav")

        assert segments == []


class TestBuildInitialPrompt:
    def test_embeds_nouns_in_natural_sentence(self) -> None:
        prompt = _build_initial_prompt(["Claude Code", "GPT-4"])
        assert prompt == "This technical discussion covers Claude Code and GPT-4."

    def test_single_noun(self) -> None:
        prompt = _build_initial_prompt(["Claude Code"])
        assert prompt == "This technical discussion covers Claude Code."

    def test_three_nouns_oxford_comma(self) -> None:
        prompt = _build_initial_prompt(["Claude Code", "GPT-4", "PySide6"])
        assert prompt == "This technical discussion covers Claude Code, GPT-4, and PySide6."

    def test_empty_nouns_returns_empty_string(self) -> None:
        prompt = _build_initial_prompt([])
        assert prompt == ""


class TestProperNounReplacement:
    def _make_segments(self, texts: list[str]) -> list[SubtitleSegment]:
        return [
            SubtitleSegment(index=i, start_time=float(i), end_time=float(i + 1), source_text=t)
            for i, t in enumerate(texts)
        ]

    def test_replaces_close_match(self) -> None:
        segs = self._make_segments(["I use cloud code daily."])
        nouns = ["Claude Code"]
        result = _apply_proper_noun_replacements(segs, nouns)
        assert "Claude Code" in result[0].source_text
        assert "cloud code" not in result[0].source_text

    def test_no_replacement_when_exact_match(self) -> None:
        segs = self._make_segments(["Claude Code is great."])
        nouns = ["Claude Code"]
        result = _apply_proper_noun_replacements(segs, nouns)
        assert result[0].source_text == "Claude Code is great."

    def test_no_replacement_unrelated_text(self) -> None:
        segs = self._make_segments(["The weather is nice."])
        nouns = ["Claude Code"]
        result = _apply_proper_noun_replacements(segs, nouns)
        assert result[0].source_text == "The weather is nice."

    def test_empty_nouns_no_change(self) -> None:
        segs = self._make_segments(["Some text."])
        result = _apply_proper_noun_replacements(segs, [])
        assert result[0].source_text == "Some text."

    def test_replacement_preserves_punctuation(self) -> None:
        segs = self._make_segments(["I love quad code."])
        nouns = ["Claude Code"]
        result = _apply_proper_noun_replacements(segs, nouns)
        assert result[0].source_text.endswith(".")

    def test_replaces_case_insensitive(self) -> None:
        segs = self._make_segments(["claude code is great."])
        nouns = ["Claude Code"]
        result = _apply_proper_noun_replacements(segs, nouns)
        assert result[0].source_text == "Claude Code is great."

    def test_multiple_nouns_in_segment(self) -> None:
        segs = self._make_segments(["cloud code and apple silicon are cool."])
        nouns = ["Claude Code", "Apple Silicon"]
        result = _apply_proper_noun_replacements(segs, nouns)
        assert "Claude Code" in result[0].source_text
        assert "Apple Silicon" in result[0].source_text


class TestMergeShortSegments:
    def _make_timed_segments(
        self,
        specs: list[tuple[float, float, str]],
    ) -> list[SubtitleSegment]:
        return [
            SubtitleSegment(index=i, start_time=start, end_time=end, source_text=text)
            for i, (start, end, text) in enumerate(specs)
        ]

    def test_merges_short_segment_into_previous(self) -> None:
        segs = self._make_timed_segments(
            [
                (0.0, 3.0, "Hello world."),
                (3.0, 3.3, "代码。"),
                (3.3, 6.0, "Next sentence."),
            ]
        )
        result = _merge_short_segments(segs)
        assert len(result) == 2
        assert "代码。" in result[0].source_text
        assert result[0].end_time == 3.3

    def test_merges_consecutive_short_segments(self) -> None:
        segs = self._make_timed_segments(
            [
                (0.0, 3.0, "Hello."),
                (3.0, 3.2, "A."),
                (3.2, 3.4, "B."),
                (3.4, 6.0, "Done."),
            ]
        )
        result = _merge_short_segments(segs)
        assert len(result) == 2
        assert "A." in result[0].source_text
        assert "B." in result[0].source_text

    def test_preserves_normal_segments(self) -> None:
        segs = self._make_timed_segments(
            [
                (0.0, 2.5, "Hello world."),
                (2.5, 5.0, "This is a test."),
            ]
        )
        result = _merge_short_segments(segs)
        assert len(result) == 2

    def test_last_short_segment_preserved(self) -> None:
        segs = self._make_timed_segments(
            [
                (0.0, 3.0, "Main text."),
                (3.0, 3.3, "End."),
            ]
        )
        result = _merge_short_segments(segs)
        assert len(result) == 2
        assert result[1].source_text == "End."

    def test_last_segment_above_threshold_kept(self) -> None:
        segs = self._make_timed_segments(
            [
                (0.0, 3.0, "Main text."),
                (3.0, 4.5, "Last one."),
            ]
        )
        result = _merge_short_segments(segs)
        assert len(result) == 2

    def test_empty_input(self) -> None:
        assert _merge_short_segments([]) == []

    def test_single_segment(self) -> None:
        segs = self._make_timed_segments([(0.0, 2.0, "One.")])
        result = _merge_short_segments(segs)
        assert len(result) == 1

    def test_reindexes_merged_output(self) -> None:
        segs = self._make_timed_segments(
            [
                (0.0, 3.0, "A."),
                (3.0, 3.3, "b."),
                (3.3, 6.0, "C."),
                (6.0, 6.2, "d."),
                (6.2, 9.0, "E."),
            ]
        )
        result = _merge_short_segments(segs)
        for idx, seg in enumerate(result):
            assert seg.index == idx
