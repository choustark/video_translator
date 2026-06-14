"""D60 CosyVoice 声音克隆 — ConfigPanel 参考音频 UI 控件测试。

验证：
- 控件存在且默认空
- 设置 text 后 get_config().tts.reference_audio 正确返回
- 状态在 save/load 之间持久化
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import get_preset, save_config
from src.gui.config_panel import ConfigPanel


@pytest.fixture
def panel(qapp, config_path: Path) -> ConfigPanel:
    return ConfigPanel(config_path)


class TestConfigPanelReferenceAudio:
    def test_reference_audio_default_empty(self, panel: ConfigPanel, config_path: Path) -> None:
        """AC6 测试 6（部分）：未选择参考音频时 reference_audio 为空字符串。"""
        save_config(get_preset("high_quality"), config_path)
        panel.load_config()

        assert panel._tts_reference_input.text() == ""
        assert panel.get_config().tts.reference_audio == ""

    def test_reference_audio_field_persists_to_config(
        self,
        panel: ConfigPanel,
        config_path: Path,
        tmp_path: Path,
    ) -> None:
        """AC6 测试 7：UI 选择文件后 get_config().tts.reference_audio 返回该路径。"""
        save_config(get_preset("high_quality"), config_path)
        panel.load_config()

        ref_wav = tmp_path / "voice.wav"
        panel._tts_reference_input.setText(str(ref_wav))

        config = panel.get_config()
        assert config.tts.reference_audio == str(ref_wav)

    def test_reference_audio_state_survives_save_load(
        self,
        panel: ConfigPanel,
        config_path: Path,
        tmp_path: Path,
    ) -> None:
        """参考音频字段经 save_config → load_config 后保持。"""
        save_config(get_preset("high_quality"), config_path)
        panel.load_config()

        ref_wav = tmp_path / "voice.wav"
        panel._tts_reference_input.setText(str(ref_wav))
        panel._do_save()

        panel2 = ConfigPanel(config_path)
        panel2.load_config()
        assert panel2._tts_reference_input.text() == str(ref_wav)
        assert panel2.get_config().tts.reference_audio == str(ref_wav)
