import pytest

from src.asr.base import ASREngine
from src.config import ASRConfig


def test_asr_engine_is_abstract():
    config = ASRConfig(engine="mlx-whisper", model_path="/tmp/model")
    with pytest.raises(TypeError, match="abstract method"):
        ASREngine(config)


def test_asr_engine_config_stored():
    config = ASRConfig(engine="mlx-whisper", model_path="/tmp/model")

    class ConcreteEngine(ASREngine):
        def transcribe(self, audio_path, progress_callback=None):
            return []

    engine = ConcreteEngine(config)
    assert engine.config is config
    assert engine.config.engine == "mlx-whisper"
