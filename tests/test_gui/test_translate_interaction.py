from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QPushButton, QSlider

from src.gui.main_window import MainWindow


@pytest.fixture
def main_window(qapp, config_path: Path) -> MainWindow:
    return MainWindow(config_path)


class TestTranslateButton:
    def test_button_initially_disabled(self, main_window: MainWindow) -> None:
        assert main_window._translate_btn.isEnabled() is False
        assert main_window._translate_btn.text() == "开始翻译"
        assert main_window._translate_btn.objectName() == "primaryButton"

    def test_button_enabled_after_video_loaded(self, main_window: MainWindow) -> None:
        main_window._validation_passed = True
        main_window._on_video_loaded(Path("/test/video.mp4"))
        assert main_window._translate_btn.isEnabled() is True

    def test_button_ignores_non_path_signal(self, main_window: MainWindow) -> None:
        main_window._on_video_loaded("not_a_path")  # type: ignore[arg-type]
        assert main_window._translate_btn.isEnabled() is False

    def test_button_shows_translating_on_click(
        self, main_window: MainWindow
    ) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._translate_btn.setEnabled(True)
        with patch("src.gui.main_window.validate_all") as mock_validate:
            mock_validate.return_value.errors = []
            mock_validate.return_value.is_valid = True
            main_window._translate_btn.click()
        assert main_window._translate_btn.text() == "翻译中..."
        assert main_window._translate_btn.isEnabled() is False

    def test_rapid_clicks_blocked(self, main_window: MainWindow) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._translate_btn.setEnabled(True)
        with patch("src.gui.main_window.validate_all") as mock_validate:
            mock_validate.return_value.errors = []
            mock_validate.return_value.is_valid = True
            main_window._translate_btn.click()
        main_window._translate_btn.setEnabled(False)
        main_window._translate_btn.click()
        assert main_window._translate_btn.text() == "翻译中..."

    def test_button_restores_after_translate_done(
        self, main_window: MainWindow
    ) -> None:
        main_window._translate_btn.setText("翻译中...")
        main_window._translate_btn.setEnabled(False)
        main_window._on_translate_done()
        assert main_window._translate_btn.text() == "开始翻译"
        assert main_window._translate_btn.isEnabled() is False

    def test_button_restores_enabled_when_video_exists(
        self, main_window: MainWindow
    ) -> None:
        main_window._video_drop_area._video_path = Path("/test/video.mp4")
        main_window._validation_passed = True
        main_window._on_video_loaded(Path("/test/video.mp4"))
        main_window._translate_btn.setText("翻译中...")
        main_window._translate_btn.setEnabled(False)
        main_window._on_translate_done()
        assert main_window._translate_btn.isEnabled() is True


class TestSpeedSlider:
    def test_speed_slider_exists(self, main_window: MainWindow) -> None:
        assert isinstance(main_window._speed_slider, QSlider)
        assert main_window._speed_slider.minimum() == 5
        assert main_window._speed_slider.maximum() == 20
        assert main_window._speed_slider.value() == 10

    def test_speed_value_label(self, main_window: MainWindow) -> None:
        assert main_window._speed_value_label.text() == "1.0x"

    def test_right_slider_syncs_to_left(self, main_window: MainWindow) -> None:
        main_window._speed_slider.setValue(15)
        assert main_window._config_panel._speed_slider.value() == 15
        assert main_window._speed_value_label.text() == "1.5x"

    def test_left_slider_syncs_to_right(self, main_window: MainWindow) -> None:
        main_window._config_panel._speed_slider.setValue(8)
        assert main_window._speed_slider.value() == 8
        assert main_window._speed_value_label.text() == "0.8x"

    def test_bidirectional_no_signal_loop(
        self, main_window: MainWindow
    ) -> None:
        main_window._speed_slider.setValue(12)
        assert main_window._config_panel._speed_slider.value() == 12
        main_window._config_panel._speed_slider.setValue(18)
        assert main_window._speed_slider.value() == 18
        assert main_window._speed_value_label.text() == "1.8x"

    def test_slider_boundary_min(self, main_window: MainWindow) -> None:
        main_window._speed_slider.setValue(5)
        assert main_window._speed_value_label.text() == "0.5x"

    def test_slider_boundary_max(self, main_window: MainWindow) -> None:
        main_window._speed_slider.setValue(20)
        assert main_window._speed_value_label.text() == "2.0x"


class TestOpenOutputButton:
    def test_button_exists(self, main_window: MainWindow) -> None:
        assert isinstance(main_window._open_output_btn, QPushButton)
        assert main_window._open_output_btn.objectName() == "secondaryButton"
        assert main_window._open_output_btn.text() == "打开输出目录"

    def test_creates_output_dir_on_click(
        self, main_window: MainWindow, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "output"
        with (
            patch("src.gui.main_window._OUTPUT_DIR", output_dir),
            patch("subprocess.run") as mock_run,
        ):
            main_window._open_output_btn.click()
            assert output_dir.exists()
            mock_run.assert_called_once_with(["open", str(output_dir)], check=False)

    def test_creates_dir_if_not_exists(
        self, main_window: MainWindow, tmp_path: Path
    ) -> None:
        output_dir = tmp_path / "nested" / "output"
        with (
            patch("src.gui.main_window._OUTPUT_DIR", output_dir),
            patch("subprocess.run"),
        ):
            main_window._open_output_btn.click()
            assert output_dir.exists()

    def test_mkdir_failure_does_not_crash(
        self, main_window: MainWindow
    ) -> None:
        with (
            patch("src.gui.main_window._OUTPUT_DIR", Path("/nonexistent/output")),
            patch("subprocess.run", side_effect=OSError("permission denied")),
        ):
            main_window._open_output_btn.click()


class TestVideoLoadedSignalIntegration:
    def test_video_loaded_enables_button(
        self, main_window: MainWindow
    ) -> None:
        assert main_window._translate_btn.isEnabled() is False

        main_window._validation_passed = True

        with (
            patch.object(Path, "is_file", return_value=True),
            patch("shutil.which", return_value="/usr/local/bin/ffprobe"),
            patch("subprocess.run") as mock_run,
        ):
            mock_result = MagicMock()
            mock_result.returncode = 0
            mock_result.stdout = "120.0\n"
            mock_result.stderr = ""
            mock_run.return_value = mock_result

            event = MagicMock()
            url_mock = MagicMock()
            url_mock.toLocalFile.return_value = "/test/video.mp4"
            mime = MagicMock()
            mime.hasUrls.return_value = True
            mime.urls.return_value = [url_mock]
            event.mimeData.return_value = mime

            main_window._video_drop_area.dropEvent(event)

        assert main_window._translate_btn.isEnabled() is True
