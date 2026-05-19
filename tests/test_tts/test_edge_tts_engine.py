from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import TTSConfig
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.edge_tts_engine import EdgeTTSEngine


def _make_config(**overrides) -> TTSConfig:
    defaults: dict = {"engine": "edge-tts", "speed": 1.0}
    defaults.update(overrides)
    return TTSConfig(**defaults)


def _make_segments(*texts: str) -> list[SubtitleSegment]:
    return [
        SubtitleSegment(
            index=i, start_time=float(i), end_time=float(i + 1),
            source_text="en", translated_text=t,
        )
        for i, t in enumerate(texts)
    ]


def _mock_audio_duration(duration: float = 2.5) -> MagicMock:
    mock_audio = MagicMock()
    mock_audio.duration_seconds = duration
    return mock_audio


def _patch_tts(audio_duration: float = 2.5):
    stack = ExitStack()
    mock_comm = stack.enter_context(
        patch("src.tts.edge_tts_engine.edge_tts.Communicate"),
    )
    stack.enter_context(
        patch(
            "src.tts.edge_tts_engine.AudioSegment.from_mp3",
            return_value=_mock_audio_duration(audio_duration),
        ),
    )
    stack.mock_comm = mock_comm  # type: ignore[attr-defined]
    return stack


class TestEdgeTTSSynthesize:
    def test_synthesizes_single_segment(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好世界")

        with _patch_tts(3.0) as stack:
            engine.synthesize(segments, tmp_path)
            stack.mock_comm.assert_called_once_with(
                text="你好世界", voice="zh-CN-YunxiNeural", rate="+0%",
            )
            stack.mock_comm.return_value.save_sync.assert_called_once()

        assert segments[0].audio_path == tmp_path / "segments" / "0000.mp3"
        assert segments[0].audio_duration == 3.0

    def test_synthesizes_multiple_segments(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好", "世界")

        with _patch_tts(2.0) as stack:
            engine.synthesize(segments, tmp_path)
            assert stack.mock_comm.call_count == 2
            assert stack.mock_comm.return_value.save_sync.call_count == 2

        assert segments[0].audio_path == tmp_path / "segments" / "0000.mp3"
        assert segments[1].audio_path == tmp_path / "segments" / "0001.mp3"

    def test_skips_empty_translated_text(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好", "   ", "世界")

        with _patch_tts() as stack:
            engine.synthesize(segments, tmp_path)
            assert stack.mock_comm.call_count == 2

        assert segments[0].audio_path != Path()
        assert segments[1].audio_path == Path()
        assert segments[2].audio_path != Path()

    def test_empty_segments_list(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        with _patch_tts() as stack:
            result = engine.synthesize([], tmp_path)
        assert result == []
        stack.mock_comm.assert_not_called()

    def test_creates_segments_directory(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        with _patch_tts():
            engine.synthesize(segments, tmp_path)

        assert (tmp_path / "segments").is_dir()

    def test_progress_callback_called(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好", "世界")
        callbacks: list[ProgressEvent] = []

        with _patch_tts():
            engine.synthesize(segments, tmp_path, callbacks.append)

        assert len(callbacks) == 3
        assert callbacks[0].progress == pytest.approx(0.5)
        assert callbacks[0].message == "正在合成 1/2"
        assert callbacks[1].progress == pytest.approx(1.0)
        assert callbacks[1].message == "正在合成 2/2"
        assert callbacks[2].progress == 1.0
        assert "合成完成" in callbacks[2].message

    def test_empty_last_segment_progress_reaches_one(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好", "   ")
        callbacks: list[ProgressEvent] = []

        with _patch_tts():
            engine.synthesize(segments, tmp_path, callbacks.append)

        last = callbacks[-1]
        assert last.progress == 1.0


class TestEdgeTTSVoiceAndSpeed:
    def test_default_voice_maps_to_yunxi(self, tmp_path: Path) -> None:
        config = _make_config(voice="default")
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        with _patch_tts() as stack:
            engine.synthesize(segments, tmp_path)
            assert stack.mock_comm.call_args.kwargs["voice"] == "zh-CN-YunxiNeural"

    def test_custom_voice_passes_through(self, tmp_path: Path) -> None:
        config = _make_config(voice="zh-CN-XiaoxiaoNeural")
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        with _patch_tts() as stack:
            engine.synthesize(segments, tmp_path)
            assert stack.mock_comm.call_args.kwargs["voice"] == "zh-CN-XiaoxiaoNeural"

    def test_speed_1_5_maps_to_plus_50(self, tmp_path: Path) -> None:
        config = _make_config(speed=1.5)
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        with _patch_tts() as stack:
            engine.synthesize(segments, tmp_path)
            assert stack.mock_comm.call_args.kwargs["rate"] == "+50%"

    def test_speed_0_5_maps_to_minus_50(self, tmp_path: Path) -> None:
        config = _make_config(speed=0.5)
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        with _patch_tts() as stack:
            engine.synthesize(segments, tmp_path)
            assert stack.mock_comm.call_args.kwargs["rate"] == "-50%"


class TestEdgeTTSErrorHandling:
    def test_no_audio_received_raises_pipeline_error(self, tmp_path: Path) -> None:
        import edge_tts as _edge_tts

        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        mock_comm_instance = MagicMock()
        mock_comm_instance.save_sync.side_effect = (
            _edge_tts.exceptions.NoAudioReceived("no audio")
        )

        with patch(
            "src.tts.edge_tts_engine.edge_tts.Communicate",
            return_value=mock_comm_instance,
        ):
            with pytest.raises(PipelineError, match="未收到音频") as exc_info:
                engine.synthesize(segments, tmp_path)
            assert exc_info.value.stage == "TTS"

    def test_websocket_error_raises_pipeline_error(self, tmp_path: Path) -> None:
        import edge_tts as _edge_tts

        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        mock_comm_instance = MagicMock()
        mock_comm_instance.save_sync.side_effect = (
            _edge_tts.exceptions.WebSocketError("ws error")
        )

        with patch(
            "src.tts.edge_tts_engine.edge_tts.Communicate",
            return_value=mock_comm_instance,
        ):
            with pytest.raises(PipelineError, match="WebSocket") as exc_info:
                engine.synthesize(segments, tmp_path)
            assert exc_info.value.stage == "TTS"

    def test_generic_error_raises_pipeline_error(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        mock_comm_instance = MagicMock()
        mock_comm_instance.save_sync.side_effect = RuntimeError("unexpected")

        with patch(
            "src.tts.edge_tts_engine.edge_tts.Communicate",
            return_value=mock_comm_instance,
        ):
            with pytest.raises(PipelineError, match="合成失败") as exc_info:
                engine.synthesize(segments, tmp_path)
            assert exc_info.value.stage == "TTS"

    def test_get_duration_error_wrapped_as_pipeline_error(self, tmp_path: Path) -> None:
        config = _make_config()
        engine = EdgeTTSEngine(config)
        segments = _make_segments("你好")

        mock_comm_instance = MagicMock()
        mock_comm_instance.save_sync.return_value = None

        with (
            patch(
                "src.tts.edge_tts_engine.edge_tts.Communicate",
                return_value=mock_comm_instance,
            ),
            patch(
                "src.tts.edge_tts_engine.AudioSegment.from_mp3",
                side_effect=OSError("ffmpeg not found"),
            ),
            pytest.raises(PipelineError, match="音频时长读取失败") as exc_info,
        ):
            engine.synthesize(segments, tmp_path)
        assert exc_info.value.stage == "TTS"
