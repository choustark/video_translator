from pathlib import Path

import pytest
import yaml

from src.config import (
    PRESETS,
    AppConfig,
    ASRConfig,
    TranslationConfig,
    TTSConfig,
    get_preset,
    load_config,
    save_config,
)
from src.exceptions import ConfigError


class TestASRConfig:
    def test_valid_config(self) -> None:
        cfg = ASRConfig(engine="mlx-whisper", model_path="/models/asr/whisper")
        assert cfg.engine == "mlx-whisper"
        assert cfg.language == "en"

    def test_invalid_engine(self) -> None:
        with pytest.raises(Exception):
            ASRConfig(engine="invalid", model_path="/models")


class TestTranslationConfig:
    def test_defaults(self) -> None:
        cfg = TranslationConfig(engine="glm")
        assert cfg.api_key == ""
        assert cfg.source_lang == "EN"
        assert cfg.target_lang == "ZH"


class TestTTSConfig:
    def test_speed_validation(self) -> None:
        TTSConfig(engine="cosyvoice", speed=0.5)
        TTSConfig(engine="cosyvoice", speed=2.0)

    def test_speed_out_of_range(self) -> None:
        with pytest.raises(Exception):
            TTSConfig(engine="cosyvoice", speed=0.1)
        with pytest.raises(Exception):
            TTSConfig(engine="cosyvoice", speed=3.0)


class TestAppConfig:
    def test_full_config(self) -> None:
        cfg = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="/asr"),
            translation=TranslationConfig(engine="glm"),
            tts=TTSConfig(engine="cosyvoice"),
        )
        assert cfg.preset == "high_quality"


class TestPresets:
    def test_four_presets_exist(self) -> None:
        assert "high_quality" in PRESETS
        assert "balanced" in PRESETS
        assert "fast" in PRESETS
        assert "offline" in PRESETS

    def test_high_quality_preset(self) -> None:
        cfg = get_preset("high_quality")
        assert cfg.asr.engine == "mlx-whisper"
        assert cfg.translation.engine == "glm"
        assert cfg.tts.engine == "cosyvoice"

    def test_fast_preset(self) -> None:
        cfg = get_preset("fast")
        assert cfg.tts.engine == "edge-tts"

    def test_offline_preset(self) -> None:
        cfg = get_preset("offline")
        assert cfg.translation.engine == "nllb"

    def test_unknown_preset(self) -> None:
        with pytest.raises(ConfigError):
            get_preset("nonexistent")


class TestYamlLoadSave:
    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        cfg = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="/asr/model"),
            translation=TranslationConfig(engine="glm", api_key="test-key"),
            tts=TTSConfig(engine="cosyvoice", speed=1.2),
            preset="custom",
        )
        path = tmp_path / "config.yaml"
        save_config(cfg, path)

        loaded = load_config(path)
        assert loaded.asr.engine == "mlx-whisper"
        assert loaded.asr.model_path == "/asr/model"
        assert loaded.translation.api_key == "test-key"
        assert loaded.tts.speed == 1.2
        assert loaded.preset == "custom"

    def test_load_nonexistent_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="配置文件不存在"):
            load_config(tmp_path / "nope.yaml")

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("asr:\n  engine: [broken\n")
        with pytest.raises(ConfigError, match="YAML"):
            load_config(path)

    def test_load_missing_field(self, tmp_path: Path) -> None:
        path = tmp_path / "partial.yaml"
        path.write_text(yaml.dump({"asr": {"engine": "mlx-whisper"}}, default_flow_style=False))
        with pytest.raises(ConfigError, match="model_path|缺失"):
            load_config(path)

    def test_load_invalid_engine_value(self, tmp_path: Path) -> None:
        data = {
            "asr": {"engine": "bad-engine", "model_path": "/m"},
            "translation": {"engine": "glm"},
            "tts": {"engine": "cosyvoice"},
        }
        path = tmp_path / "bad_engine.yaml"
        path.write_text(yaml.dump(data, default_flow_style=False))
        with pytest.raises(ConfigError):
            load_config(path)

    def test_save_creates_directory(self, tmp_path: Path) -> None:
        path = tmp_path / "subdir" / "config.yaml"
        cfg = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="/m"),
            translation=TranslationConfig(engine="glm"),
            tts=TTSConfig(engine="cosyvoice"),
        )
        save_config(cfg, path)
        assert path.exists()

    def test_yaml_string_values_quoted(self, tmp_path: Path) -> None:
        cfg = AppConfig(
            asr=ASRConfig(engine="mlx-whisper", model_path="/m"),
            translation=TranslationConfig(engine="glm"),
            tts=TTSConfig(engine="cosyvoice"),
        )
        path = tmp_path / "quoted.yaml"
        save_config(cfg, path)
        content = path.read_text()
        assert '"mlx-whisper"' in content
