from PySide6.QtCore import QObject, Signal


class PipelineSignals(QObject):
    stage_started = Signal(str)
    stage_progress = Signal(str, float)
    stage_completed = Signal(str, float)
    stage_failed = Signal(str, str)
    transcript_updated = Signal(str)
    pipeline_finished = Signal()
    tts_degraded = Signal(str, str)
