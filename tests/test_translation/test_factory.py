import pytest

from src.config import TranslationConfig
from src.exceptions import ConfigError
from src.translation import create_translation_provider


@pytest.mark.parametrize("engine", ["glm", "deepseek", "openai", "deepl", "nllb"])
def test_create_translation_provider_known_engines(engine):
    config = TranslationConfig(engine=engine)
    provider = create_translation_provider(config)
    assert provider.config.engine == engine


def test_create_translation_provider_unknown_raises_config_error():
    config = TranslationConfig.model_construct(engine="nonexistent")
    with pytest.raises(ConfigError, match="未知翻译后端"):
        create_translation_provider(config)


def test_create_translation_provider_error_has_suggestion():
    config = TranslationConfig.model_construct(engine="invalid")
    with pytest.raises(ConfigError) as exc_info:
        create_translation_provider(config)
    assert "glm" in exc_info.value.suggestion
    assert "nllb" in exc_info.value.suggestion
