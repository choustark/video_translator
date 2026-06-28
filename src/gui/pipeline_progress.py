from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from src.gui.constants import (
    COLOR_ACCENT,
    COLOR_ERROR,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY_TEXT,
    COLOR_SUCCESS,
    COLOR_WARNING,
    FONT_LABEL,
    SPACING_SM,
)
from src.pipeline import STAGE_NAMES


class PipelineProgress(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: dict[str, _StageRow] = {}
        self._stage_start_times: dict[str, float] = {}
        self._stage_durations: dict[str, float] = {}
        self._has_failure = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SM)

        for name in STAGE_NAMES:
            row = _StageRow(name)
            self._rows[name] = row
            layout.addWidget(row)

        self._summary_label = QLabel("")
        self._summary_label.setObjectName("stageSummary")
        self._summary_label.hide()
        layout.addWidget(self._summary_label)

    def reset(self) -> None:
        """重置所有阶段行状态为 pending，清空计时数据、警告标签和失败标记。"""
        for row in self._rows.values():
            row.set_status("pending")
            row._warning_label.setText("")
            row._warning_label.hide()
        self._stage_start_times.clear()
        self._stage_durations.clear()
        self._has_failure = False
        self._summary_label.setText("")
        self._summary_label.hide()

    def _on_stage_started(self, stage_name: str) -> None:
        row = self._rows.get(stage_name)
        if row is None:
            return
        row.set_status("running")
        self._stage_start_times[stage_name] = time.monotonic()
        self._summary_label.hide()

    def _on_stage_progress(self, stage_name: str, progress: float) -> None:
        row = self._rows.get(stage_name)
        if row is None:
            return
        pct = max(0, min(100, int(progress * 100)))
        row.update_progress(pct)

        start = self._stage_start_times.get(stage_name)
        if start is not None and progress > 0:
            elapsed = time.monotonic() - start
            eta = elapsed * (1 - progress) / progress
            row.update_time(f"已用 {elapsed:.0f}s / 预计剩余 {eta:.0f}s")
        else:
            row.update_time("--")

    def _on_stage_completed(self, stage_name: str, duration: float) -> None:
        row = self._rows.get(stage_name)
        if row is None:
            return
        row.set_status("completed")
        row.update_progress(-1)
        row.update_time(f"耗时 {duration:.0f}s")
        self._stage_durations[stage_name] = duration

    def _on_stage_failed(self, stage_name: str, error: str) -> None:
        row = self._rows.get(stage_name)
        if row is None:
            return
        row.set_status("failed")
        row.update_time(error[:50])
        self._has_failure = True

    def _on_pipeline_finished(self) -> None:
        if getattr(self, "_has_failure", False):
            self._summary_label.setText("管线执行失败")
            self._summary_label.setStyleSheet(
                f"color: {COLOR_ERROR}; font-size: 11pt; font-weight: bold; padding: 4px 0;"
            )
        else:
            total = sum(self._stage_durations.values())
            self._summary_label.setText(f"全部完成，总耗时 {total:.0f}s")
            self._summary_label.setStyleSheet("")
        self._summary_label.show()

    def _on_tts_degraded(self, original: str, fallback: str) -> None:
        row = self._rows.get("TTS")
        if row is None:
            return
        row.show_warning(f"已降级为 {fallback}")


_STATUS_CONFIG: dict[str, dict[str, str]] = {
    "pending": {"icon": "●", "icon_color": COLOR_SECONDARY_TEXT, "bg": ""},
    "running": {"icon": "●", "icon_color": COLOR_ACCENT, "bg": "#F0F7FF"},
    "completed": {"icon": "✓", "icon_color": COLOR_SUCCESS, "bg": ""},
    "failed": {"icon": "✗", "icon_color": COLOR_ERROR, "bg": ""},
}


class _StageRow(QWidget):
    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._stage_name = name

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(SPACING_SM)

        self._icon_label = QLabel("●")
        self._icon_label.setObjectName("stageIcon")
        self._icon_label.setFixedWidth(16)
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._icon_label)

        self._name_label = QLabel(name)
        self._name_label.setObjectName("stageName")
        self._name_label.setStyleSheet(f"color: {COLOR_PRIMARY_TEXT}; font-size: {FONT_LABEL}pt;")
        layout.addWidget(self._name_label)

        layout.addStretch()

        self._warning_label = QLabel("")
        self._warning_label.setObjectName("stageWarning")
        self._warning_label.setStyleSheet(f"color: {COLOR_WARNING}; font-size: {FONT_LABEL - 1}pt;")
        self._warning_label.hide()
        layout.addWidget(self._warning_label)

        self._progress_label = QLabel("")
        self._progress_label.setObjectName("stageProgress")
        self._progress_label.setStyleSheet(f"color: {COLOR_ACCENT}; font-size: {FONT_LABEL - 1}pt;")
        layout.addWidget(self._progress_label)

        self._time_label = QLabel("")
        self._time_label.setObjectName("stageTime")
        self._time_label.setStyleSheet(
            f"color: {COLOR_SECONDARY_TEXT}; font-size: {FONT_LABEL - 1}pt;"
        )
        self._time_label.setFixedWidth(180)
        layout.addWidget(self._time_label)

        self.set_status("pending")

    def set_status(self, status: str) -> None:
        """根据状态更新图标、背景色和字体粗细，非运行状态清除进度文本。"""
        cfg = _STATUS_CONFIG.get(status, _STATUS_CONFIG["pending"])
        self._icon_label.setText(cfg["icon"])
        self._icon_label.setStyleSheet(
            f"color: {cfg['icon_color']}; font-size: {FONT_LABEL}pt; font-weight: bold;"
        )
        object_name = f"stageRow_{self._stage_name}"
        self.setObjectName(object_name)
        if cfg["bg"]:
            self.setStyleSheet(f"#{object_name} {{ background: {cfg['bg']}; border-radius: 4px; }}")
        else:
            self.setStyleSheet("")
        bold = "font-weight: bold;" if status == "running" else "font-weight: normal;"
        self._name_label.setStyleSheet(
            f"color: {COLOR_PRIMARY_TEXT}; font-size: {FONT_LABEL}pt; {bold}"
        )
        if status != "running":
            self._progress_label.setText("")
            if status != "completed":
                self._time_label.setText("")

    def update_progress(self, pct: int) -> None:
        """更新进度百分比文本，负值时清除。"""
        if pct < 0:
            self._progress_label.setText("")
        else:
            self._progress_label.setText(f"{pct}%")

    def update_time(self, text: str) -> None:
        """更新右侧时间/耗时标签文本。"""
        self._time_label.setText(text)

    def show_warning(self, text: str) -> None:
        """显示警告标签（如 TTS 降级提示）。"""
        self._warning_label.setText(text)
        self._warning_label.show()
