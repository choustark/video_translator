from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.gui.transcript_panel import TranscriptPanel


def _tb(panel: TranscriptPanel):
    """Shortcut to access the internal text browser."""
    return panel._text_browser


class TestTranscriptPanelCreation:
    def test_shows_placeholder(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert _tb(panel).toPlainText() == "翻译结果将在此处展示"

    def test_is_readonly(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert _tb(panel).isReadOnly()


class TestTranscriptPanelUpdate:
    def test_updates_text(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello world")
        assert _tb(panel).toPlainText() == "Hello world"

    def test_replaces_previous_text(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("English text")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好")
        assert "[EN] Hello" in _tb(panel).toPlainText()
        assert "English text" not in _tb(panel).toPlainText()

    def test_removes_italic_on_update(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert "italic" in _tb(panel).styleSheet()
        panel._on_transcript_updated("Some text")
        assert "italic" not in _tb(panel).styleSheet()


class TestTranscriptPanelReset:
    def test_restores_placeholder(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Some text")
        panel.reset()
        assert _tb(panel).toPlainText() == "翻译结果将在此处展示"

    def test_restores_italic(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Some text")
        panel.reset()
        assert "italic" in _tb(panel).styleSheet()


class TestTranscriptPanelCache:
    def test_asr_text_cached(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello world from ASR")
        assert panel._asr_text == "Hello world from ASR"
        assert panel._translation_text == ""

    def test_translation_text_cached(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好")
        assert panel._asr_text == "Hello"
        assert panel._translation_text == "[EN] Hello\n[中] 你好"

    def test_reset_clears_cache(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好")
        panel.reset()
        assert panel._asr_text == ""
        assert panel._translation_text == ""


class TestTranscriptPanelCopyButtons:
    def test_copy_asr_button_disabled_initially(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert not panel._copy_asr_btn.isEnabled()

    def test_copy_trans_button_disabled_initially(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        assert not panel._copy_trans_btn.isEnabled()

    def test_copy_asr_enabled_after_asr(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("ASR text")
        assert panel._copy_asr_btn.isEnabled()
        assert not panel._copy_trans_btn.isEnabled()

    def test_copy_trans_enabled_after_translation(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("ASR text")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好")
        assert panel._copy_asr_btn.isEnabled()
        assert panel._copy_trans_btn.isEnabled()

    def test_reset_disables_buttons(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("ASR text")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好")
        panel.reset()
        assert not panel._copy_asr_btn.isEnabled()
        assert not panel._copy_trans_btn.isEnabled()


class TestTranscriptPanelCopy:
    def test_copy_asr_to_clipboard(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello ASR world")
        panel._copy_asr()
        assert QApplication.clipboard().text() == "Hello ASR world"

    def test_copy_translation_to_clipboard(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello")
        panel._on_transcript_updated("[EN] Hello\n[中] 你好\n[EN] World\n[中] 世界")
        panel._copy_translation()
        assert QApplication.clipboard().text() == "你好\n世界"

    def test_copy_asr_empty_does_nothing(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        QApplication.clipboard().setText("unchanged")
        panel._copy_asr()
        assert QApplication.clipboard().text() == "unchanged"

    def test_copy_translation_empty_does_nothing(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        QApplication.clipboard().setText("unchanged")
        panel._copy_translation()
        assert QApplication.clipboard().text() == "unchanged"


class TestTranscriptPanelFeedback:
    def test_copy_shows_feedback_text(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello")
        panel._copy_asr()
        assert panel._copy_asr_btn.text() == "已复制 ✓"

    def test_copy_disables_button_during_feedback(self, qapp: QApplication) -> None:
        panel = TranscriptPanel()
        panel._on_transcript_updated("Hello")
        panel._copy_asr()
        assert not panel._copy_asr_btn.isEnabled()
