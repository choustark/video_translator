from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ASRConfig, TranslationConfig, TTSConfig
from src.exceptions import PipelineError
from src.models import StageStatus, SubtitleSegment
from src.pipeline import STAGE_NAMES, Pipeline
from src.signals import PipelineSignals
from src.utils.temp_manager import compute_video_hash


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        asr=ASRConfig(engine="mlx-whisper", model_path="/asr"),
        translation=TranslationConfig(engine="glm"),
        tts=TTSConfig(engine="cosyvoice", speed=1.0),
    )


def _make_mock_popen(
    stderr_lines: list[bytes] | None = None,
    returncode: int = 0,
    side_effect: type[Exception] | None = None,
) -> MagicMock:
    """创建模拟的 Popen 对象，用于替代 subprocess.Popen。"""
    if side_effect is not None:
        mock_cls = MagicMock(side_effect=side_effect)
        return mock_cls

    mock_proc = MagicMock()
    mock_proc.stderr = iter(stderr_lines or [])
    mock_proc.returncode = returncode
    mock_proc.wait.return_value = None
    mock_proc.terminate.return_value = None
    mock_cls = MagicMock(return_value=mock_proc)
    return mock_cls


def _popen_proc(mock_popen_cls: MagicMock) -> MagicMock:
    """从 mock Popen 类中获取实际的 mock proc 实例。"""
    return mock_popen_cls.return_value


