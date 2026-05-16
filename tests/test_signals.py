from PySide6.QtCore import QObject

from src.signals import PipelineSignals


def test_pipeline_signals_is_qobject():
    signals = PipelineSignals()
    assert isinstance(signals, QObject)


def test_pipeline_signals_has_seven_signals():
    signals = PipelineSignals()
    signal_names = [
        "stage_started",
        "stage_progress",
        "stage_completed",
        "stage_failed",
        "transcript_updated",
        "pipeline_finished",
        "tts_degraded",
    ]
    for name in signal_names:
        assert hasattr(signals, name), f"Missing signal: {name}"


def test_stage_started_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.stage_started.connect(lambda s: received.append(s))
    signals.stage_started.emit("ASR")
    assert received == ["ASR"]


def test_stage_progress_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.stage_progress.connect(lambda s, p: received.append((s, p)))
    signals.stage_progress.emit("ASR", 0.5)
    assert received == [("ASR", 0.5)]


def test_stage_completed_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.stage_completed.connect(lambda s, t: received.append((s, t)))
    signals.stage_completed.emit("TTS", 120.0)
    assert received == [("TTS", 120.0)]


def test_stage_failed_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.stage_failed.connect(lambda s, e: received.append((s, e)))
    signals.stage_failed.emit("ASR", "OOM")
    assert received == [("ASR", "OOM")]


def test_transcript_updated_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.transcript_updated.connect(lambda t: received.append(t))
    signals.transcript_updated.emit("Hello world")
    assert received == ["Hello world"]


def test_pipeline_finished_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.pipeline_finished.connect(lambda: received.append(True))
    signals.pipeline_finished.emit()
    assert received == [True]


def test_tts_degraded_signal_emits():
    signals = PipelineSignals()
    received = []
    signals.tts_degraded.connect(lambda o, n: received.append((o, n)))
    signals.tts_degraded.emit("CosyVoice", "Edge-TTS")
    assert received == [("CosyVoice", "Edge-TTS")]
