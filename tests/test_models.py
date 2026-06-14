from pathlib import Path

from src.models import PipelineResult, ProgressEvent, StageState, StageStatus, SubtitleSegment


class TestSubtitleSegment:
    def test_create_with_required_fields(self) -> None:
        seg = SubtitleSegment(index=0, start_time=1.0, end_time=3.5, source_text="Hello")
        assert seg.index == 0
        assert seg.start_time == 1.0
        assert seg.end_time == 3.5
        assert seg.source_text == "Hello"

    def test_default_values(self) -> None:
        seg = SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="Hi")
        assert seg.translated_text == ""
        assert seg.audio_path == Path()
        assert seg.audio_duration == 0.0

    def test_index_is_zero_based(self) -> None:
        seg = SubtitleSegment(index=0, start_time=0.0, end_time=1.0, source_text="a")
        assert seg.index == 0

    def test_timestamps_are_seconds_float(self) -> None:
        seg = SubtitleSegment(index=0, start_time=1.23, end_time=4.56, source_text="")
        assert isinstance(seg.start_time, float)
        assert isinstance(seg.end_time, float)

    def test_all_fields_populated(self) -> None:
        seg = SubtitleSegment(
            index=5,
            start_time=10.0,
            end_time=15.0,
            source_text="original",
            translated_text="翻译",
            audio_path=Path("/tmp/audio.wav"),
            audio_duration=4.8,
        )
        assert seg.index == 5
        assert seg.translated_text == "翻译"
        assert seg.audio_path == Path("/tmp/audio.wav")
        assert seg.audio_duration == 4.8

    def test_from_dict_ignores_unknown_fields(self) -> None:
        """P3：from_dict 容忍未知字段，向前兼容未来版本。"""
        data = {
            "index": 2,
            "start_time": 1.5,
            "end_time": 3.0,
            "source_text": "hello",
            "translated_text": "你好",
            "audio_path": "/tmp/x.wav",
            "audio_duration": 1.5,
            "future_field_v2": "some new field",
            "another_unknown": 42,
        }
        seg = SubtitleSegment.from_dict(data)
        assert seg.index == 2
        assert seg.source_text == "hello"
        assert seg.translated_text == "你好"
        assert seg.audio_path == Path("/tmp/x.wav")

    def test_from_dict_uses_defaults_for_missing_optional_fields(self) -> None:
        """缺失的可选字段由 dataclass 默认值兜底。"""
        data = {"index": 0, "start_time": 0.0, "end_time": 1.0, "source_text": "x"}
        seg = SubtitleSegment.from_dict(data)
        assert seg.translated_text == ""
        assert seg.audio_path == Path()
        assert seg.audio_duration == 0.0

    def test_roundtrip_to_dict_from_dict(self) -> None:
        """to_dict → from_dict 往返保持数据一致。"""
        original = SubtitleSegment(
            index=3,
            start_time=5.0,
            end_time=8.5,
            source_text="original text",
            translated_text="译文",
            audio_path=Path("/tmp/a.wav"),
            audio_duration=3.2,
        )
        roundtrip = SubtitleSegment.from_dict(original.to_dict())
        assert roundtrip == original


class TestStageStatus:
    def test_enum_values(self) -> None:
        assert StageStatus.PENDING.value == "pending"
        assert StageStatus.RUNNING.value == "running"
        assert StageStatus.COMPLETED.value == "completed"
        assert StageStatus.FAILED.value == "failed"


class TestStageState:
    def test_default_values(self) -> None:
        state = StageState(name="ASR")
        assert state.name == "ASR"
        assert state.status == StageStatus.PENDING
        assert state.progress == 0.0
        assert state.start_time is None
        assert state.end_time is None
        assert state.error is None

    def test_duration_with_times(self) -> None:
        state = StageState(name="ASR", start_time=10.0, end_time=90.0)
        assert state.duration == 80.0

    def test_duration_without_end_time(self) -> None:
        state = StageState(name="ASR", start_time=10.0)
        assert state.duration is None

    def test_duration_without_start_time(self) -> None:
        state = StageState(name="ASR", end_time=90.0)
        assert state.duration is None

    def test_duration_no_times(self) -> None:
        state = StageState(name="ASR")
        assert state.duration is None


class TestProgressEvent:
    def test_create_with_required_fields(self) -> None:
        event = ProgressEvent(stage="ASR", progress=0.5)
        assert event.stage == "ASR"
        assert event.progress == 0.5
        assert event.message == ""

    def test_create_with_message(self) -> None:
        event = ProgressEvent(stage="TTS", progress=0.8, message="正在合成第 15/50 段")
        assert event.message == "正在合成第 15/50 段"


class TestPipelineResult:
    def test_success_result(self) -> None:
        result = PipelineResult(
            video_path=Path("/input/video.mp4"),
            output_dir=Path("/output"),
            audio_path=Path("/output/.temp/abc/audio.wav"),
        )
        assert result.success is True
        assert result.error is None
        assert result.audio_path == Path("/output/.temp/abc/audio.wav")

    def test_failure_result(self) -> None:
        result = PipelineResult(
            video_path=Path("/input/video.mp4"),
            output_dir=Path("/output"),
            success=False,
            error="ffmpeg 未找到",
        )
        assert result.success is False
        assert result.error == "ffmpeg 未找到"

    def test_default_values(self) -> None:
        result = PipelineResult(
            video_path=Path("/input/video.mp4"),
            output_dir=Path("/output"),
        )
        assert result.audio_path == Path()
        assert result.success is True
        assert result.error is None
