from pathlib import Path

import pytest
from PySide6.QtWidgets import QLineEdit

from src.config import PRESETS, get_preset, load_config, save_config
from src.gui.config_panel import ConfigPanel


@pytest.fixture
def panel(qapp, config_path: Path) -> ConfigPanel:
    p = ConfigPanel(config_path)
    return p


def _fill_all(panel: ConfigPanel, config_path: Path) -> None:
    save_config(get_preset("high_quality"), config_path)
    panel.load_config()


class TestConfigPanelLoadConfig:
    def test_load_from_file(self, panel: ConfigPanel, config_path: Path) -> None:
        config = get_preset("balanced")
        save_config(config, config_path)

        panel.load_config()

        assert panel._asr_path_input.text() == config.asr.model_path

    def test_load_default_when_no_file(self, panel: ConfigPanel, config_path: Path) -> None:
        panel.load_config()

        assert config_path.exists()
        default = get_preset("high_quality")
        assert panel._asr_path_input.text() == default.asr.model_path

    def test_load_invalid_yaml_falls_back(self, panel: ConfigPanel, config_path: Path) -> None:
        config_path.write_text(":: invalid yaml {{{", encoding="utf-8")

        panel.load_config()

        default = get_preset("high_quality")
        assert panel._asr_path_input.text() == default.asr.model_path


class TestConfigPanelPresetSwitch:
    def test_preset_switch_updates_fields(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)

        idx = panel._preset_combo.findData("fast")
        panel._preset_combo.setCurrentIndex(idx)

        fast = PRESETS["fast"]
        assert panel._asr_path_input.text() == fast.asr.model_path
        assert panel._translation_combo.currentData() == fast.translation.engine

    def test_preset_switch_preserves_api_key(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)
        panel._api_key_input.setText("test-key-123")

        idx = panel._preset_combo.findData("balanced")
        panel._preset_combo.setCurrentIndex(idx)

        balanced = PRESETS["balanced"]
        assert panel._api_key_input.text() == "test-key-123"
        assert panel._translation_combo.currentData() == balanced.translation.engine


class TestConfigPanelPersistence:
    def test_change_triggers_save(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)

        panel._api_key_input.setText("new-api-key")
        panel._do_save()

        saved = load_config(config_path)
        assert saved.translation.api_key == "new-api-key"

    def test_reload_restores_state(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)
        panel._api_key_input.setText("persisted-key")
        panel._do_save()

        panel2 = ConfigPanel(config_path)
        panel2.load_config()

        assert panel2._api_key_input.text() == "persisted-key"


class TestConfigPanelApiKeyToggle:
    def test_toggle_visibility(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)

        assert panel._api_key_input.echoMode() == QLineEdit.EchoMode.Password

        panel._toggle_api_key_visibility()
        assert panel._api_key_input.echoMode() == QLineEdit.EchoMode.Normal
        assert panel._api_key_toggle.text() == "隐藏"

        panel._toggle_api_key_visibility()
        assert panel._api_key_input.echoMode() == QLineEdit.EchoMode.Password
        assert panel._api_key_toggle.text() == "显示"


class TestConfigPanelGetConfig:
    def test_get_config_returns_appconfig(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)

        config = panel.get_config()
        assert config.preset == "high_quality"
        assert config.asr.model_path == PRESETS["high_quality"].asr.model_path

    def test_get_config_returns_deep_copy(self, panel: ConfigPanel, config_path: Path) -> None:
        _fill_all(panel, config_path)

        config1 = panel.get_config()
        config2 = panel.get_config()
        assert config1 is not config2

    def test_proper_nouns_support_chinese_punctuation_and_newlines(
        self, panel: ConfigPanel, config_path: Path
    ) -> None:
        _fill_all(panel, config_path)

        panel._proper_nouns_input.setPlainText("OpenAI，旧金山\nSam Altman、PySide6;ffmpeg")

        config = panel.get_config()
        assert config.asr.proper_nouns == [
            "OpenAI",
            "旧金山",
            "Sam Altman",
            "PySide6",
            "ffmpeg",
        ]

    def test_use_default_proper_nouns_checkbox_is_collected(
        self, panel: ConfigPanel, config_path: Path
    ) -> None:
        _fill_all(panel, config_path)

        panel._use_default_nouns_cb.setChecked(False)

        config = panel.get_config()
        assert config.asr.use_default_proper_nouns is False
