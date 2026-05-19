import pytest

from src.config import TTSConfig
from src.tts.base import TTSEngine


def test_tts_engine_is_abstract():
    config = TTSConfig(engine="cosyvoice")
    with pytest.raises(TypeError, match="abstract method"):
        TTSEngine(config)


def test_tts_engine_config_stored():
    config = TTSConfig(engine="cosyvoice", speed=1.2)

    class ConcreteEngine(TTSEngine):
        def synthesize(self, segments, temp_dir, progress_callback=None):
            return []

    engine = ConcreteEngine(config)
    assert engine.config is config
    assert engine.config.speed == 1.2
