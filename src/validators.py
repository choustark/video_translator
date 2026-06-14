from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import psutil

from src.config import (
    DEFAULT_MEMORY_WARNING_GB,
    MAX_VIDEO_DURATION_SECONDS,
    AppConfig,
    format_duration_limit,
)
from src.exceptions import ValidationError
from src.utils.platform_utils import get_ffmpeg_install_hint

logger = logging.getLogger("video_translator")

_MIN_FFMPEG_VERSION = 4
_API_CHECK_TIMEOUT_SECONDS = 5

# 磁盘空间估算系数：视频大小 × 3 足够覆盖 WAV 提取 + TTS 段音频 + 最终合成视频的峰值占用。
# 保守取值，给用户留余量；2 小时视频中间产物实测约 1.2GB。
_DISK_SPACE_ESTIMATE_MULTIPLIER = 3

_SUPPORTED_VIDEO_FORMATS = frozenset({".mp4", ".mkv", ".mov", ".avi"})


def validate_ffmpeg() -> None:
    """校验 ffmpeg 可用性及版本。

    通过 shutil.which 检测 ffmpeg 路径，并通过 `ffmpeg -version` 解析主版本号，
    要求 ≥4.0。

    Raises:
        ValidationError: ffmpeg 不存在或版本过低。
    """
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        raise ValidationError(
            "未检测到 ffmpeg",
            stage="ffmpeg",
            suggestion=f"请安装 ffmpeg: {get_ffmpeg_install_hint()}",
        )

    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ValidationError(
            f"ffmpeg 版本检测失败: {e}",
            stage="ffmpeg",
            suggestion="请确认 ffmpeg 可正常执行: ffmpeg -version",
        ) from e

    first_line = result.stdout.split("\n")[0] if result.stdout else ""
    match = re.search(r"ffmpeg version (\d+)", first_line)
    if not match:
        raise ValidationError(
            f"无法解析 ffmpeg 版本号: {first_line!r}",
            stage="ffmpeg",
            suggestion="请确认 ffmpeg 可正常执行: ffmpeg -version",
        )

    major = int(match.group(1))
    if major < _MIN_FFMPEG_VERSION:
        raise ValidationError(
            f"ffmpeg 版本过低: {major}.x，需要 ≥{_MIN_FFMPEG_VERSION}.0",
            stage="ffmpeg",
            suggestion=f"请升级 ffmpeg 至 {_MIN_FFMPEG_VERSION}.0 或更高版本",
        )


def validate_asr_model(model_path: str) -> None:
    """校验 ASR 模型文件是否存在。

    Args:
        model_path: ASR 模型路径（目录或文件）。

    Raises:
        ValidationError: 路径为空或不存在。
    """
    if not model_path:
        raise ValidationError(
            "未配置 ASR 模型路径",
            stage="asr",
            suggestion="请在配置中指定 ASR 模型路径",
        )
    p = Path(model_path)
    if not p.exists():
        raise ValidationError(
            f"ASR 模型文件不存在: {model_path}",
            stage="asr",
            suggestion="请检查模型路径是否正确，或下载所需模型",
        )
    if not p.is_dir():
        raise ValidationError(
            f"ASR 模型路径不是目录: {model_path}",
            stage="asr",
            suggestion="请确认模型路径指向包含 config.json 和 weights 的目录",
        )


def validate_translation_api(engine: str, api_key: str) -> None:
    """校验翻译 API Key 是否有效。

    对云端引擎（glm/deepseek/openai/deepl）发送最小测试请求验证 Key；
    NLLB 本地引擎直接跳过。网络超时/连接错误不视为 Key 无效。

    Args:
        engine: 翻译引擎名称（glm/deepseek/openai/deepl/nllb）。
        api_key: API Key 字符串。

    Raises:
        ValidationError: Key 为空或认证失败（HTTP 401/403）。
    """
    if engine == "nllb":
        return

    if not api_key:
        raise ValidationError(
            f"未配置 {engine} API Key",
            stage="translation",
            suggestion=f"请在配置中填写 {engine} 的 API Key",
        )

    url, headers, body = _build_api_check_request(engine, api_key)

    try:
        data = json.dumps(body).encode("utf-8") if body else None
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=_API_CHECK_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise ValidationError(
                f"{engine} API Key 无效（HTTP {e.code}）",
                stage="translation",
                suggestion=f"请检查 {engine} API Key 是否正确",
            ) from e
        # 其他 HTTP 错误（如 429 限流、500 服务端错误）不视为 Key 无效
        logger.warning("翻译 API 校验收到 HTTP %d，跳过 Key 有效性判断: %s", e.code, engine)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # 网络问题不阻止翻译启动，运行时 tenacity 会重试
        logger.warning("翻译 API 校验网络错误，跳过: %s — %s", engine, e)


