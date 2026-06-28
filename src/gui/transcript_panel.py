from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from src.gui.constants import (
    BUTTON_HEIGHT_SM,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY_TEXT,
    FONT_LABEL,
)

_COPY_BTN_ASR = "复制原文"
_COPY_BTN_TRANS = "复制译文"
_COPY_FEEDBACK = "已复制 ✓"
_FEEDBACK_MS = 1000


class TranscriptPanel(QWidget):
    _PLACEHOLDER = "翻译结果将在此处展示"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._asr_text = ""
        self._translation_text = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._copy_asr_btn = self._make_copy_btn(_COPY_BTN_ASR)
        self._copy_trans_btn = self._make_copy_btn(_COPY_BTN_TRANS)
        self._copy_asr_btn.clicked.connect(self._copy_asr)
        self._copy_trans_btn.clicked.connect(self._copy_translation)
        btn_layout.addWidget(self._copy_asr_btn)
        btn_layout.addWidget(self._copy_trans_btn)
        layout.addLayout(btn_layout)

        self._text_browser = QTextBrowser()
        self._text_browser.setReadOnly(True)
        self._text_browser.setMaximumHeight(200)
        self._show_placeholder()
        layout.addWidget(self._text_browser)

        self._update_copy_buttons()

    @staticmethod
    def _make_copy_btn(text: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("inlineButton")
        btn.setFixedHeight(BUTTON_HEIGHT_SM)
        btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return btn

    def _show_placeholder(self) -> None:
        self._text_browser.setStyleSheet(
            f"color: {COLOR_SECONDARY_TEXT}; font-size: {FONT_LABEL}pt; font-style: italic;"
        )
        self._text_browser.setPlainText(self._PLACEHOLDER)

    def _on_transcript_updated(self, text: str) -> None:
        if any(line.startswith("[中] ") for line in text.split("\n")):
            self._translation_text = text
        else:
            self._asr_text = text

        self._text_browser.setStyleSheet(f"color: {COLOR_PRIMARY_TEXT}; font-size: {FONT_LABEL}pt;")
        self._text_browser.setPlainText(text)
        sb = self._text_browser.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._update_copy_buttons()

    def _update_copy_buttons(self) -> None:
        self._copy_asr_btn.setEnabled(bool(self._asr_text))
        self._copy_trans_btn.setEnabled(bool(self._translation_text))

    def reset(self) -> None:
        """重置面板，恢复占位符文本和斜体样式。"""
        self._asr_text = ""
        self._translation_text = ""
        self._show_placeholder()
        self._update_copy_buttons()

    def _copy_asr(self) -> None:
        if self._asr_text:
            QApplication.clipboard().setText(self._asr_text)
            self._show_copied_feedback(self._copy_asr_btn)

    def _copy_translation(self) -> None:
        if self._translation_text:
            chinese = self._extract_chinese(self._translation_text)
            QApplication.clipboard().setText(chinese)
            self._show_copied_feedback(self._copy_trans_btn)

    @staticmethod
    def _extract_chinese(bilingual_text: str) -> str:
        return "\n".join(
            line[4:] for line in bilingual_text.split("\n") if line.startswith("[中] ")
        )

    def _show_copied_feedback(self, button: QPushButton) -> None:
        original = button.text()
        button.setText(_COPY_FEEDBACK)
        button.setEnabled(False)
        QTimer.singleShot(_FEEDBACK_MS, lambda: self._restore_button(button, original))

    def _restore_button(self, button: QPushButton, original_text: str) -> None:
        if not isValid(self) or not isValid(button):
            return
        button.setText(original_text)
        self._update_copy_buttons()
