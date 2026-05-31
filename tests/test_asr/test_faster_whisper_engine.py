from __future__ import annotations

import gc
import sys
from collections import namedtuple
from unittest.mock import MagicMock, patch

import pytest

from src.asr._helpers import _DEFAULT_PROPER_NOUNS
from src.asr.faster_whisper_engine import FasterWhisperEngine
from src.config import ASRConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

_ASRL_MEMORY_REQUIREMENT_GB = 6.0

# faster-whisper Segment namedtuple（与库实际返回结构匹配）
_Segment = namedtuple("_Segment", ["id", "seek", "start", "end", "text"])


def _make_config(**overrides) -> ASRConfig:
    defaults = {"engine": "faster-whisper", "model_path": "models/asr/whisper-medium"}
    defaults.update(overrides)
    return ASRConfig(**defaults)


def _mock_segments() -> list[_Segment]:
    return [
        _Segment(id=0, seek=0, start=0.0, end=2.5, text="Hello world."),
        _Segment(id=1, seek=0, start=2.5, end=5.0, text=" This is a test."),
    ]


def _mock_model(segments: list[_Segment] | None = None, duration: float = 5.0) -> MagicMock:
    if segments is None:
        segments = _mock_segments()
    mock = MagicMock()
    mock_info = MagicMock(duration=duration)
    mock.transcribe.return_value = (iter(segments), mock_info)
    return mock


class TestTranscribe:
    def test_returns_subtitle_segments(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        model = _mock_model()

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASRL_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            segments = engine.transcribe("/tmp/audio.wav")

        assert len(segments) == 2
        assert segments[0].start_time == 0.0
        assert segments[0].end_time == 2.5
        assert segments[0].source_text == "Hello world."
        assert segments[0].index == 0
        assert segments[1].source_text == "This is a test."

    def test_filters_empty_segments(self) -> None:
        segments = [
            _Segment(id=0, seek=0, start=0.0, end=1.0, text="Hello."),
            _Segment(id=1, seek=0, start=1.0, end=2.0, text="   "),
            _Segment(id=2, seek=0, start=2.0, end=3.0, text=""),
        ]
        engine = FasterWhisperEngine(_make_config())
        model = _mock_model(segments=segments, duration=3.0)

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASRL_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            result = engine.transcribe("/tmp/audio.wav")

        assert len(result) == 1
        assert result[0].source_text == "Hello."

    def test_calls_whisper_model_with_correct_params(self) -> None:
        config = _make_config()
        engine = FasterWhisperEngine(config)
        model = _mock_model(segments=[])
        mock_fw = MagicMock()
        mock_fw.WhisperModel.return_value = model

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": mock_fw}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASRL_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        mock_fw.WhisperModel.assert_called_once_with(
            config.model_path,
            device="cpu",
            compute_type="int8",
        )

    def test_transcribe_called_with_language_and_prompt(self) -> None:
        config = _make_config()
        engine = FasterWhisperEngine(config)
        model = _mock_model(segments=[])

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASRL_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        model.transcribe.assert_called_once()
        call_kwargs = model.transcribe.call_args
        assert call_kwargs.kwargs.get("language") == "en" or call_kwargs[1].get("language") == "en"

    def test_includes_custom_proper_nouns_in_prompt(self) -> None:
        config = _make_config(proper_nouns=["MyCustomTool"])
        engine = FasterWhisperEngine(config)
        model = _mock_model(segments=[])

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASRL_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        call_kwargs = model.transcribe.call_args
        prompt = call_kwargs.kwargs.get("initial_prompt", call_kwargs[1].get("initial_prompt", ""))
        assert "MyCustomTool" in prompt


class TestMemoryCheck:
    def test_raises_when_memory_low(self) -> None:
        engine = FasterWhisperEngine(_make_config())

        with patch("src.asr._helpers.psutil") as mock_psutil:
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=1 * 1024 ** 3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "内存不足" in str(exc_info.value)

    def test_passes_when_memory_sufficient(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        model = _mock_model(segments=[])

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            result = engine.transcribe("/tmp/audio.wav")

        assert result == []


class TestImportError:
    def test_raises_when_faster_whisper_not_installed(self) -> None:
        engine = FasterWhisperEngine(_make_config())

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": None}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "faster-whisper" in str(exc_info.value)

    def test_raises_when_transcribe_fails(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        model = MagicMock()
        model.transcribe.side_effect = RuntimeError("model not found")

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            with pytest.raises(PipelineError) as exc_info:
                engine.transcribe("/tmp/audio.wav")

        assert exc_info.value.stage == "ASR"
        assert "ASR 转录失败" in str(exc_info.value)


class TestProgressCallback:
    def test_calls_callback_during_iteration(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        model = _mock_model()
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        # 2 segments → 2 progress events
        assert len(events) == 2
        assert events[0].stage == "ASR"
        assert events[-1].progress == 1.0

    def test_progress_increases_monotonically(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        segments = [_Segment(id=i, seek=0, start=float(i), end=float(i + 1), text=f"seg {i}")
                    for i in range(5)]
        model = _mock_model(segments=segments, duration=5.0)
        events: list[ProgressEvent] = []

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            engine.transcribe(
                "/tmp/audio.wav",
                progress_callback=lambda e: events.append(e),
            )

        for i in range(1, len(events)):
            assert events[i].progress >= events[i - 1].progress

    def test_no_callback_when_none(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        model = _mock_model()

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc"),
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            result = engine.transcribe("/tmp/audio.wav", progress_callback=None)

        assert len(result) == 2


class TestGCRelease:
    def test_calls_gc_collect(self) -> None:
        engine = FasterWhisperEngine(_make_config())
        model = _mock_model(segments=[])

        with (
            patch("src.asr._helpers.psutil") as mock_psutil,
            patch("src.asr.faster_whisper_engine.gc") as mock_gc,
            patch.dict(sys.modules, {"faster_whisper": MagicMock(WhisperModel=MagicMock(return_value=model))}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            engine.transcribe("/tmp/audio.wav")

        mock_gc.collect.assert_called()
