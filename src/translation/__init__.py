from src.config import TranslationConfig
from src.exceptions import ConfigError
from src.translation.base import TranslationProvider


def create_translation_provider(config: TranslationConfig) -> TranslationProvider:
    from .deepl_provider import DeepLProvider
    from .deepseek_provider import DeepSeekProvider
    from .glm_provider import GLMProvider
    from .local_nllb_provider import LocalNLLBProvider
    from .openai_provider import OpenAIProvider

    providers: dict[str, type[TranslationProvider]] = {
        "glm": GLMProvider,
        "deepseek": DeepSeekProvider,
        "openai": OpenAIProvider,
        "deepl": DeepLProvider,
        "nllb": LocalNLLBProvider,
    }
    if config.engine not in providers:
        raise ConfigError(
            f"未知翻译后端: '{config.engine}'",
            stage="config",
            suggestion=f"可选后端: {', '.join(providers.keys())}",
        )
    return providers[config.engine](config)