class TestPipelineInit:
    def test_deepcopies_config(self, tmp_path: Path) -> None:
        original = _make_config(tmp_path)
        signals = PipelineSignals()
        pipeline = Pipeline(original, signals)
        original.preset = "fast"
        assert pipeline.config.preset != "fast"

    def test_initial_stage_states(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        assert len(pipeline.states) == 6
        for name in STAGE_NAMES:
            assert pipeline.states[name].status == StageStatus.PENDING


class TestCreateTempDir:
    def test_creates_temp_subdir(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "test.mp4"
        video.write_text("fake video content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        temp_dir = pipeline._create_temp_dir(output_dir, video)

        assert temp_dir.exists()
        assert temp_dir.parent.name == ".temp"
        assert len(temp_dir.name) == 8

    def test_deterministic_hash(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "test.mp4"
        video.write_text("content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        dir1 = pipeline._create_temp_dir(output_dir, video)
        dir2 = pipeline._create_temp_dir(output_dir, video)
        assert dir1 == dir2


class TestCleanupTemp:
    def test_removes_temp_dir(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        temp_dir = tmp_path / ".temp" / "abcd1234"
        temp_dir.mkdir(parents=True)
        (temp_dir / "audio.wav").write_text("fake")

        pipeline._cleanup_temp(temp_dir)

        assert not temp_dir.exists()


class TestStageManagement:
    def test_start_stage_emits_signal(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        emitted: list[str] = []
        pipeline.signals.stage_started.connect(lambda s: emitted.append(s))

        pipeline._start_stage("音频提取")

        assert pipeline.states["音频提取"].status == StageStatus.RUNNING
        assert emitted == ["音频提取"]

    def test_complete_stage_emits_signal(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        completed: list[tuple[str, float]] = []
        pipeline.signals.stage_completed.connect(lambda name, dur: completed.append((name, dur)))

        pipeline._start_stage("ASR")
        pipeline._complete_stage("ASR")

        assert pipeline.states["ASR"].status == StageStatus.COMPLETED
        assert pipeline.states["ASR"].progress == 1.0
        assert completed[0][0] == "ASR"
        assert completed[0][1] >= 0.0

    def test_fail_stage_emits_signal(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        failed: list[tuple[str, str]] = []
        pipeline.signals.stage_failed.connect(lambda name, err: failed.append((name, err)))

        pipeline._fail_stage("TTS", "OOM")

        assert pipeline.states["TTS"].status == StageStatus.FAILED
        assert pipeline.states["TTS"].error == "OOM"
        assert failed == [("TTS", "OOM")]


class TestParseFfmpegTime:
    def test_standard_format(self) -> None:
        line = "frame=  120 fps= 30 q=-1.0 size=    1024kB time=00:00:04.00 bitrate= 2097.2kbits/s speed=   1x"
        assert Pipeline._parse_ffmpeg_time(line) == 4.0

    def test_minutes_and_seconds(self) -> None:
        line = "time=00:01:30.50"
        assert Pipeline._parse_ffmpeg_time(line) == 90.5

    def test_hours(self) -> None:
        line = "time=01:23:45.67"
        assert Pipeline._parse_ffmpeg_time(line) == 3600 + 23 * 60 + 45.67

    def test_zero_time(self) -> None:
        line = "time=00:00:00.00"
        assert Pipeline._parse_ffmpeg_time(line) == 0.0

    def test_no_fractional_seconds(self) -> None:
        line = "time=00:00:05"
        assert Pipeline._parse_ffmpeg_time(line) == 5.0

    def test_no_match_returns_none(self) -> None:
        assert Pipeline._parse_ffmpeg_time("some random output") is None

    def test_empty_string_returns_none(self) -> None:
        assert Pipeline._parse_ffmpeg_time("") is None

    def test_partial_match_not_confused(self) -> None:
        assert Pipeline._parse_ffmpeg_time("timestamp=12345") is None


class TestExtractAudio:
    def test_success(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  120 fps= 30 time=00:00:04.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=10.0),
        ):
            result = pipeline._extract_audio(video, temp_dir)

        assert result == temp_dir / "audio.wav"
        proc = _popen_proc(mock_popen)
        proc.wait.assert_called()

    def test_ffmpeg_not_found(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        mock_popen = _make_mock_popen(side_effect=FileNotFoundError("ffmpeg not found"))

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            pytest.raises(PipelineError) as exc_info,
        ):
            pipeline._extract_audio(video, temp_dir)

        assert exc_info.value.stage == "音频提取"
        assert "ffmpeg 未找到" in str(exc_info.value)

    def test_ffmpeg_nonzero_exit(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        mock_popen = _make_mock_popen(
            stderr_lines=[b"Invalid data found\n"],
            returncode=1,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=0.0),
            pytest.raises(PipelineError) as exc_info,
        ):
            pipeline._extract_audio(video, temp_dir)

        assert exc_info.value.stage == "音频提取"
        assert "音频提取失败" in str(exc_info.value)

    def test_progress_emitted(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        progress_events: list[tuple[str, float]] = []
        pipeline.signals.stage_progress.connect(
            lambda name, pct: progress_events.append((name, pct)),
        )

        mock_popen = _make_mock_popen(
            stderr_lines=[
                b"frame=  30 fps= 30 time=00:00:01.00\n",
                b"frame=  60 fps= 30 time=00:00:02.00\n",
                b"frame=  90 fps= 30 time=00:00:03.00\n",
            ],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=10.0),
        ):
            pipeline._extract_audio(video, temp_dir)

        assert len(progress_events) == 3
        assert progress_events[0] == ("音频提取", 0.1)
        assert progress_events[1] == ("音频提取", 0.2)
        assert progress_events[2] == ("音频提取", 0.3)

    def test_no_progress_when_duration_zero(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        progress_events: list[tuple[str, float]] = []
        pipeline.signals.stage_progress.connect(
            lambda name, pct: progress_events.append((name, pct)),
        )

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=0.0),
        ):
            pipeline._extract_audio(video, temp_dir)

        assert len(progress_events) == 0

    def test_abort_during_extraction(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        pipeline._abort_requested.set()

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=10.0),
            pytest.raises(PipelineError, match="用户中止"),
        ):
            pipeline._extract_audio(video, temp_dir)

    def test_timeout_during_extraction(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=10.0),
            patch("src.pipeline.time.monotonic", side_effect=[0.0, 61.0]),
            pytest.raises(PipelineError, match="音频提取超时"),
        ):
            pipeline._extract_audio(video, temp_dir)

        proc = _popen_proc(mock_popen)
        proc.terminate.assert_called_once()

    def test_process_registered_in_active_processes(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )
        mock_proc = _popen_proc(mock_popen)

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_get_video_duration_safe", return_value=10.0),
        ):
            # 在执行过程中临时追踪 append/remove 调用
            append_calls: list[object] = []
            remove_calls: list[object] = []
            original_list = pipeline._active_processes
            pipeline._active_processes = []  # type: ignore[assignment]

            # 手动追踪 append/remove
            class TrackingList(list):  # type: ignore[type-arg]
                def append(self, item: object) -> None:
                    append_calls.append(item)
                    super().append(item)

                def remove(self, item: object) -> None:
                    remove_calls.append(item)
                    super().remove(item)

            pipeline._active_processes = TrackingList()  # type: ignore[assignment]

            pipeline._extract_audio(video, temp_dir)

        assert mock_proc in append_calls
        assert len(pipeline._active_processes) == 0


class TestProcess:
    def test_full_pipeline_with_mocked_ffmpeg(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake video content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        finished_emitted: list[None] = []
        pipeline.signals.pipeline_finished.connect(lambda: finished_emitted.append(None))

        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = [
            SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hello"),
        ]

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch("src.asr.create_asr_engine", return_value=mock_engine),
            patch("src.translation.create_translation_provider") as mock_trans_factory,
            patch("src.tts.create_tts_engine") as mock_tts_factory,
            patch("src.composer.speed_adapter.SpeedAdapter") as mock_adapter_cls,
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.translate.side_effect = lambda segs, cb=None: segs
            mock_trans_factory.return_value = mock_provider
            mock_tts_engine = MagicMock()
            mock_tts_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            mock_tts_factory.return_value = mock_tts_engine
            mock_adapter = MagicMock()
            mock_adapter.align.side_effect = lambda segs, td, cb=None, **kw: segs
            mock_adapter_cls.return_value = mock_adapter
            mock_srt = MagicMock()
            mock_srt.generate_srt.side_effect = lambda segs, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8"),
                path,
            )[-1]
            mock_srt_cls.return_value = mock_srt
            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_video_duration.return_value = 10.0
            mock_ffmpeg.compose_chinese_audio.return_value = tmp_path / "output" / "audio.wav"
            mock_ffmpeg.compose_video.return_value = tmp_path / "output" / "out.mp4"
            mock_ffmpeg_cls.return_value = mock_ffmpeg
            result = pipeline.process(video, output_dir)

        assert result.success is True
        assert result.audio_path.name == "audio.wav"
        assert result.video_path == video
        assert len(finished_emitted) == 1

        for name in STAGE_NAMES:
            assert pipeline.states[name].status == StageStatus.COMPLETED

    def test_pipeline_failure_emits_finished(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        finished_emitted: list[None] = []
        pipeline.signals.pipeline_finished.connect(lambda: finished_emitted.append(None))

        mock_popen = _make_mock_popen(side_effect=FileNotFoundError("no ffmpeg"))

        with patch("src.pipeline.subprocess.Popen", mock_popen):
            result = pipeline.process(video, output_dir)

        assert result.success is False
        assert result.error is not None
        assert len(finished_emitted) == 1

    def test_generic_exception_uses_current_stage(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        failed: list[tuple[str, str]] = []
        pipeline.signals.stage_failed.connect(lambda name, err: failed.append((name, err)))

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_run_asr", side_effect=RuntimeError("boom")),
        ):
            result = pipeline.process(video, output_dir)

        assert result.success is False
        assert failed[0][0] == "ASR"

    def test_success_cleans_up_temp_dir(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC5: 管线成功完成后自动删除临时目录。"""
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake video content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # 显式设置 event，避免依赖 preload 线程时序
        pipeline._tts_ready_event.set()

        captured_temp_dir: list[Path] = []
        original_create = pipeline._create_temp_dir

        def tracking_create(od: Path, vp: Path) -> Path:
            td = original_create(od, vp)
            captured_temp_dir.append(td)
            return td

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            caplog.at_level(logging.INFO, logger="video_translator"),
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch("src.asr.create_asr_engine") as mock_asr_factory,
            patch("src.translation.create_translation_provider") as mock_trans_factory,
            patch("src.tts.create_tts_engine") as mock_tts_factory,
            patch("src.composer.speed_adapter.SpeedAdapter") as mock_adapter_cls,
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
            patch.object(pipeline, "_create_temp_dir", tracking_create),
        ):
            mock_asr = MagicMock()
            mock_asr.transcribe.return_value = [
                SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hi"),
            ]
            mock_asr_factory.return_value = mock_asr
            mock_provider = MagicMock()
            mock_provider.translate.side_effect = lambda segs, cb=None: segs
            mock_trans_factory.return_value = mock_provider
            mock_tts = MagicMock()
            mock_tts.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            mock_tts_factory.return_value = mock_tts
            mock_adapter = MagicMock()
            mock_adapter.align.side_effect = lambda segs, td, cb=None, **kw: segs
            mock_adapter_cls.return_value = mock_adapter
            mock_srt = MagicMock()
            mock_srt.generate_srt.side_effect = lambda segs, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_text("1\n00:00:00,000 --> 00:00:01,000\n嗨\n", encoding="utf-8"),
                path,
            )[-1]
            mock_srt_cls.return_value = mock_srt
            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_video_duration.return_value = 10.0
            mock_ffmpeg.compose_chinese_audio.return_value = output_dir / "audio.wav"
            mock_ffmpeg.compose_video.return_value = output_dir / "out.mp4"
            mock_ffmpeg_cls.return_value = mock_ffmpeg
            result = pipeline.process(video, output_dir)

        assert result.success is True
        assert len(captured_temp_dir) == 1
        assert not captured_temp_dir[0].exists()
        # AC8: 验证清理日志
        assert any("临时目录 | 清理" in r.message for r in caplog.records)

    def test_failure_preserves_temp_dir(self, tmp_path: Path) -> None:
        """AC6: 管线中途失败时保留临时目录供调试。"""
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake video content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        captured_temp_dir: list[Path] = []
        original_create = pipeline._create_temp_dir

        def tracking_create(od: Path, vp: Path) -> Path:
            td = original_create(od, vp)
            captured_temp_dir.append(td)
            return td

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch.object(pipeline, "_create_temp_dir", tracking_create),
            patch.object(pipeline, "_run_asr", side_effect=RuntimeError("ASR crash")),
        ):
            result = pipeline.process(video, output_dir)

        assert result.success is False
        assert len(captured_temp_dir) == 1
        assert captured_temp_dir[0].exists()


class TestStart:
    def test_spawns_thread_and_finishes(
        self,
        tmp_path: Path,
        qapp,
    ) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        finished: list[None] = []
        pipeline.signals.pipeline_finished.connect(lambda: finished.append(None))

        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = [
            SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hello"),
        ]

        mock_popen = _make_mock_popen(
            stderr_lines=[b"frame=  30 time=00:00:01.00\n"],
            returncode=0,
        )

        with (
            patch("src.pipeline.subprocess.Popen", mock_popen),
            patch("src.asr.create_asr_engine", return_value=mock_engine),
            patch("src.translation.create_translation_provider") as mock_trans_factory,
            patch("src.tts.create_tts_engine") as mock_tts_factory,
            patch("src.composer.speed_adapter.SpeedAdapter") as mock_adapter_cls,
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
        ):
            mock_provider = MagicMock()
            mock_provider.translate.side_effect = lambda segs, cb=None: segs
            mock_trans_factory.return_value = mock_provider
            mock_tts_engine = MagicMock()
            mock_tts_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            mock_tts_factory.return_value = mock_tts_engine
            mock_adapter = MagicMock()
            mock_adapter.align.side_effect = lambda segs, td, cb=None, **kw: segs
            mock_adapter_cls.return_value = mock_adapter
            mock_srt = MagicMock()
            mock_srt.generate_srt.side_effect = lambda segs, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_text("1\n00:00:00,000 --> 00:00:01,000\n你好\n", encoding="utf-8"),
                path,
            )[-1]
            mock_srt_cls.return_value = mock_srt
            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_video_duration.return_value = 10.0
            mock_ffmpeg.compose_chinese_audio.return_value = tmp_path / "output" / "audio.wav"
            mock_ffmpeg.compose_video.return_value = tmp_path / "output" / "out.mp4"
            mock_ffmpeg_cls.return_value = mock_ffmpeg
            pipeline.start(video, output_dir)
            import time

            for _ in range(50):
                qapp.processEvents()
                if finished:
                    break
                time.sleep(0.05)

        assert finished, "pipeline_finished signal was not emitted"


class TestRunASR:
    def test_asr_returns_segments(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        audio = tmp_path / "audio.wav"
        audio.write_text("fake")

        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = [
            SubtitleSegment(index=0, start_time=0.0, end_time=2.0, source_text="Hello"),
        ]

        transcript: list[str] = []
        pipeline.signals.transcript_updated.connect(lambda t: transcript.append(t))

        with patch("src.asr.create_asr_engine", return_value=mock_engine):
            segments = pipeline._run_asr(audio)

        assert len(segments) == 1
        assert segments[0].source_text == "Hello"
        assert transcript == ["Hello"]

    def test_preload_sets_event(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.tts.model_path = str(tmp_path / "models" / "tts")
        pipeline = Pipeline(config, PipelineSignals())

        pipeline._preload_check_tts()
        assert pipeline._tts_ready_event.is_set()


class TestRunTranslation:
    def test_translation_fills_translated_text(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        segments = [
            SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hello"),
            SubtitleSegment(index=1, start_time=1.0, end_time=2.0, source_text="World"),
        ]

        mock_provider = MagicMock()
        translated = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hello",
                translated_text="你好",
            ),
            SubtitleSegment(
                index=1,
                start_time=1.0,
                end_time=2.0,
                source_text="World",
                translated_text="世界",
            ),
        ]
        mock_provider.translate.return_value = translated

        with patch("src.translation.create_translation_provider", return_value=mock_provider):
            result = pipeline._run_translation(segments)

        assert result[0].translated_text == "你好"
        assert result[1].translated_text == "世界"

    def test_translation_emits_bilingual_text(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        segments = [
            SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hello"),
        ]

        mock_provider = MagicMock()
        mock_provider.translate.return_value = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hello",
                translated_text="你好",
            ),
        ]

        transcript: list[str] = []
        pipeline.signals.transcript_updated.connect(lambda t: transcript.append(t))

        with patch("src.translation.create_translation_provider", return_value=mock_provider):
            pipeline._run_translation(segments)

        assert len(transcript) == 1
        assert "[EN] Hello" in transcript[0]
        assert "[中] 你好" in transcript[0]

    def test_translation_emits_stage_progress(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        segments = [SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hi")]

        progress_events: list[tuple[str, float]] = []
        pipeline.signals.stage_progress.connect(
            lambda name, pct: progress_events.append((name, pct))
        )

        def fake_translate(segs, cb=None):
            if cb:
                from src.models import ProgressEvent

                cb(ProgressEvent(stage="翻译", progress=1.0, message="正在翻译 1/1"))
            return [
                SubtitleSegment(
                    index=0,
                    start_time=0.0,
                    end_time=1.0,
                    source_text="Hi",
                    translated_text="嗨",
                )
            ]

        mock_provider = MagicMock()
        mock_provider.translate.side_effect = fake_translate

        with patch("src.translation.create_translation_provider", return_value=mock_provider):
            pipeline._run_translation(segments)

        assert len(progress_events) == 1
        assert progress_events[0] == ("翻译", 1.0)


class TestRunTTS:
    def test_tts_fills_audio_path_and_duration(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hello",
                translated_text="你好",
            ),
        ]

        def fake_synthesize(segs, td, cb=None, **kw):
            segs[0].audio_path = td / "segments" / "0000.mp3"
            segs[0].audio_duration = 2.5
            return segs

        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = fake_synthesize

        with patch("src.tts.create_tts_engine", return_value=mock_engine):
            result = pipeline._run_tts(segments, tmp_path)

        assert result[0].audio_path == tmp_path / "segments" / "0000.mp3"
        assert result[0].audio_duration == 2.5

    def test_tts_emits_stage_progress(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        progress_events: list[tuple[str, float]] = []
        pipeline.signals.stage_progress.connect(
            lambda name, pct: progress_events.append((name, pct)),
        )

        def fake_synthesize(segs, td, cb=None, **kw):
            if cb:
                from src.models import ProgressEvent

                cb(ProgressEvent(stage="TTS", progress=1.0, message="正在合成 1/1"))
            return segs

        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = fake_synthesize

        with patch("src.tts.create_tts_engine", return_value=mock_engine):
            pipeline._run_tts(segments, tmp_path)

        assert len(progress_events) == 1
        assert progress_events[0] == ("TTS", 1.0)

    def test_cosyvoice_degrades_to_chattts(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        call_count = 0

        def mock_create_tts(cfg):
            nonlocal call_count
            call_count += 1
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = PipelineError(
                    "CosyVoice 未安装",
                    stage="TTS",
                )
                return mock_engine
            # ChatTTS fallback succeeds
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "chattts")
        assert call_count == 2

    def test_edge_tts_failure_does_not_degrade(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.tts.engine = "edge-tts"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = PipelineError("TTS 合成失败", stage="TTS")

        with patch("src.tts.create_tts_engine", return_value=mock_engine):
            with pytest.raises(PipelineError, match="TTS 所有引擎均失败"):
                pipeline._run_tts(segments, tmp_path)

    def test_tts_preload_timeout_raises_pipeline_error(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        # Leave _tts_ready_event unset (simulates preload stuck)
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        with (
            patch.object(pipeline._tts_ready_event, "wait", return_value=False),
            pytest.raises(PipelineError, match="预加载超时"),
        ):
            pipeline._run_tts(segments, tmp_path)

    def test_cosyvoice_memory_error_degrades_to_chattts(self, tmp_path: Path) -> None:
        """AC1: MemoryError 触发自动降级到 ChatTTS。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = MemoryError("OOM")
                return mock_engine
            # ChatTTS fallback succeeds
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "chattts")
        assert segments[0].source_text == "Hi"

    def test_cosyvoice_runtime_error_degrades_to_chattts(self, tmp_path: Path) -> None:
        """AC1: RuntimeError（模型加载失败）触发自动降级。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = RuntimeError("model load failed")
                return mock_engine
            # ChatTTS fallback succeeds
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "chattts")

    def test_cosyvoice_import_error_degrades_to_chattts(self, tmp_path: Path) -> None:
        """AC1: ImportError（CosyVoice 未安装）触发自动降级。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = ImportError("No module named 'cosyvoice'")
                return mock_engine
            # ChatTTS fallback succeeds
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "chattts")

    def test_all_engines_fail_raises_pipeline_error(self, tmp_path: Path) -> None:
        """AC5: 所有引擎均失败 → PipelineError(stage=TTS)。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = MemoryError("OOM")
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            with pytest.raises(PipelineError, match="TTS 所有引擎均失败") as exc_info:
                pipeline._run_tts(segments, tmp_path)

        assert exc_info.value.stage == "TTS"
        assert exc_info.value.suggestion is not None
        assert "OOM" in str(exc_info.value)
        # cosyvoice→chattts and chattts→edge-tts
        assert len(degraded_signals) == 2

    def test_cosyvoice_empty_memory_error_degrades(self, tmp_path: Path) -> None:
        """AC1: 空 MemoryError() 降级时日志用类名回退。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = MemoryError()
                return mock_engine
            # ChatTTS fallback succeeds
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            result = pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "chattts")
        assert result[0].source_text == "Hi"

    def test_edge_tts_terminal_engine_no_further_degrade(self, tmp_path: Path) -> None:
        """AC5: Edge-TTS 是终端引擎，失败后不再降级。"""
        config = _make_config(tmp_path)
        config.tts.engine = "edge-tts"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=1.0,
                source_text="Hi",
                translated_text="嗨",
            )
        ]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = RuntimeError("connection failed")

        with patch("src.tts.create_tts_engine", return_value=mock_engine):
            with pytest.raises(PipelineError, match="TTS 所有引擎均失败"):
                pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 0


class TestRunAlignment:
    def test_alignment_overwrites_audio_path(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=2.0,
                source_text="Hi",
                translated_text="嗨",
                audio_path=tmp_path / "segments" / "0000.mp3",
                audio_duration=1.5,
            )
        ]

        def fake_align(segs, td, cb=None):
            segs[0].audio_path = td / "aligned" / "0000.wav"
            segs[0].audio_duration = 2.0
            return segs

        with patch("src.composer.speed_adapter.SpeedAdapter") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.align.side_effect = fake_align
            mock_cls.return_value = mock_instance
            result = pipeline._run_alignment(segments, tmp_path)

        assert result[0].audio_path == tmp_path / "aligned" / "0000.wav"
        assert result[0].audio_duration == 2.0

    def test_alignment_emits_stage_progress(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=2.0,
                source_text="Hi",
                translated_text="嗨",
                audio_path=tmp_path / "segments" / "0000.mp3",
                audio_duration=1.5,
            )
        ]

        progress_events: list[tuple[str, float]] = []
        pipeline.signals.stage_progress.connect(
            lambda name, pct: progress_events.append((name, pct)),
        )

        def fake_align(segs, td, cb=None):
            if cb:
                from src.models import ProgressEvent

                cb(ProgressEvent(stage="语速自适应", progress=1.0, message="正在对齐 1/1"))
            return segs

        with patch("src.composer.speed_adapter.SpeedAdapter") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.align.side_effect = fake_align
            mock_cls.return_value = mock_instance
            pipeline._run_alignment(segments, tmp_path)

        assert len(progress_events) == 1
        assert progress_events[0] == ("语速自适应", 1.0)


