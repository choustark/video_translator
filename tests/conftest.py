from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "config.yaml"
