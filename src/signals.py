"""管线 → UI 单向信号总线。

所有信号由 Pipeline 后台线程 emit，UI 主线程通过 Qt QueuedConnection 接收。
完整契约见 docs/pipeline-signals-contract.md。
"""

from PySide6.QtCore import QObject, Signal


class PipelineSignals(QObject):
    stage_started = Signal(str)
    """阶段开始执行。参数：stage_name（STAGE_NAMES 之一）。同一阶段内只 emit 一次。"""

    stage_progress = Signal(str, float)
    """阶段进度更新。参数：stage_name, progress ∈ [0.0, 1.0]。同阶段内单调不减。"""

    stage_completed = Signal(str, float)
    """阶段成功完成。参数：stage_name, duration（秒）。"""

    stage_failed = Signal(str, str)
    """阶段失败。参数：stage_name, error_message。必须先于 pipeline_finished emit。"""

    transcript_updated = Signal(str)
    """字幕文本更新。参数：text。在 ASR 与翻译阶段各 emit 一次。"""

    pipeline_finished = Signal()
    """管线终止（成功或失败）。永远是该批次最后一个信号。"""

    tts_degraded = Signal(str, str)
    """TTS 引擎降级。参数：original_engine, fallback_engine。"""
