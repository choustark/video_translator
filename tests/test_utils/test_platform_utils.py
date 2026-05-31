from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.utils.platform_utils import (
    IS_LINUX,
    IS_MACOS,
    IS_WINDOWS,
    get_ffmpeg_install_hint,
    get_process_group_kwargs,
    open_with_default_app,
)


class TestPlatformConstants:
    """模块级常量测试 — 当前测试环境为 macOS。"""

    def test_macos_constant_matches_platform(self) -> None:
        import sys

        assert IS_MACOS == (sys.platform == "darwin")

    def test_windows_constant_matches_platform(self) -> None:
        import sys

        assert IS_WINDOWS == (sys.platform == "win32")

    def test_linux_constant_matches_platform(self) -> None:
        import sys

        assert IS_LINUX == (sys.platform == "linux")

    def test_at_most_one_platform_true(self) -> None:
        """IS_MACOS/IS_WINDOWS/IS_LINUX 不可能同时为 True。"""
        true_count = sum([IS_MACOS, IS_WINDOWS, IS_LINUX])
        assert true_count <= 1


class TestOpenWithDefaultApp:
    def test_macos_calls_open_command(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_MACOS", True),
            patch("src.utils.platform_utils.IS_WINDOWS", False),
            patch("src.utils.platform_utils.subprocess") as mock_subprocess,
        ):
            open_with_default_app("/some/path")
            mock_subprocess.run.assert_called_once_with(
                ["open", "/some/path"], check=False,
            )

    def test_windows_calls_startfile(self) -> None:
        mock_os = MagicMock()
        mock_os.startfile = MagicMock()
        with (
            patch("src.utils.platform_utils.IS_MACOS", False),
            patch("src.utils.platform_utils.IS_WINDOWS", True),
            patch("src.utils.platform_utils.os", mock_os),
        ):
            open_with_default_app("/some/path")
            mock_os.startfile.assert_called_once_with("/some/path")

    def test_linux_calls_xdg_open(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_MACOS", False),
            patch("src.utils.platform_utils.IS_WINDOWS", False),
            patch("src.utils.platform_utils.subprocess") as mock_subprocess,
        ):
            open_with_default_app("/some/path")
            mock_subprocess.run.assert_called_once_with(
                ["xdg-open", "/some/path"], check=False,
            )

    def test_accepts_path_object(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_MACOS", True),
            patch("src.utils.platform_utils.IS_WINDOWS", False),
            patch("src.utils.platform_utils.subprocess") as mock_subprocess,
        ):
            open_with_default_app(Path("/some/path"))
            mock_subprocess.run.assert_called_once_with(
                ["open", "/some/path"], check=False,
            )


class TestGetFfmpegInstallHint:
    def test_macos_returns_brew(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_MACOS", True),
            patch("src.utils.platform_utils.IS_WINDOWS", False),
        ):
            hint = get_ffmpeg_install_hint()
            assert "brew" in hint

    def test_windows_returns_winget(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_MACOS", False),
            patch("src.utils.platform_utils.IS_WINDOWS", True),
        ):
            hint = get_ffmpeg_install_hint()
            assert "winget" in hint

    def test_linux_returns_apt(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_MACOS", False),
            patch("src.utils.platform_utils.IS_WINDOWS", False),
        ):
            hint = get_ffmpeg_install_hint()
            assert "apt" in hint


class TestGetProcessGroupKwargs:
    def test_posix_returns_start_new_session(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_WINDOWS", False),
        ):
            kwargs = get_process_group_kwargs()
            assert kwargs == {"start_new_session": True}

    def test_windows_returns_creationflags(self) -> None:
        with (
            patch("src.utils.platform_utils.IS_WINDOWS", True),
        ):
            kwargs = get_process_group_kwargs()
            assert kwargs == {"creationflags": 0x00000200}
