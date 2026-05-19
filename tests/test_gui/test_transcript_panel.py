from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.gui.transcript_panel import TranscriptPanel


class TestTranscriptPanelCreation:
    def test_shows_placeholder(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert panel.toPlainText() == "翻译结果将在此处展示"

    def test_is_readonly(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert panel.isReadOnly()


class TestTranscriptPanelUpdate:
    def test_updates_text(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello world")
        assert panel.toPlainText() == "Hello world"

    def test_replaces_previous_text(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("English text")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好")
        assert "[EN] Hello" in panel.toPlainText()
        assert "English text" not in panel.toPlainText()

    def test_removes_italic_on_update(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert "italic" in panel.styleSheet()
        panel._on_transcript_updated("Some text")
        assert "italic" not in panel.styleSheet()


class TestTranscriptPanelReset:
    def test_restores_placeholder(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Some text")
        panel.reset()
        assert panel.toPlainText() == "翻译结果将在此处展示"

    def test_restores_italic(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Some text")
        panel.reset()
        assert "italic" in panel.styleSheet()
