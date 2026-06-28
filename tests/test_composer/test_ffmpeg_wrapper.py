from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.composer.ffmpeg_wrapper import FFmpegWrapper
from src.exceptions import PipelineError
from src.models import SubtitleSegment


def _seg(
    index: int,
    start: float,
    end: float,
    translated: str = "",
    audio_path: str = "",
    audio_duration: float = 0.0,
) -> SubtitleSegment:
    return SubtitleSegment(
        index=index,
        start_time=start,
        end_time=end,
        source_text="en",
        translated_text=translated,
        audio_path=Path(audio_path) if audio_path else Path(),
        audio_duration=audio_duration,
    )


class TestGetVideoDuration:
    def test_parses_ffprobe_output(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "video.mp4"
        video.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(stdout="600.123456\n")
            duration = wrapper.get_video_duration(video)

        assert duration == 600.123456
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffprobe"
        assert str(video) in cmd

    def test_ffprobe_failure_raises_pipeline_error(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "video.mp4"
        video.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "ffprobe", stderr=b"No such file"
            )
            with pytest.raises(PipelineError, match="ffprobe"):
                wrapper.get_video_duration(video)

    def test_ffprobe_not_found(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "video.mp4"
        video.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("ffprobe not found")
            with pytest.raises(PipelineError, match="ffprobe"):
                wrapper.get_video_duration(video)

    def test_ffprobe_timeout(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "video.mp4"
        video.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ffprobe", 30)
            with pytest.raises(PipelineError, match="超时"):
                wrapper.get_video_duration(video)


class TestComposeChineseAudio:
    def test_builds_concat_list_with_silence_gaps(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        seg0_path = tmp_path / "aligned" / "0000.wav"
        seg1_path = tmp_path / "aligned" / "0001.wav"
        seg0_path.parent.mkdir(parents=True)
        seg0_path.write_text("a")
        seg1_path.write_text("b")

        segments = [
            _seg(0, 1.0, 3.0, audio_path=str(seg0_path), audio_duration=2.0),
            _seg(1, 4.0, 6.0, audio_path=str(seg1_path), audio_duration=2.0),
        ]
        output = tmp_path / "output.wav"
        video_duration = 10.0

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            wrapper.compose_chinese_audio(segments, video_duration, tmp_path, output)

        assert mock_run.call_count >= 2  # silence files + concat

        # Verify concat command was called
        concat_calls = [
            c for c in mock_run.call_args_list if "-f" in c[0][0] and "concat" in c[0][0]
        ]
        assert len(concat_calls) == 1
        concat_cmd = concat_calls[0][0][0]
        assert str(output) in concat_cmd

    def test_skips_segments_without_audio(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        seg0_path = tmp_path / "aligned" / "0000.wav"
        seg0_path.parent.mkdir(parents=True)
        seg0_path.write_text("a")

        segments = [
            _seg(0, 0.0, 2.0, audio_path=str(seg0_path), audio_duration=2.0),
            _seg(1, 2.0, 4.0),
            _seg(2, 4.0, 6.0, audio_path=str(seg0_path), audio_duration=2.0),
        ]
        output = tmp_path / "output.wav"

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            wrapper.compose_chinese_audio(segments, 10.0, tmp_path, output)

        assert output.parent == tmp_path

    def test_no_valid_segments_raises_error(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        segments = [_seg(0, 0.0, 1.0)]
        output = tmp_path / "output.wav"

        with pytest.raises(PipelineError, match="没有有效的音频段"):
            wrapper.compose_chinese_audio(segments, 10.0, tmp_path, output)

    def test_single_segment_no_gap(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        seg_path = tmp_path / "aligned" / "0000.wav"
        seg_path.parent.mkdir(parents=True)
        seg_path.write_text("a")

        segments = [
            _seg(0, 0.0, 2.0, audio_path=str(seg_path), audio_duration=2.0),
        ]
        output = tmp_path / "output.wav"

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            wrapper.compose_chinese_audio(segments, 5.0, tmp_path, output)

        assert mock_run.called

    def test_ffmpeg_failure_raises_pipeline_error(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        seg_path = tmp_path / "aligned" / "0000.wav"
        seg_path.parent.mkdir(parents=True)
        seg_path.write_text("a")

        segments = [
            _seg(0, 0.0, 2.0, audio_path=str(seg_path), audio_duration=2.0),
        ]
        output = tmp_path / "output.wav"

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"error")
            with pytest.raises(PipelineError, match="合成"):
                wrapper.compose_chinese_audio(segments, 5.0, tmp_path, output)


class TestComposeVideo:
    def test_uses_subtitles_filter(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "input.mp4"
        audio = tmp_path / "chinese.wav"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "output.mp4"
        for f in [video, audio, srt]:
            f.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            wrapper.compose_video(video, audio, srt, output)

        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-map" in cmd
        idx_map = cmd.index("-map")
        assert cmd[idx_map + 1] == "0:v"
        assert cmd[idx_map + 3] == "1:a"
        # Check subtitles filter is in -vf argument
        vf_idx = cmd.index("-vf")
        assert "subtitles=" in cmd[vf_idx + 1]

    def test_replaces_audio_completely(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "input.mp4"
        audio = tmp_path / "chinese.wav"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "output.mp4"
        for f in [video, audio, srt]:
            f.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            wrapper.compose_video(video, audio, srt, output)

        cmd = mock_run.call_args[0][0]
        assert "-map" in cmd
        map_values = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-map"]
        assert "0:v" in map_values
        assert "1:a" in map_values

    def test_ffmpeg_failure(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "input.mp4"
        audio = tmp_path / "chinese.wav"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "output.mp4"
        for f in [video, audio, srt]:
            f.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "ffmpeg", stderr=b"encode error"
            )
            with pytest.raises(PipelineError, match="合成"):
                wrapper.compose_video(video, audio, srt, output)

    def test_ffmpeg_not_found(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "input.mp4"
        audio = tmp_path / "chinese.wav"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "output.mp4"
        for f in [video, audio, srt]:
            f.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("no ffmpeg")
            with pytest.raises(PipelineError, match="ffmpeg 未找到"):
                wrapper.compose_video(video, audio, srt, output)

    def test_ffmpeg_timeout(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "input.mp4"
        audio = tmp_path / "chinese.wav"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "output.mp4"
        for f in [video, audio, srt]:
            f.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 300)
            with pytest.raises(PipelineError, match="超时"):
                wrapper.compose_video(video, audio, srt, output)

    def test_timeout_is_300(self, tmp_path: Path) -> None:
        wrapper = FFmpegWrapper()
        video = tmp_path / "input.mp4"
        audio = tmp_path / "chinese.wav"
        srt = tmp_path / "subs.srt"
        output = tmp_path / "output.mp4"
        for f in [video, audio, srt]:
            f.write_text("fake")

        with patch("src.composer.ffmpeg_wrapper.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            wrapper.compose_video(video, audio, srt, output)

        assert mock_run.call_args[1].get("timeout") == 300
