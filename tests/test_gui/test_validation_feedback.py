from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QLabel

from src.exceptions import ValidationError
from src.gui.config_panel import ConfigPanel
from src.gui.main_window import MainWindow
from src.validators import ValidationResult


@pytest.fixture
def config_panel(qapp, config_path: Path) -> ConfigPanel:
    return ConfigPanel(config_path)


@pytest.fixture
def main_window(qapp, config_path: Path) -> MainWindow:
    return MainWindow(config_path)


# ---------------------------------------------------------------------------
# Task 1: 校验图标基础设施
# ---------------------------------------------------------------------------


class TestStatusIcons:
    """校验图标创建与状态设置 (AC: #1, #2)。"""

    def test_three_icons_exist(self, config_panel: ConfigPanel) -> None:
        assert isinstance(config_panel._asr_status_icon, QLabel)
        assert isinstance(config_panel._translation_status_icon, QLabel)
        assert isinstance(config_panel._tts_status_icon, QLabel)

    def test_icons_have_fixed_size(self, config_panel: ConfigPanel) -> None:
        for icon in (
            config_panel._asr_status_icon,
            config_panel._translation_status_icon,
            config_panel._tts_status_icon,
        ):
            assert icon.width() == 16
            assert icon.height() == 16

    def test_set_icon_state_passed(self, config_panel: ConfigPanel) -> None:
        config_panel._set_icon_state(config_panel._asr_status_icon, passed=True, tooltip="")
        pixmap = config_panel._asr_status_icon.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()
        assert config_panel._asr_status_icon.toolTip() == ""

    def test_set_icon_state_failed(self, config_panel: ConfigPanel) -> None:
        config_panel._set_icon_state(
            config_panel._asr_status_icon,
            passed=False,
            tooltip="模型未配置",
        )
        pixmap = config_panel._asr_status_icon.pixmap()
        assert pixmap is not None
        assert not pixmap.isNull()
        assert "模型未配置" in config_panel._asr_status_icon.toolTip()


# ---------------------------------------------------------------------------
# Task 2: 校验状态汇总标签
# ---------------------------------------------------------------------------


class TestValidationSummary:
    """汇总标签更新逻辑 (AC: #4)。"""

    def test_summary_label_exists(self, config_panel: ConfigPanel) -> None:
        assert isinstance(config_panel._validation_summary_label, QLabel)
        assert config_panel._validation_summary_label.objectName() == "validationSummary"

    def test_summary_shows_all_ready_when_no_errors(self, config_panel: ConfigPanel) -> None:
        config_panel._update_validation_summary([])
        assert not config_panel._validation_summary_label.isHidden()
        assert "全部就绪" in config_panel._validation_summary_label.text()

    def test_summary_shows_count_when_errors(self, config_panel: ConfigPanel) -> None:
        err1 = ValidationError("err1", stage="asr")
        err2 = ValidationError("err2", stage="tts")
        config_panel._update_validation_summary([err1, err2])
        assert "2 项未通过" in config_panel._validation_summary_label.text()


# ---------------------------------------------------------------------------
# Task 3 & 4: 校验调度 + validation_changed 信号
# ---------------------------------------------------------------------------


