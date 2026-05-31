from src.asr.base import ASREngine
from src.config import ASRConfig
from src.exceptions import ConfigError

_engines_raw: dict[str, type[ASREngine] | None] = {}

try:
    from .mlx_whisper_engine import MLXWhisperEngine

    _engines_raw["mlx-whisper"] = MLXWhisperEngine
except ImportError:
    _engines_raw["mlx-whisper"] = None

try:
    from .faster_whisper_engine import FasterWhisperEngine

    _engines_raw["faster-whisper"] = FasterWhisperEngine
except ImportError:
    _engines_raw["faster-whisper"] = None

try:
    from .whisper_engine import WhisperEngine

    _engines_raw["whisper"] = WhisperEngine
except ImportError:
    _engines_raw["whisper"] = None

_AVAILABLE_ENGINES: dict[str, type[ASREngine]] = {
    k: v for k, v in _engines_raw.items() if v is not None
}


def create_asr_engine(config: ASRConfig) -> ASREngine:
    """根据配置创建 ASR 引擎实例（工厂函数）。

    Args:
        config: ASR 配置，engine 字段决定创建哪种引擎。

    Returns:
        对应的 ASREngine 实例。

    Raises:
        ConfigError: engine 字段不匹配任何已注册引擎时抛出。
    """
    if config.engine not in _AVAILABLE_ENGINES:
        available = ", ".join(_AVAILABLE_ENGINES.keys()) or "无可用引擎"
        raise ConfigError(
            f"当前平台不可用: '{config.engine}'",
            stage="config",
            suggestion=f"可用引擎: {available}",
        )
    return _AVAILABLE_ENGINES[config.engine](config)
