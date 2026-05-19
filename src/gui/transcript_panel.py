from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser, QWidget

from src.gui.constants import COLOR_PRIMARY_TEXT, COLOR_SECONDARY_TEXT, FONT_LABEL


class TranscriptPanel(QTextBrowser):
    _PLACEHOLDER = "翻译结果将在此处展示"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumHeight(200)
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        self.setStyleSheet(
            f"color: {COLOR_SECONDARY_TEXT}; font-size: {FONT_LABEL}pt; font-style: italic;"
        )
        self.setPlainText(self._PLACEHOLDER)

    def _on_transcript_updated(self, text: str) -> None:
        self.setStyleSheet(
            f"color: {COLOR_PRIMARY_TEXT}; font-size: {FONT_LABEL}pt;"
        )
        self.setPlainText(text)
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def reset(self) -> None:
        """重置面板，恢复占位符文本和斜体样式。"""
        self._show_placeholder()
