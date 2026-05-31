from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.asr._helpers import (
    _DEFAULT_PROPER_NOUNS,
    _apply_proper_noun_replacements,
    _build_initial_prompt,
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
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
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
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
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
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        expected_prompt = _build_initial_prompt(_DEFAULT_PROPER_NOUNS)
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
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
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
                available=1 * 1024 ** 3,
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
                available=10 * 1024 ** 3,
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
                available=10 * 1024 ** 3,
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
                available=10 * 1024 ** 3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "ASR 转录失败" in str(exc_info.value)


class TestProgressCallback:
    def test_calls_callback_per_segment(self) -> None:
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
                available=10 * 1024 ** 3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        # 2 segments → min(10, 2) = 2 steps
        assert len(events) == 2
        assert events[0].stage == "ASR"
        assert events[-1].progress == 1.0

    def test_calls_callback_10_steps_for_many_segments(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = {
            "text": "", "language": "en",
            "segments": [{"start": float(i), "end": float(i + 1), "text": f"seg {i}"}
                         for i in range(15)],
        }
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        # 15 segments → min(10, 15) = 10 steps
        assert len(events) == 10
        assert events[-1].progress == 1.0

    def test_no_callback_when_none(self) -> None:
        engine = MLXWhisperEngine(_make_config())
        mock_mlx = _mock_mlx_whisper()
        mock_mlx.transcribe.return_value = _mock_transcribe_result()

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            segments = engine.transcribe(
                "/tmp/audio.wav", progress_callback=None,
            )

        assert len(segments) == 2


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
                available=10 * 1024 ** 3,
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
            patch.dict(sys.modules, {
                "mlx_whisper": mock_mlx,
                "mlx.core": mock_mx,
            }),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
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
            patch.dict(sys.modules, {
                "mlx_whisper": mock_mlx,
                "mlx.core": mock_mx,
            }),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
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
        self, specs: list[tuple[float, float, str]],
    ) -> list[SubtitleSegment]:
        return [
            SubtitleSegment(index=i, start_time=start, end_time=end, source_text=text)
            for i, (start, end, text) in enumerate(specs)
        ]

    def test_merges_short_segment_into_previous(self) -> None:
        segs = self._make_timed_segments([
            (0.0, 3.0, "Hello world."),
            (3.0, 3.3, "代码。"),
            (3.3, 6.0, "Next sentence."),
        ])
        result = _merge_short_segments(segs)
        assert len(result) == 2
        assert "代码。" in result[0].source_text
        assert result[0].end_time == 3.3

    def test_merges_consecutive_short_segments(self) -> None:
        segs = self._make_timed_segments([
            (0.0, 3.0, "Hello."),
            (3.0, 3.2, "A."),
            (3.2, 3.4, "B."),
            (3.4, 6.0, "Done."),
        ])
        result = _merge_short_segments(segs)
        assert len(result) == 2
        assert "A." in result[0].source_text
        assert "B." in result[0].source_text

    def test_preserves_normal_segments(self) -> None:
        segs = self._make_timed_segments([
            (0.0, 2.5, "Hello world."),
            (2.5, 5.0, "This is a test."),
        ])
        result = _merge_short_segments(segs)
        assert len(result) == 2

    def test_last_short_segment_preserved(self) -> None:
        segs = self._make_timed_segments([
            (0.0, 3.0, "Main text."),
            (3.0, 3.3, "End."),
        ])
        result = _merge_short_segments(segs)
        assert len(result) == 2
        assert result[1].source_text == "End."

    def test_last_segment_above_threshold_kept(self) -> None:
        segs = self._make_timed_segments([
            (0.0, 3.0, "Main text."),
            (3.0, 4.5, "Last one."),
        ])
        result = _merge_short_segments(segs)
        assert len(result) == 2

    def test_empty_input(self) -> None:
        assert _merge_short_segments([]) == []

    def test_single_segment(self) -> None:
        segs = self._make_timed_segments([(0.0, 2.0, "One.")])
        result = _merge_short_segments(segs)
        assert len(result) == 1

    def test_reindexes_merged_output(self) -> None:
        segs = self._make_timed_segments([
            (0.0, 3.0, "A."),
            (3.0, 3.3, "b."),
            (3.3, 6.0, "C."),
            (6.0, 6.2, "d."),
            (6.2, 9.0, "E."),
        ])
        result = _merge_short_segments(segs)
        for idx, seg in enumerate(result):
            assert seg.index == idx