def _build_api_check_request(
    engine: str, api_key: str
) -> tuple[str, dict[str, str], dict[str, object]]:
    """构建各翻译引擎的最小 API Key 验证请求。

    Returns:
        (url, headers, body) 三元组。
    """
    if engine == "glm":
        body: dict[str, object] = {
            "model": "glm-4-flash",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        return (
            "https://open.bigmodel.cn/api/paas/v4/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body,
        )
    if engine == "deepseek":
        body = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        return (
            "https://api.deepseek.com/v1/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body,
        )
    if engine == "openai":
        body = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }
        return (
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            body,
        )
    if engine == "deepl":
        return (
            "https://api-free.deepl.com/v2/translate",
            {"Authorization": f"DeepL-Auth-Key {api_key}", "Content-Type": "application/json"},
            {"text": ["hello"], "target_lang": "DE"},
        )
    # 未知引擎 — 不校验
    return "", {}, {}


def validate_tts_model(engine: str, model_path: str) -> None:
    """校验 TTS 模型文件是否就绪。

    Edge-TTS（云端）跳过模型路径检查；CosyVoice 校验本地模型目录存在。

    Args:
        engine: TTS 引擎名称（cosyvoice/edge-tts）。
        model_path: 模型路径字符串。

    Raises:
        ValidationError: Cosyvoice 模型路径为空或不存在。
    """
    if engine == "edge-tts":
        return

    if engine == "cosyvoice":
        if not model_path:
            raise ValidationError(
                "未配置 CosyVoice 模型路径",
                stage="tts",
                suggestion="请在配置中指定 CosyVoice 模型目录",
            )
        p = Path(model_path)
        if not p.exists():
            raise ValidationError(
                f"CosyVoice 模型目录不存在: {model_path}",
                stage="tts",
                suggestion="请检查模型路径是否正确，或下载 CosyVoice 模型",
            )
        if not p.is_dir():
            raise ValidationError(
                f"CosyVoice 模型路径不是目录: {model_path}",
                stage="tts",
                suggestion="请确认模型路径指向包含模型文件的目录",
            )


def validate_video_format(video_path: Path) -> None:
    """校验视频文件格式是否支持。

    Args:
        video_path: 视频文件路径。

    Raises:
        ValidationError: 文件后缀不在允许列表中。
    """
    suffix = video_path.suffix.lower()
    if suffix not in _SUPPORTED_VIDEO_FORMATS:
        supported = "/".join(sorted(_SUPPORTED_VIDEO_FORMATS))
        raise ValidationError(
            f"不支持的视频格式: {video_path.suffix}",
            stage="video",
            suggestion=f"支持的视频格式: {supported}",
        )


def validate_video_duration(video_path: Path) -> None:
    """校验视频时长是否在限制内（默认 ≤2 小时，由 MAX_VIDEO_DURATION_SECONDS 控制）。

    通过 ffprobe 获取视频时长。

    Args:
        video_path: 视频文件路径。

    Raises:
        ValidationError: 视频时长超过限制或 ffprobe 执行失败。
    """
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise ValidationError(
            "无法获取视频时长",
            stage="video",
            suggestion="请确认 ffprobe 可用且视频文件有效",
        ) from e

    if result.returncode != 0 or not result.stdout.strip():
        raise ValidationError(
            "无法获取视频时长",
            stage="video",
            suggestion="请确认视频文件有效且未损坏",
        )

    try:
        duration = float(result.stdout.strip())
    except ValueError:
        raise ValidationError(
            f"无法解析视频时长: {result.stdout.strip()!r}",
            stage="video",
            suggestion="请确认视频文件有效且未损坏",
        )

    if duration <= 0:
        raise ValidationError(
            f"视频时长异常（{duration:.1f}s），文件可能已损坏",
            stage="video",
            suggestion="请检查视频文件是否完整，或尝试用 ffmpeg 重新封装",
        )

    if duration > MAX_VIDEO_DURATION_SECONDS:
        limit_display = format_duration_limit(MAX_VIDEO_DURATION_SECONDS)
        raise ValidationError(
            f"视频时长 {duration:.0f} 秒超过 {limit_display} 限制",
            stage="video",
            suggestion=f"请选择时长不超过 {limit_display} 的视频",
        )


