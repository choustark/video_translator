#!/usr/bin/env python3
"""模型下载脚本 — 将 ASR / TTS 模型从 HuggingFace 预下载到本地 models/ 目录。

平台兼容性：
  - macOS (Apple Silicon)：推荐 --asr mlx + --tts chattts
  - Windows / Linux：只能 --asr faster + --tts chattts（不支持 mlx-whisper）
  - 不确定选什么？用 --auto，脚本自动检测平台

用法：
    python scripts/download_models.py --auto             # 自动检测平台，下载推荐模型
    python scripts/download_models.py --all              # 下载全部（跳过确认，平台兼容警告）
    python scripts/download_models.py --asr mlx          # 仅 mlx-whisper（仅 macOS）
    python scripts/download_models.py --asr faster       # 仅 faster-whisper（跨平台）
    python scripts/download_models.py --tts chattts      # 仅 ChatTTS（跨平台）
    python scripts/download_models.py --list             # 列出可用模型 + 平台兼容标记

前置条件：
    pip install huggingface_hub[hf_transfer]

模型仓库（全部经过 dry-run 联网查证，2026-05-30）：
    mlx-community/whisper-large-v3-turbo  → models/asr/whisper-large-v3-turbo/
    mlx-community/whisper-medium          → models/asr/whisper-medium/
    mlx-community/whisper-tiny            → models/asr/whisper-tiny/
    Systran/faster-whisper-medium         → models/asr/faster-whisper-medium/
    Systran/faster-whisper-large-v3       → models/asr/faster-whisper-large-v3/
    2Noise/ChatTTS                        → models/tts/ChatTTS/
"""

from __future__ import annotations

import argparse
import logging
import platform
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_MODELS_DIR = _PROJECT_ROOT / "models"

# ── 平台检测 ─────────────────────────────────────────────────────────────

_IS_MACOS = platform.system() == "Darwin"
# macOS arm64 才能用 mlx-whisper（Apple Silicon 专用框架）
_IS_APPLE_SILICON = _IS_MACOS and platform.machine() == "arm64"


def _platform_label() -> str:
    """返回当前平台标识字符串。"""
    if _IS_APPLE_SILICON:
        return f"macOS Apple Silicon ({platform.machine()})"
    if _IS_MACOS:
        return f"macOS Intel ({platform.machine()}) — mlx-whisper 不可用，请用 faster-whisper"
    return f"{platform.system()} ({platform.machine()})"


# ── 模型清单 ─────────────────────────────────────────────────────────────

MLX_WHISPER_MODELS: dict[str, str] = {
    "whisper-large-v3-turbo": "mlx-community/whisper-large-v3-turbo",
    "whisper-medium": "mlx-community/whisper-medium",
    "whisper-tiny": "mlx-community/whisper-tiny",
}

FASTER_WHISPER_MODELS: dict[str, str] = {
    "faster-whisper-medium": "Systran/faster-whisper-medium",
    "faster-whisper-large-v3": "Systran/faster-whisper-large-v3",
}

CHATTTS_MODELS: dict[str, str] = {
    "ChatTTS": "2Noise/ChatTTS",
}

