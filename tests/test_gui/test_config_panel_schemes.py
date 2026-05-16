from pathlib import Path

import pytest

from src.config import get_preset
from src.scheme_manager import SchemeManager


@pytest.fixture
def panel_with_schemes(qapp, config_path: Path, tmp_path: Path) -> tuple:
    from src.gui.config_panel import ConfigPanel

    schemes_dir = tmp_path / "schemes"
    schemes_dir.mkdir()
    panel = ConfigPanel(config_path)
    panel._scheme_mgr = SchemeManager(schemes_dir)
    panel.load_config()
    return panel, schemes_dir


class TestConfigPanelSchemeSaveLoad:
    def test_save_and_list_scheme(
        self, panel_with_schemes: tuple, config_path: Path
    ) -> None:
        panel, schemes_dir = panel_with_schemes
        assert panel._scheme_combo.count() == 1  # only placeholder

        panel._scheme_mgr.save_scheme("test_scheme", get_preset("fast"))
        panel.refresh_schemes()

        assert panel._scheme_combo.count() == 2
        assert panel._scheme_combo.itemText(1) == "test_scheme"

    def test_load_scheme_updates_panel(
        self, panel_with_schemes: tuple, config_path: Path
    ) -> None:
        panel, schemes_dir = panel_with_schemes
        config = get_preset("offline")
        config.translation.api_key = "test-key"
        panel._scheme_mgr.save_scheme("offline_scheme", config)
        panel.refresh_schemes()

        idx = panel._scheme_combo.findData("offline_scheme")
        panel._scheme_combo.setCurrentIndex(idx)

        assert panel._translation_combo.currentData() == "nllb"

    def test_delete_scheme(
        self, panel_with_schemes: tuple, config_path: Path
    ) -> None:
        panel, schemes_dir = panel_with_schemes
        panel._scheme_mgr.save_scheme("to_delete", get_preset("high_quality"))
        panel.refresh_schemes()
        assert panel._scheme_combo.count() == 2

        panel._scheme_mgr.delete_scheme("to_delete")
        panel.refresh_schemes()
        assert panel._scheme_combo.count() == 1
