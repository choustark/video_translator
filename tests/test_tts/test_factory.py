import pytest

from src.config import TTSConfig
from src.exceptions import ConfigError
from src.tts import create_tts_engine


def test_create_cosyvoice_engine():
    config = TTSConfig(engine="cosyvoice")
    engine = create_tts_engine(config)
    assert engine.config.engine == "cosyvoice"


def test_create_edge_tts_engine():
    config = TTSConfig(engine="edge-tts")
    engine = create_tts_engine(config)
    assert engine.config.engine == "edge-tts"


def test_create_tts_engine_unknown_raises_config_error():
    config = TTSConfig.model_construct(engine="nonexistent")
    with pytest.raises(ConfigError, match="未知 TTS 引擎"):
        create_tts_engine(config)


def test_create_tts_engine_error_has_suggestion():
    config = TTSConfig.model_construct(engine="invalid")
    with pytest.raises(ConfigError) as exc_info:
        create_tts_engine(config)
    assert "cosyvoice" in exc_info.value.suggestion
    assert "edge-tts" in exc_info.value.suggestion
