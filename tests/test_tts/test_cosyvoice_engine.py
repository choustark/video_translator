from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from src.tts.cosyvoice_engine import CosyVoiceEngine


class TestBuildEnv:
    def test_pythonpath_uses_pathsep(self) -> None:
        env = CosyVoiceEngine._build_env(Path("/fake/source"))
        parts = env["PYTHONPATH"].split(os.pathsep)
        assert len(parts) >= 2
        assert str(Path("/fake/source")) in parts

    def test_pythonpath_preserves_existing(self) -> None:
        with patch.dict(os.environ, {"PYTHONPATH": "/existing/path"}):
            env = CosyVoiceEngine._build_env(Path("/fake/source"))
            assert "/existing/path" in env["PYTHONPATH"]


class TestProcessGroupKwargs:
    def test_get_process_group_kwargs_imported(self) -> None:
        import src.tts.cosyvoice_engine as mod
        assert hasattr(mod, "get_process_group_kwargs")

    def test_popen_uses_platform_kwargs(self) -> None:
        from src.utils.platform_utils import get_process_group_kwargs

        kwargs = get_process_group_kwargs()
        assert "start_new_session" in kwargs or "creationflags" in kwargs

    def test_macos_uses_start_new_session(self) -> None:
        from src.utils.platform_utils import IS_MACOS, get_process_group_kwargs

        if not IS_MACOS:
            import pytest
            pytest.skip("not macOS")
        kwargs = get_process_group_kwargs()
        assert kwargs == {"start_new_session": True}

    def test_creationflags_is_correct_constant(self) -> None:
        from src.utils.platform_utils import get_process_group_kwargs

        kwargs = get_process_group_kwargs()
        if "creationflags" in kwargs:
            assert kwargs["creationflags"] == subprocess.CREATE_NEW_PROCESS_GROUP
