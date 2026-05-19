from src.config import TTSConfig
from src.exceptions import ConfigError
from src.tts.base import TTSEngine


def create_tts_engine(config: TTSConfig) -> TTSEngine:
    """根据配置创建 TTS 引擎实例。

    Args:
        config: TTS 配置对象，需包含 engine 字段。

    Returns:
        对应引擎类型的 TTSEngine 实例（cosyvoice 或 edge-tts）。

    Raises:
        ConfigError: 配置中的引擎名称不在可选范围内时抛出。
    """
    from .cosyvoice_engine import CosyVoiceEngine
    from .edge_tts_engine import EdgeTTSEngine

    engines: dict[str, type[TTSEngine]] = {
        "cosyvoice": CosyVoiceEngine,
        "edge-tts": EdgeTTSEngine,
    }
    if config.engine not in engines:
        raise ConfigError(
            f"未知 TTS 引擎: '{config.engine}'",
            stage="config",
            suggestion=f"可选引擎: {', '.join(engines.keys())}",
        )
    return engines[config.engine](config)