class TestRunCompose:
    def test_compose_calls_three_steps(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=2.0,
                source_text="Hello",
                translated_text="你好",
                audio_path=temp_dir / "aligned" / "0000.wav",
                audio_duration=2.0,
            )
        ]

        with (
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
        ):
            mock_srt = MagicMock()
            mock_srt.generate_srt.side_effect = lambda segs, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8"),
                path,
            )[-1]
            mock_srt_cls.return_value = mock_srt

            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_video_duration.return_value = 10.0
            mock_ffmpeg.compose_chinese_audio.return_value = output_dir / "input_chinese_audio.wav"
            mock_ffmpeg.compose_video.return_value = output_dir / "input_translated.mp4"
            mock_ffmpeg_cls.return_value = mock_ffmpeg

            result = pipeline._compose(video, segments, temp_dir, output_dir)

        assert result == output_dir / "input_translated.mp4"
        mock_srt.generate_srt.assert_called_once()
        mock_ffmpeg.get_video_duration.assert_called_once_with(video)
        mock_ffmpeg.compose_chinese_audio.assert_called_once()
        mock_ffmpeg.compose_video.assert_called_once()

    def test_compose_emits_progress(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        segments = [
            SubtitleSegment(
                index=0,
                start_time=0.0,
                end_time=2.0,
                source_text="Hello",
                translated_text="你好",
                audio_path=temp_dir / "aligned" / "0000.wav",
                audio_duration=2.0,
            )
        ]

        progress_events: list[tuple[str, float]] = []
        pipeline.signals.stage_progress.connect(
            lambda name, pct: progress_events.append((name, pct)),
        )

        with (
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
        ):
            mock_srt = MagicMock()
            mock_srt.generate_srt.side_effect = lambda segs, path: (
                path.parent.mkdir(parents=True, exist_ok=True),
                path.write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8"),
                path,
            )[-1]
            mock_srt_cls.return_value = mock_srt

            mock_ffmpeg = MagicMock()
            mock_ffmpeg.get_video_duration.return_value = 10.0
            mock_ffmpeg.compose_chinese_audio.return_value = output_dir / "audio.wav"
            mock_ffmpeg.compose_video.return_value = output_dir / "out.mp4"
            mock_ffmpeg_cls.return_value = mock_ffmpeg

            pipeline._compose(video, segments, temp_dir, output_dir)

        compose_events = [(n, p) for n, p in progress_events if n == "合成"]
        assert len(compose_events) == 3
        assert compose_events[0] == ("合成", 0.33)
        assert compose_events[1] == ("合成", 0.67)
        assert compose_events[2] == ("合成", 1.0)


class TestCheckpoint:
    """断点续传检查点测试（spec 测试策略要求 7 个 pipeline 测试）。"""

    def _setup_pipeline_with_video(self, tmp_path: Path) -> tuple[Pipeline, Path, Path, Path]:
        """构造一个带有真实视频文件的 Pipeline + temp_dir。"""
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "test.mp4"
        video.write_text("fake video content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        temp_dir = pipeline._create_temp_dir(output_dir, video)
        pipeline._video_path = video
        return pipeline, video, output_dir, temp_dir

    def test_load_checkpoint_returns_none_when_no_file(self, tmp_path: Path) -> None:
        """checkpoint.json 不存在时返回 None。"""
        pipeline, _, _, temp_dir = self._setup_pipeline_with_video(tmp_path)
        assert pipeline._load_checkpoint(temp_dir) is None

    def test_load_checkpoint_returns_none_when_corrupted_json(self, tmp_path: Path) -> None:
        """损坏的 JSON 时返回 None（不抛异常）。"""
        pipeline, _, _, temp_dir = self._setup_pipeline_with_video(tmp_path)
        (temp_dir / "checkpoint.json").write_text("{not valid json", encoding="utf-8")
        assert pipeline._load_checkpoint(temp_dir) is None

    def test_load_checkpoint_returns_none_when_video_size_mismatch(self, tmp_path: Path) -> None:
        """异常流程 A：video_size 不匹配，返回 None。"""
        pipeline, video, _, temp_dir = self._setup_pipeline_with_video(tmp_path)
        pipeline._write_checkpoint(temp_dir, ["音频提取", "ASR"], "翻译")
        # 模拟视频被替换（同路径，但大小变化）
        video.write_text("different content with different size")
        assert pipeline._load_checkpoint(temp_dir) is None

    def test_load_checkpoint_returns_none_when_config_hash_mismatch(self, tmp_path: Path) -> None:
        """异常流程 B：config_hash 不匹配，返回 None。"""
        pipeline, _, _, temp_dir = self._setup_pipeline_with_video(tmp_path)
        pipeline._write_checkpoint(temp_dir, ["音频提取", "ASR"], "翻译")
        # 修改配置（影响 config_hash）
        pipeline.config.asr.model_path = "/different/path"
        assert pipeline._load_checkpoint(temp_dir) is None

    def test_load_checkpoint_returns_data_when_valid(self, tmp_path: Path) -> None:
        """正常情况：hash/size 都匹配，返回 checkpoint dict。"""
        pipeline, _, _, temp_dir = self._setup_pipeline_with_video(tmp_path)
        pipeline._write_checkpoint(temp_dir, ["音频提取", "ASR"], "翻译")
        data = pipeline._load_checkpoint(temp_dir)
        assert data is not None
        assert data["completed_stages"] == ["音频提取", "ASR"]
        assert data["current_stage"] == "翻译"

    def test_resume_falls_back_when_segments_missing_but_asr_completed(
        self, tmp_path: Path
    ) -> None:
        """P7：ASR 已 completed 但 segments_checkpoint 缺失 → 回退重跑 ASR。"""
        pipeline, video, output_dir, temp_dir = self._setup_pipeline_with_video(tmp_path)
        # 写入检查点，声称 ASR 已完成
        pipeline._write_checkpoint(temp_dir, ["音频提取", "ASR"], "翻译")
        # 故意不创建 segments_checkpoint.json

        with (
            patch.object(pipeline, "_extract_audio") as mock_extract,
            patch.object(pipeline, "_run_asr") as mock_asr,
            patch.object(pipeline, "_run_translation") as mock_trans,
            patch.object(pipeline, "_run_tts") as mock_tts,
            patch.object(pipeline, "_run_alignment") as mock_align,
            patch.object(pipeline, "_compose"),
        ):
            mock_extract.return_value = temp_dir / "audio.wav"
            (temp_dir / "audio.wav").write_text("fake audio")
            mock_asr.return_value = []
            mock_trans.return_value = []
            mock_tts.return_value = []
            mock_align.return_value = []

            pipeline.process(video, output_dir, resume=True)

        # 由于 segments 缺失，ASR 应该被重新执行（而不是跳过）
        assert mock_asr.called
        # 翻译也应被重新执行
        assert mock_trans.called

    def test_write_checkpoint_preserves_created_at(self, tmp_path: Path) -> None:
        """P6：第二次写入时 created_at 保留首次的时间戳。"""
        pipeline, _, _, temp_dir = self._setup_pipeline_with_video(tmp_path)
        pipeline._write_checkpoint(temp_dir, ["音频提取"], "ASR")
        first_data = json.loads((temp_dir / "checkpoint.json").read_text(encoding="utf-8"))
        first_created = first_data["created_at"]

        # 模拟时间流逝（保证 updated_at 不同）
        import time as _time

        _time.sleep(0.01)
        pipeline._write_checkpoint(temp_dir, ["音频提取", "ASR"], "翻译")
        second_data = json.loads((temp_dir / "checkpoint.json").read_text(encoding="utf-8"))

        assert second_data["created_at"] == first_created
        assert second_data["updated_at"] != first_created


class TestLoadSegmentsCheckpoint:
    """segments_checkpoint.json 加载容错测试（P4）。"""

    def _setup(self, tmp_path: Path) -> tuple[Pipeline, Path]:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "test.mp4"
        video.write_text("content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        temp_dir = output_dir / ".temp" / compute_video_hash(video)
        temp_dir.mkdir(parents=True)
        return pipeline, temp_dir

    def test_returns_empty_when_no_file(self, tmp_path: Path) -> None:
        pipeline, temp_dir = self._setup(tmp_path)
        assert pipeline._load_segments_checkpoint(temp_dir) == []

    def test_returns_empty_when_corrupted_json(self, tmp_path: Path) -> None:
        pipeline, temp_dir = self._setup(tmp_path)
        (temp_dir / "segments_checkpoint.json").write_text("{bad", encoding="utf-8")
        assert pipeline._load_segments_checkpoint(temp_dir) == []

    def test_returns_empty_when_not_list(self, tmp_path: Path) -> None:
        pipeline, temp_dir = self._setup(tmp_path)
        (temp_dir / "segments_checkpoint.json").write_text('{"key": "value"}', encoding="utf-8")
        assert pipeline._load_segments_checkpoint(temp_dir) == []
