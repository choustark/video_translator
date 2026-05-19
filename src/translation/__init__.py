from src.config import TranslationConfig
from src.exceptions import ConfigError
from src.translation.base import TranslationProvider


def create_translation_provider(config: TranslationConfig) -> TranslationProvider:
    """根据配置创建翻译后端实例。

    支持的后端: "glm", "deepseek", "openai", "deepl", "nllb"。

    Args:
        config: 翻译配置，engine 字段决定使用哪个后端。

    Returns:
        对应引擎的 TranslationProvider 实例。

    Raises:
        ConfigError: 当 config.engine 不是已知的后端名称时。
    """
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
