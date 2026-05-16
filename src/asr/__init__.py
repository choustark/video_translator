from src.asr.base import ASREngine
from src.config import ASRConfig
from src.exceptions import ConfigError


def create_asr_engine(config: ASRConfig) -> ASREngine:
    from .faster_whisper_engine import FasterWhisperEngine
    from .mlx_whisper_engine import MLXWhisperEngine
    from .whisper_engine import WhisperEngine

    engines: dict[str, type[ASREngine]] = {
        "mlx-whisper": MLXWhisperEngine,
        "faster-whisper": FasterWhisperEngine,
        "whisper": WhisperEngine,
    }
    if config.engine not in engines:
        raise ConfigError(
            f"未知 ASR 引擎: '{config.engine}'",
            stage="config",
            suggestion=f"可选引擎: {', '.join(engines.keys())}",
        )
    return engines[config.engine](config)
