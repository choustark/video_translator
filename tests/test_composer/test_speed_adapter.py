from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.composer.speed_adapter import SpeedAdapter
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

_FFMPEG = "src.composer.speed_adapter.subprocess.run"
_PYDUB = "src.composer.speed_adapter.AudioSegment.from_wav"


def _make_segments(*durations: tuple[float, float, float]) -> list[SubtitleSegment]:
    """Create segments: (start_time, end_time, audio_duration) tuples."""
    return [
        SubtitleSegment(
            index=i,
            start_time=start,
            end_time=end,
            source_text="en",
            translated_text="zh",
            audio_path=Path(f"/fake/segments/{i:04d}.mp3"),
            audio_duration=dur,
        )
        for i, (start, end, dur) in enumerate(durations)
    ]


def _mock_pydub_wav(duration: float = 2.0) -> MagicMock:
    mock_audio = MagicMock()
    mock_audio.duration_seconds = duration
    return mock_audio


def _patch_ffmpeg(audio_duration: float = 2.0):
    from contextlib import ExitStack

    stack = ExitStack()
    mock_run = stack.enter_context(
        patch(_FFMPEG, return_value=MagicMock(returncode=0)),
    )
    stack.enter_context(
        patch(_PYDUB, return_value=_mock_pydub_wav(audio_duration)),
    )
    stack.mock_run = mock_run  # type: ignore[attr-defined]
    return stack


class TestSpeedAdapterPad:
    def test_audio_shorter_pads_centered(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 3.0, 2.0))

        with _patch_ffmpeg(3.0) as stack:
            result = adapter.align(segments, tmp_path)

        mock_run = stack.mock_run
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "adelay=500|500" in cmd_str
        assert "apad=whole_dur=3.000" in cmd_str
        assert result[0].audio_path == tmp_path / "aligned" / "0000.wav"

    def test_pad_creates_aligned_directory(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 1.0))

        with _patch_ffmpeg(2.0):
            adapter.align(segments, tmp_path)

        assert (tmp_path / "aligned").is_dir()


class TestSpeedAdapterSpeedUp:
    def test_audio_longer_speeds_up(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 3.0))

        with _patch_ffmpeg(2.0) as stack:
            result = adapter.align(segments, tmp_path)

        mock_run = stack.mock_run
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "atempo=1.5000" in cmd_str or "rubberband=tempo=1.5000" in cmd_str
        assert result[0].audio_path == tmp_path / "aligned" / "0000.wav"

    def test_audio_too_long_skips_speedup(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 1.0, 3.0))

        with _patch_ffmpeg(3.0) as stack:
            result = adapter.align(segments, tmp_path)

        mock_run = stack.mock_run
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        assert "atempo" not in cmd_str and "rubberband" not in cmd_str
        assert result[0].audio_path == tmp_path / "aligned" / "0000.wav"


class TestSpeedAdapterExactMatch:
    def test_audio_exact_duration_copies(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 2.0))

        with _patch_ffmpeg(2.0) as stack:
            adapter.align(segments, tmp_path)

        mock_run = stack.mock_run
        assert mock_run.call_count == 1
        cmd = mock_run.call_args[0][0]
        assert "-ar" in cmd
        assert "16000" in cmd


class TestSpeedAdapterSkipSegments:
    def test_skips_segment_with_no_audio_path(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        seg = SubtitleSegment(index=0, start_time=0.0, end_time=2.0, source_text="en")
        segments = [seg]

        with patch(_FFMPEG) as mock_run:
            result = adapter.align(segments, tmp_path)

        mock_run.assert_not_called()
        assert result[0].audio_path == Path()

    def test_skips_segment_with_zero_duration(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        seg = SubtitleSegment(
            index=0,
            start_time=0.0,
            end_time=2.0,
            source_text="en",
            translated_text="zh",
            audio_path=Path("/fake/0000.mp3"),
            audio_duration=0.0,
        )
        segments = [seg]

        with patch(_FFMPEG) as mock_run:
            adapter.align(segments, tmp_path)

        mock_run.assert_not_called()

    def test_empty_segments_returns_empty(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        with patch(_FFMPEG) as mock_run:
            result = adapter.align([], tmp_path)
        assert result == []
        mock_run.assert_not_called()


class TestSpeedAdapterProgress:
    def test_progress_callback_called(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 1.0), (2.0, 4.0, 1.5))
        callbacks: list[ProgressEvent] = []

        with _patch_ffmpeg(2.0):
            adapter.align(segments, tmp_path, callbacks.append)

        assert len(callbacks) == 3
        assert callbacks[0].progress == pytest.approx(0.5)
        assert callbacks[0].message == "正在对齐 1/2"
        assert callbacks[1].progress == pytest.approx(1.0)
        assert callbacks[1].message == "正在对齐 2/2"
        assert callbacks[2].progress == 1.0
        assert "对齐完成" in callbacks[2].message


class TestSpeedAdapterDeviation:
    def test_single_deviation_warning_logged(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 1.0, 2.0))

        with _patch_ffmpeg(2.0):
            with patch("src.composer.speed_adapter.logger") as mock_logger:
                adapter.align(segments, tmp_path)
                mock_logger.warning.assert_any_call(
                    "对齐 | 偏差过大 | seg=%d target=%.3f actual=%.3f deviation=%.1f%%",
                    0,
                    1.0,
                    2.0,
                    100.0,
                )

    def test_global_deviation_warning_logged(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments(
            (0.0, 1.0, 0.8),
            (1.0, 2.0, 0.8),
        )

        with _patch_ffmpeg(1.5):
            with patch("src.composer.speed_adapter.logger") as mock_logger:
                adapter.align(segments, tmp_path)
                calls = mock_logger.warning.call_args_list
                global_calls = [c for c in calls if "全局偏差" in str(c)]
                assert len(global_calls) == 1


class TestSpeedAdapterFFmpegErrors:
    def test_called_process_error_raises_pipeline_error(self, tmp_path: Path) -> None:
        import subprocess

        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 1.0))

        with patch(_FFMPEG) as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1,
                "ffmpeg",
                stderr=b"Invalid data",
            )
            with pytest.raises(PipelineError, match="ffmpeg 对齐失败") as exc_info:
                adapter.align(segments, tmp_path)
            assert exc_info.value.stage == "语速自适应"

    def test_timeout_raises_pipeline_error(self, tmp_path: Path) -> None:
        import subprocess

        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 1.0))

        with patch(_FFMPEG) as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 30)
            with pytest.raises(PipelineError, match="超时"):
                adapter.align(segments, tmp_path)

    def test_ffmpeg_not_found_raises_pipeline_error(self, tmp_path: Path) -> None:
        adapter = SpeedAdapter()
        segments = _make_segments((0.0, 2.0, 1.0))

        with patch(_FFMPEG) as mock_run:
            mock_run.side_effect = FileNotFoundError("ffmpeg not found")
            with pytest.raises(PipelineError, match="ffmpeg 未找到"):
                adapter.align(segments, tmp_path)
