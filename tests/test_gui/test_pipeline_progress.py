from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.gui.pipeline_progress import PipelineProgress, _StageRow


class TestPipelineProgressCreation:
    def test_creates_six_rows(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        assert len(widget._rows) == 6

    def test_all_rows_pending(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        from src.pipeline import STAGE_NAMES

        for name in STAGE_NAMES:
            row = widget._rows[name]
            assert isinstance(row, _StageRow)
            assert row._icon_label.text() == "●"

    def test_summary_hidden_initially(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        assert widget._summary_label.isHidden()


class TestPipelineProgressStageStarted:
    def test_running_highlight(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        row = widget._rows["ASR"]
        assert row._icon_label.text() == "●"
        assert "bold" in row._name_label.styleSheet()
        assert row.styleSheet() != ""

    def test_records_start_time(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("翻译")
        assert "翻译" in widget._stage_start_times


class TestPipelineProgressProgress:
    def test_shows_percentage(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("TTS")
        widget._on_stage_progress("TTS", 0.45)
        row = widget._rows["TTS"]
        assert row._progress_label.text() == "45%"

    def test_shows_time_estimate(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        widget._on_stage_progress("ASR", 0.5)
        row = widget._rows["ASR"]
        assert "已用" in row._time_label.text()
        assert "预计剩余" in row._time_label.text()

    def test_zero_progress_shows_dash(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("翻译")
        widget._on_stage_progress("翻译", 0.0)
        row = widget._rows["翻译"]
        assert "--" in row._time_label.text()


class TestPipelineProgressCompleted:
    def test_green_checkmark(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_completed("音频提取", 3.0)
        row = widget._rows["音频提取"]
        assert row._icon_label.text() == "✓"

    def test_shows_duration(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_completed("ASR", 80.5)
        row = widget._rows["ASR"]
        assert "80" in row._time_label.text()
        assert "耗时" in row._time_label.text()

    def test_clears_progress(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("TTS")
        widget._on_stage_progress("TTS", 0.5)
        widget._on_stage_completed("TTS", 120.0)
        row = widget._rows["TTS"]
        assert row._progress_label.text() == ""


class TestPipelineProgressFailed:
    def test_red_cross(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("TTS")
        widget._on_stage_failed("TTS", "OOM")
        row = widget._rows["TTS"]
        assert row._icon_label.text() == "✗"

    def test_removes_highlight(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("翻译")
        assert widget._rows["翻译"].styleSheet() != ""
        widget._on_stage_failed("翻译", "API timeout")
        assert widget._rows["翻译"].styleSheet() == ""

    def test_shows_error_in_time_label(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("TTS")
        widget._on_stage_failed("TTS", "CosyVoice 内存不足")
        row = widget._rows["TTS"]
        assert "内存不足" in row._time_label.text()

    def test_clears_running_time_on_fail(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        widget._on_stage_progress("ASR", 0.5)
        widget._on_stage_failed("ASR", "crash")
        row = widget._rows["ASR"]
        assert row._time_label.text() == "crash"


class TestPipelineProgressFinished:
    def test_shows_total_duration(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_completed("音频提取", 3.0)
        widget._on_stage_completed("ASR", 80.0)
        widget._on_stage_completed("翻译", 10.0)
        widget._on_pipeline_finished()
        assert "93" in widget._summary_label.text()
        assert not widget._summary_label.isHidden()

    def test_no_durations_shows_zero(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_pipeline_finished()
        assert "0" in widget._summary_label.text()

    def test_failure_shows_failed_summary(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("TTS")
        widget._on_stage_failed("TTS", "OOM")
        widget._on_pipeline_finished()
        assert "失败" in widget._summary_label.text()
        assert "FF3B30" in widget._summary_label.styleSheet()


class TestPipelineProgressTtsDegraded:
    def test_shows_warning(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_tts_degraded("cosyvoice", "edge-tts")
        row = widget._rows["TTS"]
        assert not row._warning_label.isHidden()
        assert "edge-tts" in row._warning_label.text()


class TestPipelineProgressReset:
    def test_resets_all_rows(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        widget._on_stage_completed("ASR", 80.0)
        widget._on_pipeline_finished()
        widget.reset()
        for name, row in widget._rows.items():
            assert row._icon_label.text() == "●"
        assert widget._summary_label.isHidden()
        assert len(widget._stage_durations) == 0

    def test_resets_warning_label(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_tts_degraded("cosyvoice", "edge-tts")
        assert not widget._rows["TTS"]._warning_label.isHidden()
        widget.reset()
        assert widget._rows["TTS"]._warning_label.isHidden()
        assert widget._rows["TTS"]._warning_label.text() == ""

    def test_resets_failure_flag(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_failed("ASR", "crash")
        assert widget._has_failure is True
        widget.reset()
        assert widget._has_failure is False


class TestPipelineProgressEdgeCases:
    def test_progress_clamped_over_100(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        widget._on_stage_progress("ASR", 1.5)
        row = widget._rows["ASR"]
        assert row._progress_label.text() == "100%"

    def test_progress_clamped_negative(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        widget._on_stage_progress("ASR", -0.1)
        row = widget._rows["ASR"]
        assert row._progress_label.text() == "0%"

    def test_progress_without_start_shows_dash(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_progress("翻译", 0.3)
        row = widget._rows["翻译"]
        assert row._time_label.text() == "--"

    def test_running_bg_uses_objectname_selector(self, qapp: QApplication) -> None:
        widget = PipelineProgress()
        widget._on_stage_started("ASR")
        row = widget._rows["ASR"]
        ss = row.styleSheet()
        assert "#" in ss
        assert row.objectName() in ss
