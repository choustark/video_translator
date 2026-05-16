from pathlib import Path

from src.models import ProgressEvent, StageState, StageStatus, SubtitleSegment


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