def validate_memory(requirement_gb: float = DEFAULT_MEMORY_WARNING_GB) -> None:
    """校验可用内存是否满足模型加载需求。

    Args:
        requirement_gb: 最低需要的可用内存（GB）。

    Raises:
        ValidationError: 可用内存不足。
    """
    available = psutil.virtual_memory().available
    available_gb = available / (1024**3)
    if available < requirement_gb * (1024**3):
        raise ValidationError(
            f"可用内存不足: {available_gb:.1f}GB，建议至少 {requirement_gb:.0f}GB 可用",
            stage="memory",
            suggestion="请关闭其他应用释放内存，或使用快速预设（Edge-TTS + tiny 模型）",
        )


def validate_disk_space(video_path: Path, output_dir: Path) -> None:
    """校验目标磁盘可用空间是否足够容纳中间产物 + 最终合成视频。

    估算策略：视频大小 × 3（保守估计，覆盖 WAV 提取 + TTS 段音频 + 合成视频峰值）。
    通过 shutil.disk_usage 获取真实可用空间，跨平台一致（macOS/Linux/Windows）。

    Args:
        video_path: 视频文件路径，用于读取文件大小作为估算基准。
        output_dir: 输出目录（中间产物 .temp/ 和最终视频都写在这里）。

    Raises:
        ValidationError: 视频文件无法读取、输出目录不可访问、或可用空间不足。
    """
    try:
        video_size = video_path.stat().st_size
    except OSError as e:
        raise ValidationError(
            f"无法读取视频文件大小: {video_path}",
            stage="disk",
            suggestion="请确认视频文件未被移动或删除",
        ) from e

    required = video_size * _DISK_SPACE_ESTIMATE_MULTIPLIER

    try:
        usage = shutil.disk_usage(output_dir)
    except OSError as e:
        raise ValidationError(
            f"无法获取磁盘信息: {output_dir}",
            stage="disk",
            suggestion="请确认输出目录存在且可访问",
        ) from e

    if usage.free < required:
        free_mb = usage.free / (1024**2)
        required_mb = required / (1024**2)
        raise ValidationError(
            f"磁盘空间不足：预估需要 {required_mb:.0f}MB（视频大小 × "
            f"{_DISK_SPACE_ESTIMATE_MULTIPLIER}），当前可用 {free_mb:.0f}MB",
            stage="disk",
            suggestion="请清理磁盘空间或将输出目录改到容量更大的盘",
        )


class ValidationResult:
    """批量校验结果容器。"""

    def __init__(self, errors: list[ValidationError] | None = None) -> None:
        self.errors: list[ValidationError] = errors if errors is not None else []

    @property
    def is_valid(self) -> bool:
        """是否所有校验均通过。"""
        return len(self.errors) == 0


def validate_config_only(config: AppConfig) -> ValidationResult:
    """执行仅配置项校验（无视频），收集所有失败项。

    与 validate_all 不同，此函数跳过视频格式和时长校验，
    适用于用户尚未拖入视频时的即时反馈场景。

    Args:
        config: 应用配置（包含 ASR/翻译/TTS 子配置）。

    Returns:
        ValidationResult 包含所有失败的校验项。
    """
    errors: list[ValidationError] = []

    checks: list[tuple[str, tuple[object, ...]]] = [
        ("validate_ffmpeg", ()),
        ("validate_asr_model", (config.asr.model_path,)),
        ("validate_translation_api", (config.translation.engine, config.translation.api_key)),
        ("validate_tts_model", (config.tts.engine, config.tts.model_path)),
        ("validate_memory", (config.memory.warning_gb,)),
    ]

    for func_name, args in checks:
        try:
            func = globals()[func_name]
            func(*args)  # type: ignore[arg-type]
        except ValidationError as e:
            errors.append(e)

    return ValidationResult(errors)


def validate_all(config: AppConfig, video_path: Path, output_dir: Path) -> ValidationResult:
    errors: list[ValidationError] = []

    checks: list[tuple[str, tuple[object, ...]]] = [
        ("validate_ffmpeg", ()),
        ("validate_asr_model", (config.asr.model_path,)),
        ("validate_translation_api", (config.translation.engine, config.translation.api_key)),
        ("validate_tts_model", (config.tts.engine, config.tts.model_path)),
        ("validate_video_format", (video_path,)),
        ("validate_video_duration", (video_path,)),
        ("validate_disk_space", (video_path, output_dir)),
        ("validate_memory", (config.memory.warning_gb,)),
    ]

    for func_name, args in checks:
        try:
            func = globals()[func_name]
            func(*args)  # type: ignore[arg-type]
        except ValidationError as e:
            errors.append(e)

    return ValidationResult(errors)