# 各平台推荐模型
_PLATFORM_DEFAULT: dict[str, list[str]] = {
    "macos-arm64": ["mlx-whisper", "chattts"],
    "other": ["faster-whisper", "chattts"],
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("download_models")


# ── 工具函数 ─────────────────────────────────────────────────────────────

def _check_huggingface_hub() -> None:
    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        logger.error("缺少 huggingface_hub，请安装：pip install huggingface_hub[hf_transfer]")
        sys.exit(1)


def _download_model(repo_id: str, local_dir: Path) -> bool:
    from huggingface_hub import snapshot_download

    name = local_dir.name
    logger.info("开始下载: %s → %s", repo_id, local_dir)

    try:
        local_dir.mkdir(parents=True, exist_ok=True)
        snapshot_download(
            repo_id=repo_id,
            local_dir=str(local_dir),
            max_workers=4,
        )
        logger.info("下载完成: %s", name)
        return True
    except Exception as e:
        logger.error("下载失败: %s — %s", name, e)
        return False


# ── 下载入口 ─────────────────────────────────────────────────────────────

def download_mlx_whisper(models: list[str] | None = None) -> dict[str, bool]:
    if not _IS_APPLE_SILICON:
        logger.warning("mlx-whisper 仅支持 Apple Silicon，当前平台: %s", _platform_label())
        logger.warning("请使用 --asr faster 下载 faster-whisper 模型")
        return {}
    results: dict[str, bool] = {}
    target = {k: v for k, v in MLX_WHISPER_MODELS.items() if models is None or k in models}
    for name, repo_id in target.items():
        local_dir = _MODELS_DIR / "asr" / name
        results[name] = _download_model(repo_id, local_dir)
    return results


def download_faster_whisper(models: list[str] | None = None) -> dict[str, bool]:
    results: dict[str, bool] = {}
    target = {k: v for k, v in FASTER_WHISPER_MODELS.items() if models is None or k in models}
    for name, repo_id in target.items():
        local_dir = _MODELS_DIR / "asr" / name
        results[name] = _download_model(repo_id, local_dir)
    return results


def download_chattts(models: list[str] | None = None) -> dict[str, bool]:
    results: dict[str, bool] = {}
    target = {k: v for k, v in CHATTTS_MODELS.items() if models is None or k in models}
    for name, repo_id in target.items():
        local_dir = _MODELS_DIR / "tts" / name
        results[name] = _download_model(repo_id, local_dir)
    return results


def download_auto() -> dict[str, bool]:
    """根据当前平台自动选择并下载推荐模型。"""
    print(f"检测到平台: {_platform_label()}")
    results: dict[str, bool] = {}

    if _IS_APPLE_SILICON:
        print("  → 推荐: mlx-whisper + ChatTTS\n")
        results.update(download_mlx_whisper())
    else:
        print("  → 推荐: faster-whisper + ChatTTS\n")
        results.update(download_faster_whisper())

    results.update(download_chattts())
    return results


# ── 输出 ─────────────────────────────────────────────────────────────────

def _print_summary(results: dict[str, bool]) -> None:
    success = sum(1 for v in results.values() if v)
    failed = sum(1 for v in results.values() if not v)
    print(f"\n{'='*50}")
    print(f"下载完成: {success} 成功, {failed} 失败")
    for name, ok in results.items():
        status = "✓" if ok else "✗"
        print(f"  {status} {name}")
    print(f"{'='*50}")


def _list_models() -> None:
    mlx_compat = "✓ 本机可用" if _IS_APPLE_SILICON else "✗ 仅 Apple Silicon"
    faster_compat = "✓ 本机可用"

    print(f"平台: {_platform_label()}")
    print()

    print(f"mlx-whisper 模型（MLX 格式）[{mlx_compat}]:")
    for name, repo_id in MLX_WHISPER_MODELS.items():
        local = _MODELS_DIR / "asr" / name
        exists = " [已存在]" if local.exists() and any(local.iterdir()) else ""
        print(f"  {name:35s} ← {repo_id}{exists}")

    print(f"\nfaster-whisper 模型（CTranslate2 格式）[{faster_compat}]:")
    for name, repo_id in FASTER_WHISPER_MODELS.items():
        local = _MODELS_DIR / "asr" / name
        exists = " [已存在]" if local.exists() and any(local.iterdir()) else ""
        print(f"  {name:35s} ← {repo_id}{exists}")

    print(f"\nChatTTS 模型 [{faster_compat}]:")
    for name, repo_id in CHATTTS_MODELS.items():
        local = _MODELS_DIR / "tts" / name
        exists = " [已存在]" if local.exists() and any(local.iterdir()) else ""
        print(f"  {name:35s} ← {repo_id}{exists}")

    print(f"\n所有模型下载到: {_MODELS_DIR}")
    print("CosyVoice 无法自动下载，请参考 docs/cosyvoice-deployment-guide.md")

    # ── 平台不兼容警告 ──
    if not _IS_APPLE_SILICON:
        print()
        print("─── 重要提醒 ───")
        print("当前不是 Apple Silicon Mac，mlx-whisper 模型无法使用。")
        print("请使用: python scripts/download_models.py --asr faster")


# ── CLI ──────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载 video_translator 所需的 AI 模型（自动检测平台兼容性）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python scripts/download_models.py --auto             # 自动检测平台，下载推荐模型
  python scripts/download_models.py --all              # 下载全部（不兼容模型会跳过）
  python scripts/download_models.py --asr mlx          # 仅 mlx-whisper（仅 macOS）
  python scripts/download_models.py --asr faster       # 仅 faster-whisper（跨平台）
  python scripts/download_models.py --tts chattts      # 仅 ChatTTS（跨平台）
  python scripts/download_models.py --list             # 列出模型 + 平台兼容标记
        """,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--auto", action="store_true", help="自动检测平台，下载推荐模型")
    group.add_argument("--all", action="store_true", help="下载全部兼容模型（跳过确认）")
    group.add_argument("--asr", choices=["mlx", "faster"], help="下载 ASR 模型")
    group.add_argument("--tts", choices=["chattts"], help="下载 TTS 模型")
    group.add_argument("--list", action="store_true", help="列出可用模型 + 平台兼容标记")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _check_huggingface_hub()

    if args.list:
        _list_models()
        return

    results: dict[str, bool] = {}

    if args.asr == "mlx":
        results.update(download_mlx_whisper())
    elif args.asr == "faster":
        results.update(download_faster_whisper())
    elif args.tts == "chattts":
        results.update(download_chattts())
    elif args.all:
        # 下载全部兼容模型，不兼容的跳过有 warning
        results.update(download_mlx_whisper())
        results.update(download_faster_whisper())
        results.update(download_chattts())
    elif args.auto:
        results.update(download_auto())
    else:
        # 交互模式
        _list_models()
        print()
        if _IS_APPLE_SILICON:
            try:
                response = input("下载推荐模型（mlx-whisper + ChatTTS）？[Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                return
            if response in ("n", "no"):
                print("已取消")
                return
            results.update(download_mlx_whisper())
        else:
            try:
                response = input("下载推荐模型（faster-whisper + ChatTTS）？[Y/n] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\n已取消")
                return
            if response in ("n", "no"):
                print("已取消")
                return
            results.update(download_faster_whisper())
        results.update(download_chattts())

    if results:
        _print_summary(results)
    else:
        print("未选择任何模型，使用 --help 查看用法")


if __name__ == "__main__":
    main()
