from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

from src.exceptions import ConfigError

logger = logging.getLogger("video_translator")


class ASRConfig(BaseModel):
    engine: Literal["mlx-whisper", "faster-whisper", "whisper"]
    model_path: str
    language: str = "en"


class TranslationConfig(BaseModel):
    engine: Literal["glm", "deepseek", "openai", "deepl", "nllb"]
    api_key: str = ""
    model: str = "glm-4-flash"
    source_lang: str = "EN"
    target_lang: str = "ZH"


class TTSConfig(BaseModel):
    engine: Literal["cosyvoice", "edge-tts"]
    model_path: str = ""
    voice: str = "default"
    speed: float = Field(1.0, ge=0.5, le=2.0)


class AppConfig(BaseModel):
    asr: ASRConfig
    translation: TranslationConfig
    tts: TTSConfig
    preset: str = "high_quality"


_PRESETS_DATA: dict[str, dict] = {
    "high_quality": {
        "asr": {"engine": "mlx-whisper", "model_path": "models/asr/whisper-large-v3-turbo"},
        "translation": {"engine": "glm"},
        "tts": {"engine": "cosyvoice"},
    },
    "balanced": {
        "asr": {"engine": "mlx-whisper", "model_path": "models/asr/whisper-medium"},
        "translation": {"engine": "deepseek"},
        "tts": {"engine": "cosyvoice"},
    },
    "fast": {
        "asr": {"engine": "mlx-whisper", "model_path": "models/asr/whisper-tiny"},
        "translation": {"engine": "deepseek"},
        "tts": {"engine": "edge-tts"},
    },
    "offline": {
        "asr": {"engine": "mlx-whisper", "model_path": "models/asr/whisper-medium"},
        "translation": {"engine": "nllb"},
        "tts": {"engine": "cosyvoice"},
    },
    "docker": {
        "asr": {"engine": "faster-whisper", "model_path": "models/asr/whisper-medium"},
        "translation": {"engine": "glm"},
        "tts": {"engine": "edge-tts"},
    },
}

PRESETS: dict[str, AppConfig] = {name: AppConfig(**data) for name, data in _PRESETS_DATA.items()}


def get_preset(name: str) -> AppConfig:
    """按名称获取预设配置方案的深拷贝。

    Args:
        name: 预设方案名称，可选值见 ``PRESETS`` 字典的键。

    Returns:
        该预设方案的 ``AppConfig`` 深拷贝实例。

    Raises:
        ConfigError: 预设方案名称不存在时抛出。
    """
    if name not in PRESETS:
        raise ConfigError(
            f"未知预设方案: '{name}'",
            stage="config",
            suggestion=f"可选方案: {', '.join(PRESETS.keys())}",
        )
    return PRESETS[name].model_copy(deep=True)


def load_config(path: Path) -> AppConfig:
    """从 YAML 文件加载并校验应用配置。

    Args:
        path: YAML 配置文件的路径。

    Returns:
        校验通过的 ``AppConfig`` 实例。

    Raises:
        ConfigError: 文件不存在、YAML 格式错误或字段校验失败时抛出。
    """
    if not path.exists():
        raise ConfigError(
            f"配置文件不存在: {path}",
            stage="config",
            suggestion="请先创建 config.yaml 或使用预设方案",
        )
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ConfigError(
            f"配置文件 YAML 格式错误: {e}",
            stage="config",
            suggestion="检查缩进和语法",
        ) from e

    if not isinstance(raw, dict):
        raise ConfigError(
            "配置文件格式错误：期望键值对结构",
            stage="config",
        )

    try:
        return AppConfig.model_validate(raw)
    except Exception as e:
        raise ConfigError(
            f"配置校验失败: {e}",
            stage="config",
            suggestion="检查必填字段和值的有效性",
        ) from e


class _QuotedDumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: _QuotedDumper, data: str) -> yaml.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


_QuotedDumper.add_representer(str, _str_representer)


def save_config(config: AppConfig, path: Path) -> None:
    """将应用配置序列化为 YAML 并写入文件。

    所有字符串值会被双引号包裹，父目录不存在时自动创建。

    Args:
        config: 要保存的 ``AppConfig`` 实例。
        path: 目标文件路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = config.model_dump()
    content = yaml.dump(
        data,
        Dumper=_QuotedDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    path.write_text(content, encoding="utf-8")
