import pytest

from src.asr import create_asr_engine
from src.config import ASRConfig
from src.exceptions import ConfigError


def test_create_mlx_whisper_engine():
    config = ASRConfig(engine="mlx-whisper", model_path="/tmp/model")
    engine = create_asr_engine(config)
    assert engine.config.engine == "mlx-whisper"


def test_create_faster_whisper_engine():
    config = ASRConfig(engine="faster-whisper", model_path="/tmp/model")
    engine = create_asr_engine(config)
    assert engine.config.engine == "faster-whisper"


def test_create_whisper_engine():
    config = ASRConfig(engine="whisper", model_path="/tmp/model")
    engine = create_asr_engine(config)
    assert engine.config.engine == "whisper"


def test_create_asr_engine_unknown_raises_config_error():
    config = ASRConfig.model_construct(engine="nonexistent", model_path="/tmp/model")
    with pytest.raises(ConfigError, match="未知 ASR 引擎"):
        create_asr_engine(config)


def test_create_asr_engine_error_has_suggestion():
    config = ASRConfig.model_construct(engine="invalid", model_path="/tmp/model")
    with pytest.raises(ConfigError) as exc_info:
        create_asr_engine(config)
    assert "mlx-whisper" in exc_info.value.suggestion
    assert "faster-whisper" in exc_info.value.suggestion
    assert "whisper" in exc_info.value.suggestion
