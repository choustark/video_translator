import pytest

from src.config import TranslationConfig
from src.translation.base import TranslationProvider


def test_translation_provider_is_abstract():
    config = TranslationConfig(engine="glm")
    with pytest.raises(TypeError, match="abstract method"):
        TranslationProvider(config)


def test_translation_provider_config_stored():
    config = TranslationConfig(engine="glm", api_key="test-key")

    class ConcreteProvider(TranslationProvider):
        def translate(self, segments, progress_callback=None):
            return []

    provider = ConcreteProvider(config)
    assert provider.config is config
    assert provider.config.engine == "glm"
