import os
import stat
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DOCKERIGNORE_PATH = PROJECT_ROOT / ".dockerignore"
DOCKERFILE_PATH = PROJECT_ROOT / "Dockerfile"
ENTRYPOINT_PATH = PROJECT_ROOT / "scripts" / "docker-entrypoint.sh"

# --- .dockerignore ---


class TestDockerignore:
    def test_dockerignore_exists(self) -> None:
        assert DOCKERIGNORE_PATH.is_file()

    @pytest.fixture
    def ignore_lines(self) -> set[str]:
        assert DOCKERIGNORE_PATH.exists(), ".dockerignore must exist"
        text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
        return {
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.startswith("#")
        }

    def test_excludes_models(self, ignore_lines: set[str]) -> None:
        assert "models/" in ignore_lines

    def test_excludes_output(self, ignore_lines: set[str]) -> None:
        assert "output/" in ignore_lines

    def test_excludes_logs(self, ignore_lines: set[str]) -> None:
        assert "logs/" in ignore_lines

    def test_excludes_venv(self, ignore_lines: set[str]) -> None:
        assert ".venv/" in ignore_lines

    def test_excludes_pycache(self, ignore_lines: set[str]) -> None:
        assert "__pycache__/" in ignore_lines

    def test_excludes_git(self, ignore_lines: set[str]) -> None:
        assert ".git/" in ignore_lines

    def test_excludes_bmad(self, ignore_lines: set[str]) -> None:
        assert "_bmad/" in ignore_lines

    def test_excludes_bmad_output(self, ignore_lines: set[str]) -> None:
        assert "_bmad-output/" in ignore_lines

    def test_excludes_claude(self, ignore_lines: set[str]) -> None:
        assert ".claude/" in ignore_lines

    def test_excludes_env(self, ignore_lines: set[str]) -> None:
        assert ".env" in ignore_lines

    def test_excludes_vscode(self, ignore_lines: set[str]) -> None:
        assert ".vscode/" in ignore_lines

    def test_excludes_idea(self, ignore_lines: set[str]) -> None:
        assert ".idea/" in ignore_lines

    def test_excludes_ds_store(self, ignore_lines: set[str]) -> None:
        assert ".DS_Store" in ignore_lines


# --- Dockerfile ---


class TestDockerfile:
    def test_dockerfile_exists(self) -> None:
        assert DOCKERFILE_PATH.is_file()

    @pytest.fixture
    def dockerfile_content(self) -> str:
        assert DOCKERFILE_PATH.exists(), "Dockerfile must exist"
        return DOCKERFILE_PATH.read_text(encoding="utf-8")

    def test_base_image_python(self, dockerfile_content: str) -> None:
        assert "FROM python:" in dockerfile_content

    def test_installs_ffmpeg(self, dockerfile_content: str) -> None:
        assert "ffmpeg" in dockerfile_content

    def test_uses_uv(self, dockerfile_content: str) -> None:
        assert "uv" in dockerfile_content

    def test_entrypoint_or_cmd(self, dockerfile_content: str) -> None:
        assert "ENTRYPOINT" in dockerfile_content or "CMD" in dockerfile_content

    def test_copies_pyproject(self, dockerfile_content: str) -> None:
        assert "pyproject.toml" in dockerfile_content

    def test_workdir_set(self, dockerfile_content: str) -> None:
        assert "WORKDIR" in dockerfile_content

    def test_docker_extra(self, dockerfile_content: str) -> None:
        assert "--extra docker" in dockerfile_content


# --- Entrypoint script ---


class TestEntrypoint:
    def test_entrypoint_exists(self) -> None:
        assert ENTRYPOINT_PATH.is_file()

    def test_entrypoint_is_executable(self) -> None:
        st = os.stat(ENTRYPOINT_PATH)
        is_exec = bool(st.st_mode & stat.S_IXUSR)
        assert is_exec, "docker-entrypoint.sh must be executable"

    @pytest.fixture
    def entrypoint_content(self) -> str:
        assert ENTRYPOINT_PATH.exists(), "entrypoint script must exist"
        return ENTRYPOINT_PATH.read_text(encoding="utf-8")

    def test_has_shebang(self, entrypoint_content: str) -> None:
        assert entrypoint_content.startswith(
            "#!/bin/bash"
        ) or entrypoint_content.startswith("#!/usr/bin/env bash")

    def test_creates_output_dir(self, entrypoint_content: str) -> None:
        assert "output" in entrypoint_content and "mkdir" in entrypoint_content

    def test_creates_logs_dir(self, entrypoint_content: str) -> None:
        assert "logs" in entrypoint_content and "mkdir" in entrypoint_content

    def test_executes_python(self, entrypoint_content: str) -> None:
        assert "python" in entrypoint_content or "exec" in entrypoint_content
