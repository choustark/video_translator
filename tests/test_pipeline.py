from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ASRConfig, TranslationConfig, TTSConfig
from src.exceptions import PipelineError
from src.models import StageStatus
from src.pipeline import STAGE_NAMES, Pipeline
from src.signals import PipelineSignals


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        asr=ASRConfig(engine="mlx-whisper", model_path="/asr"),
        translation=TranslationConfig(engine="glm"),
        tts=TTSConfig(engine="cosyvoice"),
    )


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
        pipeline.signals.stage_completed.connect(
            lambda name, dur: completed.append((name, dur))
        )

        pipeline._start_stage("ASR")
        pipeline._complete_stage("ASR")

        assert pipeline.states["ASR"].status == StageStatus.COMPLETED
        assert pipeline.states["ASR"].progress == 1.0
        assert completed[0][0] == "ASR"
        assert completed[0][1] >= 0.0

    def test_fail_stage_emits_signal(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        failed: list[tuple[str, str]] = []
        pipeline.signals.stage_failed.connect(
            lambda name, err: failed.append((name, err))
        )

        pipeline._fail_stage("TTS", "OOM")

        assert pipeline.states["TTS"].status == StageStatus.FAILED
        assert pipeline.states["TTS"].error == "OOM"
        assert failed == [("TTS", "OOM")]


class TestExtractAudio:
    def test_success(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = pipeline._extract_audio(video, temp_dir)

        assert result == temp_dir / "audio.wav"
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "ffmpeg"
        assert "-vn" in cmd
        assert "16000" in cmd

    def test_ffmpeg_called_process_error(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "ffmpeg", stderr=b"Invalid data found"
            )
            with pytest.raises(PipelineError) as exc_info:
                pipeline._extract_audio(video, temp_dir)

        assert exc_info.value.stage == "音频提取"
        assert "音频提取失败" in str(exc_info.value)

    def test_ffmpeg_timeout(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired("ffmpeg", 60)
            with pytest.raises(PipelineError) as exc_info:
                pipeline._extract_audio(video, temp_dir)

        assert exc_info.value.stage == "音频提取"
        assert "超时" in str(exc_info.value)

    def test_ffmpeg_not_found(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        temp_dir = tmp_path / "temp"
        temp_dir.mkdir()

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("ffmpeg not found")
            with pytest.raises(PipelineError) as exc_info:
                pipeline._extract_audio(video, temp_dir)

        assert exc_info.value.stage == "音频提取"
        assert "ffmpeg 未找到" in str(exc_info.value)


class TestProcess:
    def test_full_pipeline_with_mocked_ffmpeg(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake video content")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        finished_emitted: list[None] = []
        pipeline.signals.pipeline_finished.connect(
            lambda: finished_emitted.append(None)
        )

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
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
        pipeline.signals.pipeline_finished.connect(
            lambda: finished_emitted.append(None)
        )

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("no ffmpeg")
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
        pipeline.signals.stage_failed.connect(
            lambda name, err: failed.append((name, err))
        )

        with (
            patch("src.pipeline.subprocess.run") as mock_run,
            patch.object(pipeline, "_run_asr", side_effect=RuntimeError("boom")),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = pipeline.process(video, output_dir)

        assert result.success is False
        assert failed[0][0] == "ASR"


class TestStart:
    def test_spawns_thread_and_finishes(
        self, tmp_path: Path, qapp,
    ) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        video = tmp_path / "input.mp4"
        video.write_text("fake")
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        finished: list[None] = []
        pipeline.signals.pipeline_finished.connect(lambda: finished.append(None))

        with patch("src.pipeline.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            pipeline.start(video, output_dir)
            import time

            for _ in range(50):
                qapp.processEvents()
                if finished:
                    break
                time.sleep(0.05)

        assert finished, "pipeline_finished signal was not emitted"
