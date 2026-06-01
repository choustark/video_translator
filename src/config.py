from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field

from src.exceptions import ConfigError

logger = logging.getLogger("video_translator")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = _PROJECT_ROOT / ".env"
_ENV_API_KEY = "VIDEO_TRANSLATOR_API_KEY"


def _load_dotenv(path: Path) -> dict[str, str]:
    """加载 .env 文件，返回键值对字典。文件不存在时返回空字典。"""
    if not path.exists():
        return {}
    return dotenv_values(str(path))  # type: ignore[no-any-return]


def save_api_key_to_env(api_key: str, path: Path = ENV_PATH) -> None:
    """将 API Key 写入 .env 文件，保留其他已有键值。"""
    existing = _load_dotenv(path)
    existing[_ENV_API_KEY] = api_key
    lines = [f"{k}={v}" for k, v in existing.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# 中文口语基准语速（字/秒），用于翻译时长约束和 TTS 语速计算
CHARS_PER_SEC = 4.0
# 默认内存告警阈值（GB），与 MemoryConfig.warning_gb 默认值保持同步
DEFAULT_MEMORY_WARNING_GB = 6.0


class ASRConfig(BaseModel):
    engine: Literal["mlx-whisper", "faster-whisper", "whisper"]
    model_path: str
    language: str = "en"
    proper_nouns: list[str] = Field(default_factory=list)
    use_default_proper_nouns: bool = True


class TranslationConfig(BaseModel):
    engine: Literal["glm", "deepseek", "openai", "deepl", "nllb"]
    api_key: str = ""
    model: str = "glm-4-flash"
    source_lang: str = "EN"
    target_lang: str = "ZH"


class TTSConfig(BaseModel):
    engine: Literal["cosyvoice", "edge-tts", "chattts"]
    model_path: str = ""
    voice: str = "default"
    # 不再暴露给 UI，三层自动化已覆盖（翻译时长约束 + rate 自适应 + rubberband）
    speed: float = Field(1.0, ge=0.5, le=2.0)
    conda_python_path: str = ""
    cosyvoice_source_path: str = ""


class SubtitleConfig(BaseModel):
    style: str = "classic_white"


class MemoryConfig(BaseModel):
    warning_gb: float = DEFAULT_MEMORY_WARNING_GB


class AppConfig(BaseModel):
    asr: ASRConfig
    translation: TranslationConfig
    tts: TTSConfig
    subtitle: SubtitleConfig = SubtitleConfig()
    memory: MemoryConfig = MemoryConfig()
    preset: str = "high_quality"


SUBTITLE_STYLES: dict[str, str] = {
    "classic_white": (  # noqa: E501
        "FontSize=20,PrimaryColour=&Hffffff&,"
        "OutlineColour=&H40000000,BorderStyle=1,Outline=2,Alignment=2"
    ),
    "yellow_black": (  # noqa: E501
        "FontSize=22,PrimaryColour=&H00ffff&,"
        "OutlineColour=&H000000,BorderStyle=3,Outline=1,Alignment=2"
    ),
    "white_clean": (  # noqa: E501
        "FontSize=18,PrimaryColour=&Hffffff&,"
        "BackColour=&H80000000,BorderStyle=3,Outline=0,Alignment=2"
    ),
}

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
        "tts": {"engine": "chattts"},
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


def load_config(path: Path, env_path: Path | None = None) -> AppConfig:
    """从 YAML 文件加载并校验应用配置，通过 .env 注入机密。

    Args:
        path: YAML 配置文件的路径。
        env_path: .env 文件路径，默认项目根目录下的 .env；不存在则跳过。

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
        config = AppConfig.model_validate(raw)
    except Exception as e:
        raise ConfigError(
            f"配置校验失败: {e}",
            stage="config",
            suggestion="检查必填字段和值的有效性",
        ) from e

    env_path = env_path or ENV_PATH
    env_values = _load_dotenv(env_path)
    if _ENV_API_KEY in env_values:
        config.translation.api_key = env_values[_ENV_API_KEY]
    elif os.getenv(_ENV_API_KEY):
        config.translation.api_key = os.environ[_ENV_API_KEY]

    return config


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
    data = config.model_dump(exclude={"translation": {"api_key": True}})
    content = yaml.dump(
        data,
        Dumper=_QuotedDumper,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    path.write_text(content, encoding="utf-8")
