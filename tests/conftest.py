from pathlib import Path

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
