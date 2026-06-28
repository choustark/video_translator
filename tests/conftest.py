import os
from pathlib import Path

# Linux headless CI 上 QApplication 默认尝试 xcb 平台插件连 X server，
# 无显示环境会 SIGABRT（exit 134）。offscreen 是 Qt 内置的"无显示"QPA 后端，
# 让 QWidget 能在不连 X server 的情况下创建。
# 用 setdefault 不覆盖本地显式设置（本地开发者想用 xcb 仍可手动 export）。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from src.config import ENV_PATH


@pytest.fixture(autouse=True)
def _clean_env() -> None:
    """每个测试前清理真实 .env 文件，防止 api_key 测试间污染。"""
    if ENV_PATH.exists():
        ENV_PATH.unlink()


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.yaml"
