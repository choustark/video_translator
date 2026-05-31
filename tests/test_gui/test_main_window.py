from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import QApplication, QScrollArea, QSplitter

from src.gui.config_panel import ConfigPanel
from src.gui.main_window import MainWindow


@pytest.fixture
def main_window(qapp, config_path: Path) -> MainWindow:
    return MainWindow(config_path)


class TestMainWindowCreation:
    def test_create_success(self, qapp, config_path: Path) -> None:
        window = MainWindow(config_path)
        assert window is not None
        assert window.windowTitle() == "video_translator"

    def test_minimum_size(self, main_window: MainWindow) -> None:
        assert main_window.minimumWidth() == 720
        assert main_window.minimumHeight() == 520

    def test_central_widget_is_splitter(self, main_window: MainWindow) -> None:
        central = main_window.centralWidget()
        assert isinstance(central, QSplitter)
        assert central.orientation() == Qt.Orientation.Horizontal


class TestMainWindowSplitterLayout:
    def test_splitter_has_two_children(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        assert splitter.count() == 2

    def test_left_panel_is_scroll_area(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        left = splitter.widget(0)
        assert isinstance(left, QScrollArea)

    def test_left_panel_contains_config_panel(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        scroll_area = splitter.widget(0)
        assert isinstance(scroll_area.widget(), ConfigPanel)

    def test_left_panel_min_width(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        scroll_area = splitter.widget(0)
        assert scroll_area.minimumWidth() == 220

    def test_right_panel_is_widget(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        from PySide6.QtWidgets import QWidget

        right = splitter.widget(1)
        assert isinstance(right, QWidget)

    def test_children_collapsible_false(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        assert splitter.childrenCollapsible() is False

    def test_splitter_initial_sizes(self, main_window: MainWindow) -> None:
        splitter = main_window.centralWidget()
        sizes = splitter.sizes()
        assert sizes[0] >= 200
        assert sizes[1] > 0


class TestMainWindowQSS:
    def test_qss_loaded(self, qapp, config_path: Path) -> None:
        _window = MainWindow(config_path)
        stylesheet = QApplication.instance().styleSheet()
        assert len(stylesheet) > 0

    def test_qss_contains_key_selectors(self, qapp, config_path: Path) -> None:
        _window = MainWindow(config_path)
        stylesheet = QApplication.instance().styleSheet()
        assert "QMainWindow" in stylesheet
        assert "QPushButton" in stylesheet
        assert "QComboBox" in stylesheet


class TestMainWindowQSettings:
    @staticmethod
    def _isolated_settings() -> QSettings:
        """创建测试专用 QSettings，避免污染用户真实的窗口几何设置。

        使用独立的组织名/应用名，确保读写与用户本机 QSettings 完全隔离。
        """
        settings = QSettings("video_translator_test", "MainWindowTest")
        settings.clear()  # 确保每次测试从干净状态开始
        return settings

    def test_save_geometry_writes_settings(self, qapp, config_path: Path) -> None:
        window = MainWindow(config_path)
        window._settings = self._isolated_settings()
        window.resize(900, 700)
        window._save_geometry()

        geometry = window._settings.value("geometry")
        assert geometry is not None

    def test_restore_geometry_after_save(self, qapp, config_path: Path) -> None:
        window = MainWindow(config_path)
        iso_settings = self._isolated_settings()
        window._settings = iso_settings
        window.resize(900, 700)
        window._save_geometry()

        window2 = MainWindow(config_path)
        window2._settings = iso_settings  # 复用同一个隔离实例，模拟 save→restore 循环
        window2._restore_geometry()
        size = window2.size()
        assert size.width() == 900
        assert size.height() == 700

    def test_restore_default_when_no_saved_geometry(self, qapp, config_path: Path) -> None:
        window = MainWindow(config_path)
        window._settings = self._isolated_settings()
        window._settings.setValue("geometry", None)
        window._settings.setValue("windowState", None)
        window._restore_geometry()

        size = window.size()
        assert size.width() == 800
        assert size.height() == 600


class TestMainWindowConfigPanelIntegration:
    def test_load_config_delegates(self, main_window: MainWindow, config_path: Path) -> None:
        from src.config import get_preset, save_config

        config = get_preset("balanced")
        save_config(config, config_path)
        main_window.load_config()

        assert main_window._config_panel._asr_path_input.text() == config.asr.model_path

    def test_get_config_returns_appconfig(self, main_window: MainWindow, config_path: Path) -> None:
        main_window.load_config()
        config = main_window.get_config()
        from src.config import AppConfig

        assert isinstance(config, AppConfig)


class TestOpenOutputDir:
    def test_calls_open_with_default_app(self, main_window: MainWindow) -> None:
        with patch("src.gui.main_window.open_with_default_app") as mock_open:
            main_window._open_output_dir()
            mock_open.assert_called_once()

    def test_handles_exception_gracefully(self, main_window: MainWindow) -> None:
        with patch(
            "src.gui.main_window.open_with_default_app",
            side_effect=OSError("test error"),
        ):
            main_window._open_output_dir()  # 不应抛出异常
