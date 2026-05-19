from src.asr.base import ASREngine
from src.config import ASRConfig
from src.exceptions import ConfigError


def create_asr_engine(config: ASRConfig) -> ASREngine:
    """根据配置创建 ASR 引擎实例（工厂函数）。

    Args:
        config: ASR 配置，engine 字段决定创建哪种引擎。

    Returns:
        对应的 ASREngine 实例。

    Raises:
        ConfigError: engine 字段不匹配任何已注册引擎时抛出。
    """
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