class TestValidationScheduling:
    """防抖调度 + do_validation 逻辑 (AC: #3, #5)。"""

    def test_schedule_validation_starts_timer(self, config_panel: ConfigPanel) -> None:
        config_panel._schedule_validation()
        assert config_panel._validation_timer.isActive() is True

    def test_validation_timer_is_single_shot(self, config_panel: ConfigPanel) -> None:
        assert config_panel._validation_timer.isSingleShot() is True

    def test_validation_timer_interval_300ms(self, config_panel: ConfigPanel) -> None:
        assert config_panel._validation_timer.interval() == 300

    def test_do_validation_with_passing_result(
        self, config_panel: ConfigPanel, tmp_path: Path
    ) -> None:
        results: list[bool] = []
        config_panel.validation_changed.connect(lambda v: results.append(v))
        video = tmp_path / "test.mp4"
        video.touch()
        config_panel._video_path = video
        with patch(
            "src.gui.config_panel.validate_all",
            return_value=ValidationResult([]),
        ):
            config_panel._do_validation()
        assert results == [True]

    def test_do_validation_with_failing_result(
        self, config_panel: ConfigPanel, tmp_path: Path
    ) -> None:
        results: list[bool] = []
        config_panel.validation_changed.connect(lambda v: results.append(v))
        video = tmp_path / "test.mp4"
        video.touch()
        config_panel._video_path = video
        err = ValidationError("test failure", stage="asr")
        with patch(
            "src.gui.config_panel.validate_all",
            return_value=ValidationResult([err]),
        ):
            config_panel._do_validation()
        assert results == [False]

    def test_do_validation_updates_icons_on_failure(
        self, config_panel: ConfigPanel, tmp_path: Path
    ) -> None:
        video = tmp_path / "test.mp4"
        video.touch()
        config_panel._video_path = video
        err = ValidationError("ASR 模型不存在", stage="asr")
        with patch(
            "src.gui.config_panel.validate_all",
            return_value=ValidationResult([err]),
        ):
            config_panel._do_validation()
        asr_pixmap = config_panel._asr_status_icon.pixmap()
        assert asr_pixmap is not None
        assert "ASR 模型不存在" in config_panel._asr_status_icon.toolTip()

    def test_do_validation_bails_when_config_none(self, config_panel: ConfigPanel) -> None:
        results: list[bool] = []
        config_panel.validation_changed.connect(lambda v: results.append(v))
        with patch.object(config_panel, "_collect_config", return_value=None):
            config_panel._do_validation()
            assert results == []

    def test_do_validation_no_video_passing(self, config_panel: ConfigPanel) -> None:
        """无视频时调用 validate_config_only 并正确处理通过结果。"""
        results: list[bool] = []
        config_panel.validation_changed.connect(lambda v: results.append(v))
        config_panel._video_path = None
        with patch(
            "src.gui.config_panel.validate_config_only",
            return_value=ValidationResult([]),
        ):
            config_panel._do_validation()
        assert results == [True]

    def test_do_validation_no_video_failing(self, config_panel: ConfigPanel) -> None:
        """无视频时调用 validate_config_only 并正确处理失败结果。"""
        results: list[bool] = []
        config_panel.validation_changed.connect(lambda v: results.append(v))
        config_panel._video_path = None
        err = ValidationError("ffmpeg 未安装", stage="ffmpeg")
        with patch(
            "src.gui.config_panel.validate_config_only",
            return_value=ValidationResult([err]),
        ):
            config_panel._do_validation()
        assert results == [False]

    def test_do_validation_no_video_updates_summary(self, config_panel: ConfigPanel) -> None:
        """无视频校验失败时汇总标签正确更新。"""
        config_panel._video_path = None
        err = ValidationError("内存不足", stage="memory")
        with patch(
            "src.gui.config_panel.validate_config_only",
            return_value=ValidationResult([err]),
        ):
            config_panel._do_validation()
        assert "1 项未通过" in config_panel._validation_summary_label.text()

    def test_set_video_path_triggers_validation(self, config_panel: ConfigPanel) -> None:
        with patch.object(config_panel, "_schedule_validation") as mock_schedule:
            config_panel.set_video_path(Path("/test/video.mp4"))
            mock_schedule.assert_called_once()
            assert config_panel._video_path == Path("/test/video.mp4")


# ---------------------------------------------------------------------------
# Task 5: 翻译按钮联动
# ---------------------------------------------------------------------------


class TestButtonLinkage:
    """翻译按钮联动逻辑 (AC: #5)。"""

    def test_button_disabled_when_validation_fails(self, main_window: MainWindow) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._validation_passed = False
        main_window._on_validation_changed(False)
        assert main_window._translate_btn.isEnabled() is False

    def test_button_enabled_when_validation_passes_with_video(
        self, main_window: MainWindow
    ) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._on_validation_changed(True)
        assert main_window._translate_btn.isEnabled() is True

    def test_button_disabled_when_no_video_even_if_valid(self, main_window: MainWindow) -> None:
        main_window._video_drop_area._video_path = None
        main_window._on_validation_changed(True)
        assert main_window._translate_btn.isEnabled() is False

    def test_button_disabled_during_translation(self, main_window: MainWindow) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._translating = True
        main_window._on_validation_changed(True)
        assert main_window._translate_btn.isEnabled() is False


