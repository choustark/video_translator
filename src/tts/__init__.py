from src.config import TTSConfig
from src.exceptions import ConfigError
from src.tts.base import TTSEngine


def create_tts_engine(config: TTSConfig) -> TTSEngine:
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
