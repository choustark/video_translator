from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from src.exceptions import PipelineError
from src.tts.cosyvoice_engine import CosyVoiceEngine


def _make_engine(reference_audio: str = "") -> CosyVoiceEngine:
    """构造一个最小可用的 CosyVoiceEngine，仅用于 _prepare_reference_audio 测试。"""
    from src.config import TTSConfig

    config = TTSConfig(
        engine="cosyvoice",
        model_path="/fake/model",
        conda_python_path="/fake/python",
        cosyvoice_source_path="/fake/source",
        reference_audio=reference_audio,
    )
    return CosyVoiceEngine(config)


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


class TestPrepareReferenceAudio:
    """D60 hotfix #3 — _prepare_reference_audio 用 ffmpeg 把任意格式 → 16kHz mono WAV。"""

    def test_empty_reference_returns_empty_string(self, tmp_path: Path) -> None:
        """未配置参考音频 → 返回空串，不触发 ffmpeg。"""
        engine = _make_engine(reference_audio="")
        with patch("subprocess.run") as mock_run:
            assert engine._prepare_reference_audio(tmp_path) == ""
            mock_run.assert_not_called()

    def test_missing_reference_raises_pipeline_error(self, tmp_path: Path) -> None:
        """参考音频文件不存在 → PipelineError。"""
        engine = _make_engine(reference_audio=str(tmp_path / "nonexistent.mp3"))
        with pytest.raises(PipelineError, match="参考音频文件不存在"):
            engine._prepare_reference_audio(tmp_path)

    def test_reuses_existing_converted_wav(self, tmp_path: Path) -> None:
        """temp_dir 下已有 reference_audio.wav → 直接复用，不重复转码。"""
        engine = _make_engine(reference_audio="/fake/source.mp3")
        # 用户源文件不需要存在 —— 复用分支在源文件存在性检查之后
        # 但源文件不存在会先报错，所以这里要构造源文件存在的场景
        src = tmp_path / "source.mp3"
        src.write_bytes(b"fake mp3")
        engine.config.reference_audio = str(src)

        out_wav = tmp_path / "reference_audio.wav"
        out_wav.write_bytes(b"fake wav header")

        with patch("subprocess.run") as mock_run:
            result = engine._prepare_reference_audio(tmp_path)
            assert result == str(out_wav)
            mock_run.assert_not_called()

    def test_invokes_ffmpeg_with_16khz_mono_pcm_args(self, tmp_path: Path) -> None:
        """转码调用 ffmpeg 时命令行应包含 -ar 16000 -ac 1 pcm_s16le。"""
        src = tmp_path / "source.mp3"
        src.write_bytes(b"fake mp3")
        engine = _make_engine(reference_audio=str(src))

        completed = subprocess.CompletedProcess(args=[], returncode=0, stderr=b"")
        with patch("subprocess.run", return_value=completed) as mock_run:
            result = engine._prepare_reference_audio(tmp_path)

        assert result == str(tmp_path / "reference_audio.wav")
        mock_run.assert_called_once()
        cmd = mock_run.call_args.args[0]
        assert cmd[0] == "ffmpeg"
        assert "-ar" in cmd and "16000" in cmd
        assert "-ac" in cmd and "1" in cmd
        assert "pcm_s16le" in cmd

    def test_ffmpeg_failure_raises_pipeline_error(self, tmp_path: Path) -> None:
        """ffmpeg 返回非零 → PipelineError。"""
        src = tmp_path / "source.mp3"
        src.write_bytes(b"corrupt")
        engine = _make_engine(reference_audio=str(src))

        completed = subprocess.CompletedProcess(args=[], returncode=1, stderr=b"Invalid data found")
        with patch("subprocess.run", return_value=completed):
            with pytest.raises(PipelineError, match="参考音频转码失败"):
                engine._prepare_reference_audio(tmp_path)

    def test_ffmpeg_not_found_raises_pipeline_error(self, tmp_path: Path) -> None:
        """ffmpeg 二进制不存在 → FileNotFoundError 转 PipelineError。"""
        src = tmp_path / "source.mp3"
        src.write_bytes(b"fake")
        engine = _make_engine(reference_audio=str(src))

        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(PipelineError, match="ffmpeg 未找到"):
                engine._prepare_reference_audio(tmp_path)
