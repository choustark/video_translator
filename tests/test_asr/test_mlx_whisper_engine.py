from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.asr.mlx_whisper_engine import _ASR_MEMORY_REQUIREMENT_GB, MLXWhisperEngine
from src.config import ASRConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent


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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc"),
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=_ASR_MEMORY_REQUIREMENT_GB * 1024 ** 3 + 1,
            )
            engine.transcribe("/tmp/audio.wav")

        mock_mlx.transcribe.assert_called_once_with(
            "/tmp/audio.wav",
            path_or_hf_repo=config.model_path,
            language=config.language,
            word_timestamps=True,
            verbose=False,
        )


class TestMemoryCheck:
    def test_raises_when_memory_low(self) -> None:
        engine = MLXWhisperEngine(_make_config())

        with patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil:
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
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
            patch("src.asr.mlx_whisper_engine.psutil") as mock_psutil,
            patch("src.asr.mlx_whisper_engine.gc") as mock_gc,
            patch.dict(sys.modules, {"mlx_whisper": mock_mlx}),
        ):
            mock_psutil.virtual_memory.return_value = MagicMock(
                available=10 * 1024 ** 3,
            )
            engine.transcribe("/tmp/audio.wav")

        mock_gc.collect.assert_called_once()
