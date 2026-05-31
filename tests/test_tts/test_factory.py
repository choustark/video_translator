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
    with pytest.raises(ConfigError, match="未知或不可用的 TTS 引擎"):
        create_tts_engine(config)


def test_create_tts_engine_error_has_suggestion():
    config = TTSConfig.model_construct(engine="invalid")
    with pytest.raises(ConfigError) as exc_info:
        create_tts_engine(config)
    assert "cosyvoice" in exc_info.value.suggestion
    assert "edge-tts" in exc_info.value.suggestion


def test_create_chattts_engine_when_installed():
    """当 ChatTTS 依赖可用时，factory 能正确创建引擎。"""
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock

    saved: dict[str, object | None] = {}
    for key in ("src.tts.chattts_engine", "ChatTTS", "torch", "torchaudio"):
        if key in sys.modules:
            saved[key] = sys.modules.pop(key)

    fake_chattts_mod = ModuleType("ChatTTS")
    fake_chat_cls = MagicMock()
    fake_chattts_mod.Chat = fake_chat_cls
    sys.modules["ChatTTS"] = fake_chattts_mod

    fake_torch = ModuleType("torch")
    sys.modules["torch"] = fake_torch

    fake_ta = ModuleType("torchaudio")
    sys.modules["torchaudio"] = fake_ta

    try:
        config = TTSConfig(engine="chattts")
        engine = create_tts_engine(config)
        assert engine.config.engine == "chattts"
    finally:
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        sys.modules.pop("src.tts.chattts_engine", None)