# ---------------------------------------------------------------------------
# Task 6: 校验失败弹窗
# ---------------------------------------------------------------------------


class TestValidationFailureDialog:
    """校验失败弹窗 (AC: #6, #7)。"""

    def test_dialog_shows_error_count(self, main_window: MainWindow) -> None:
        errors = [
            ValidationError("error one", stage="asr", suggestion="fix one"),
            ValidationError("error two", stage="tts", suggestion="fix two"),
        ]
        with patch("src.gui.main_window.QMessageBox.warning") as mock_warn:
            main_window._show_validation_failure_dialog(errors)
            mock_warn.assert_called_once()
            args = mock_warn.call_args[0]
            assert "2 项" in args[2]

    def test_dialog_includes_stage_info(self, main_window: MainWindow) -> None:
        errors = [ValidationError("bad key", stage="translation", suggestion="check")]
        with patch("src.gui.main_window.QMessageBox.warning") as mock_warn:
            main_window._show_validation_failure_dialog(errors)
            detail = mock_warn.call_args[0][2]
            assert "[translation]" in detail
            assert "bad key" in detail
            assert "check" in detail

    def test_translate_clicked_shows_dialog_on_validation_failure(
        self, main_window: MainWindow
    ) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._translate_btn.setEnabled(True)
        err = ValidationError("fail", stage="memory", suggestion="close apps")
        with (
            patch("src.gui.main_window.validate_all", return_value=ValidationResult([err])),
            patch("src.gui.main_window.QMessageBox.warning") as mock_warn,
        ):
            main_window._translate_btn.click()
            mock_warn.assert_called_once()
        assert main_window._translate_btn.text() == "开始翻译"

    def test_translate_clicked_skips_when_no_video(self, main_window: MainWindow) -> None:
        main_window._video_drop_area._video_path = None
        main_window._translate_btn.setEnabled(True)
        with patch("src.gui.main_window.validate_all") as mock_validate:
            main_window._translate_btn.click()
            mock_validate.assert_not_called()


# ---------------------------------------------------------------------------
# Task 3: 防抖
# ---------------------------------------------------------------------------


class TestDebounce:
    """防抖：快速多次变化只触发一次校验 (AC: #3)。"""

    def test_rapid_changes_only_trigger_once(self, config_panel: ConfigPanel) -> None:
        with patch.object(config_panel, "_do_validation") as mock_do:
            # 快速连续触发多次
            config_panel._schedule_validation()
            config_panel._schedule_validation()
            config_panel._schedule_validation()
            # 手动触发 timeout
            config_panel._validation_timer.timeout.emit()
            mock_do.assert_called_once()

    def test_on_config_changed_triggers_validation(self, config_panel: ConfigPanel) -> None:
        with patch.object(config_panel, "_schedule_validation") as mock_schedule:
            config_panel._on_config_changed()
            mock_schedule.assert_called_once()


# ---------------------------------------------------------------------------
# Task 6: build_tooltip
# ---------------------------------------------------------------------------


class TestBuildTooltip:
    """tooltip 文本构建。"""

    def test_empty_tooltip_when_no_errors(self, config_panel: ConfigPanel) -> None:
        assert config_panel._build_tooltip([]) == ""

    def test_tooltip_includes_message_and_suggestion(self, config_panel: ConfigPanel) -> None:
        errors = [
            ValidationError("未配置", stage="asr", suggestion="请配置"),
        ]
        tip = config_panel._build_tooltip(errors)
        assert "未配置" in tip
        assert "请配置" in tip

    def test_multiple_errors_separated(self, config_panel: ConfigPanel) -> None:
        errors = [
            ValidationError("err1", stage="a", suggestion="fix1"),
            ValidationError("err2", stage="b", suggestion="fix2"),
        ]
        tip = config_panel._build_tooltip(errors)
        assert "\n\n" in tip
