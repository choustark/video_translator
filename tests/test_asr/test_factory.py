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
    with pytest.raises(ConfigError, match="当前平台不可用"):
        create_asr_engine(config)


def test_create_asr_engine_error_has_suggestion():
    config = ASRConfig.model_construct(engine="invalid", model_path="/tmp/model")
    with pytest.raises(ConfigError) as exc_info:
        create_asr_engine(config)
    assert "可用引擎" in exc_info.value.suggestion


def test_mlx_whisper_import_error_graceful():
    """mlx-whisper 未安装时，工厂不应崩溃，而是提示不可用。"""
    import src.asr as asr_mod

    saved = asr_mod._AVAILABLE_ENGINES.copy()
    saved_raw = asr_mod._engines_raw.copy()
    try:
        asr_mod._engines_raw["mlx-whisper"] = None
        asr_mod._AVAILABLE_ENGINES.pop("mlx-whisper", None)

        config = ASRConfig(engine="mlx-whisper", model_path="/tmp/model")
        with pytest.raises(ConfigError, match="当前平台不可用"):
            create_asr_engine(config)
    finally:
        asr_mod._engines_raw["mlx-whisper"] = saved.get("mlx-whisper")
        if "mlx-whisper" in saved:
            asr_mod._AVAILABLE_ENGINES["mlx-whisper"] = saved["mlx-whisper"]
