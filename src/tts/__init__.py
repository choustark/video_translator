from src.config import TTSConfig
from src.exceptions import ConfigError
from src.tts.base import TTSEngine


def create_tts_engine(config: TTSConfig) -> TTSEngine:
    """根据配置创建 TTS 引擎实例。

    Args:
        config: TTS 配置对象，需包含 engine 字段。

    Returns:
        对应引擎类型的 TTSEngine 实例。

    Raises:
        ConfigError: 配置中的引擎名称不在可选范围内时抛出。
    """
    from .cosyvoice_engine import CosyVoiceEngine
    from .edge_tts_engine import EdgeTTSEngine

    try:
        from .chattts_engine import ChatTTSEngine
    except ImportError:
        ChatTTSEngine = None  # type: ignore[assignment,misc]

    engines: dict[str, type[TTSEngine] | None] = {
        "cosyvoice": CosyVoiceEngine,
        "edge-tts": EdgeTTSEngine,
        "chattts": ChatTTSEngine,
    }
    available: dict[str, type[TTSEngine]] = {k: v for k, v in engines.items() if v is not None}
    if config.engine not in available:
        names = ", ".join(available.keys()) or "无可用引擎"
        raise ConfigError(
            f"未知或不可用的 TTS 引擎: '{config.engine}'",
            stage="config",
            suggestion=f"可选引擎: {names}",
        )
    return available[config.engine](config)
