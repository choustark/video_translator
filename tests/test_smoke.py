import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "src",
        "src.asr",
        "src.translation",
        "src.tts",
        "src.composer",
        "src.gui",
        "src.utils",
    ],
)
def test_module_importable(module_name: str) -> None:
    importlib.import_module(module_name)
