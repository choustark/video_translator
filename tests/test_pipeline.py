from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.config import AppConfig, ASRConfig, TranslationConfig, TTSConfig
from src.exceptions import PipelineError
from src.models import StageStatus, SubtitleSegment
from src.pipeline import STAGE_NAMES, Pipeline
from src.signals import PipelineSignals


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        asr=ASRConfig(engine="mlx-whisper", model_path="/asr"),
        translation=TranslationConfig(engine="glm"),
        tts=TTSConfig(engine="cosyvoice", speed=1.0),
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

        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = [
            SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hello"),
        ]

        with (
            patch("src.pipeline.subprocess.run") as mock_run,
            patch("src.asr.create_asr_engine", return_value=mock_engine),
            patch("src.translation.create_translation_provider") as mock_trans_factory,
            patch("src.tts.create_tts_engine") as mock_tts_factory,
            patch("src.composer.speed_adapter.SpeedAdapter") as mock_adapter_cls,
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
        ):
            mock_run.return_value = MagicMock(returncode=0)
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

    def test_success_cleans_up_temp_dir(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture,
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

        with (
            caplog.at_level(logging.INFO, logger="video_translator"),
            patch("src.pipeline.subprocess.run") as mock_run,
            patch("src.asr.create_asr_engine") as mock_asr_factory,
            patch("src.translation.create_translation_provider") as mock_trans_factory,
            patch("src.tts.create_tts_engine") as mock_tts_factory,
            patch("src.composer.speed_adapter.SpeedAdapter") as mock_adapter_cls,
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
            patch.object(pipeline, "_create_temp_dir", tracking_create),
        ):
            mock_run.return_value = MagicMock(returncode=0)
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

        with (
            patch("src.pipeline.subprocess.run") as mock_run,
            patch.object(pipeline, "_create_temp_dir", tracking_create),
            patch.object(pipeline, "_run_asr", side_effect=RuntimeError("ASR crash")),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = pipeline.process(video, output_dir)

        assert result.success is False
        assert len(captured_temp_dir) == 1
        assert captured_temp_dir[0].exists()


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

        mock_engine = MagicMock()
        mock_engine.transcribe.return_value = [
            SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hello"),
        ]

        with (
            patch("src.pipeline.subprocess.run") as mock_run,
            patch("src.asr.create_asr_engine", return_value=mock_engine),
            patch("src.translation.create_translation_provider") as mock_trans_factory,
            patch("src.tts.create_tts_engine") as mock_tts_factory,
            patch("src.composer.speed_adapter.SpeedAdapter") as mock_adapter_cls,
            patch("src.composer.subtitle_generator.SubtitleGenerator") as mock_srt_cls,
            patch("src.composer.ffmpeg_wrapper.FFmpegWrapper") as mock_ffmpeg_cls,
        ):
            mock_run.return_value = MagicMock(returncode=0)
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
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hello", translated_text="你好",
            ),
            SubtitleSegment(
                index=1, start_time=1.0, end_time=2.0,
                source_text="World", translated_text="世界",
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
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hello", translated_text="你好",
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
            return [SubtitleSegment(
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hi", translated_text="嗨",
            )]

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
                index=0, start_time=0.0, end_time=1.0,
                source_text="Hello", translated_text="你好",
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
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

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

    def test_cosyvoice_degrades_to_edge_tts(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

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
                    "CosyVoice 未安装", stage="TTS",
                )
                return mock_engine
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "edge-tts")
        assert call_count == 2

    def test_edge_tts_failure_does_not_degrade(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = PipelineError("TTS 合成失败", stage="TTS")

        with patch("src.tts.create_tts_engine", return_value=mock_engine):
            with pytest.raises(PipelineError, match="合成失败"):
                pipeline._run_tts(segments, tmp_path)

    def test_tts_preload_timeout_raises_pipeline_error(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        # Leave _tts_ready_event unset (simulates preload stuck)
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        with (
            patch.object(pipeline._tts_ready_event, "wait", return_value=False),
            pytest.raises(PipelineError, match="预加载超时"),
        ):
            pipeline._run_tts(segments, tmp_path)

    def test_cosyvoice_memory_error_degrades_to_edge_tts(self, tmp_path: Path) -> None:
        """AC1: MemoryError 触发自动降级到 Edge-TTS。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = MemoryError("OOM")
                return mock_engine
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "edge-tts")
        assert segments[0].source_text == "Hi"

    def test_cosyvoice_runtime_error_degrades_to_edge_tts(self, tmp_path: Path) -> None:
        """AC1: RuntimeError（模型加载失败）触发自动降级。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = RuntimeError("model load failed")
                return mock_engine
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "edge-tts")

    def test_cosyvoice_import_error_degrades_to_edge_tts(self, tmp_path: Path) -> None:
        """AC1: ImportError（CosyVoice 未安装）触发自动降级。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = ImportError("No module named 'cosyvoice'")
                return mock_engine
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert degraded_signals[0] == ("cosyvoice", "edge-tts")

    def test_cosyvoice_degrades_edge_tts_also_fails(self, tmp_path: Path) -> None:
        """AC5: CosyVoice 降级后 Edge-TTS 也失败 → PipelineError(stage=TTS)。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = MemoryError("OOM")
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            with pytest.raises(PipelineError, match="CosyVoice 失败.*Edge-TTS 也失败") as exc_info:
                pipeline._run_tts(segments, tmp_path)

        assert exc_info.value.stage == "TTS"
        assert exc_info.value.suggestion is not None
        assert "OOM" in str(exc_info.value)
        assert len(degraded_signals) == 1

    def test_cosyvoice_empty_memory_error_degrades(self, tmp_path: Path) -> None:
        """AC1: 空 MemoryError() 降级时日志用类名回退。"""
        config = _make_config(tmp_path)
        config.tts.engine = "cosyvoice"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        def mock_create_tts(cfg):
            if cfg.engine == "cosyvoice":
                mock_engine = MagicMock()
                mock_engine.synthesize.side_effect = MemoryError()
                return mock_engine
            mock_engine = MagicMock()
            mock_engine.synthesize.side_effect = lambda segs, td, cb=None, **kw: segs
            return mock_engine

        with patch("src.tts.create_tts_engine", side_effect=mock_create_tts):
            result = pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 1
        assert result[0].source_text == "Hi"

    def test_non_cosyvoice_memory_error_does_not_degrade(self, tmp_path: Path) -> None:
        """AC5: 非 CosyVoice 引擎失败时不降级，直接抛异常。"""
        config = _make_config(tmp_path)
        config.tts.engine = "edge-tts"
        pipeline = Pipeline(config, PipelineSignals())
        pipeline._tts_ready_event.set()
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=1.0,
            source_text="Hi", translated_text="嗨",
        )]

        degraded_signals: list[tuple[str, str]] = []
        pipeline.signals.tts_degraded.connect(
            lambda orig, fallback: degraded_signals.append((orig, fallback)),
        )

        mock_engine = MagicMock()
        mock_engine.synthesize.side_effect = RuntimeError("connection failed")

        with patch("src.tts.create_tts_engine", return_value=mock_engine):
            with pytest.raises(RuntimeError, match="connection failed"):
                pipeline._run_tts(segments, tmp_path)

        assert len(degraded_signals) == 0


class TestRunAlignment:
    def test_alignment_overwrites_audio_path(self, tmp_path: Path) -> None:
        pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=2.0,
            source_text="Hi", translated_text="嗨",
            audio_path=tmp_path / "segments" / "0000.mp3",
            audio_duration=1.5,
        )]

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
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=2.0,
            source_text="Hi", translated_text="嗨",
            audio_path=tmp_path / "segments" / "0000.mp3",
            audio_duration=1.5,
        )]

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
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=2.0,
            source_text="Hello", translated_text="你好",
            audio_path=temp_dir / "aligned" / "0000.wav",
            audio_duration=2.0,
        )]

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
        segments = [SubtitleSegment(
            index=0, start_time=0.0, end_time=2.0,
            source_text="Hello", translated_text="你好",
            audio_path=temp_dir / "aligned" / "0000.wav",
            audio_duration=2.0,
        )]

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
