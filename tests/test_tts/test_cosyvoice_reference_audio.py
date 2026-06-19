"""D60 CosyVoice 声音克隆 — 引擎层 reference_audio 处理测试。

D60 hotfix #3（2026-06-19）后，主进程不再把用户原始参考音频路径直接透传给 worker，
而是先用 ffmpeg 转成 16kHz mono WAV 临时文件，再把临时路径写入 stdin JSON。
"""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from src.config import TTSConfig
from src.models import SubtitleSegment
from src.tts.cosyvoice_engine import CosyVoiceEngine


def _make_config(reference_audio: str = "") -> TTSConfig:
    return TTSConfig(
        engine="cosyvoice",
        model_path="/models/cosyvoice",
        reference_audio=reference_audio,
        conda_python_path="/opt/conda/bin/python",
        cosyvoice_source_path="/opt/cosyvoice",
    )


def _make_segments() -> list[SubtitleSegment]:
    return [
        SubtitleSegment(
            index=0,
            start_time=0.0,
            end_time=2.0,
            source_text="hello",
            translated_text="你好",
        )
    ]


def _build_fake_process(stdin_captured: dict[str, Any]) -> MagicMock:
    """构造一个 fake Popen 对象，记录 stdin 并模拟 worker 立即完成。"""

    process = MagicMock()
    process.returncode = 0

    real_stdin = io.BytesIO()

    class _Stdin:
        def write(self, data: bytes) -> int:
            captured = json.loads(data.decode("utf-8"))
            stdin_captured.update(captured)
            real_stdin.write(data)
            return len(data)

        def close(self) -> None:
            pass

    process.stdin = _Stdin()
    process.stdout = io.BytesIO(
        b'{"type": "result", "index": 0, "duration": 1.5, "status": "ok"}\n'
        b'{"type": "done", "total": 1, "success_count": 1}\n'
    )
    process.stderr = io.BytesIO()
    process.wait = MagicMock(return_value=0)
    return process


class TestReferenceAudioPassThrough:
    def test_synthesize_passes_converted_wav_path_to_worker_stdin(self, tmp_path: Path) -> None:
        """AC6 测试 1：reference_audio 非空 → 主进程 ffmpeg 转码后写入 stdin。

        用户原始路径（如 mp3）不应直接出现在 stdin；stdin 里的应是
        temp_dir/reference_audio.wav 这个 ffmpeg 转换后的 wav 路径。
        """
        # 构造一个真实存在的"源音频"文件，让 _prepare_reference_audio 走 ffmpeg 路径
        src_mp3 = tmp_path / "user_ref.mp3"
        src_mp3.write_bytes(b"fake mp3")
        config = _make_config(reference_audio=str(src_mp3))
        engine = CosyVoiceEngine(config)
        captured: dict[str, Any] = {}
        fake_process = _build_fake_process(captured)

        completed = subprocess.CompletedProcess(args=[], returncode=0, stderr=b"")
        with (
            patch.object(
                engine,
                "_resolve_paths",
                return_value=(Path("/opt/conda/bin/python"), Path("/opt/cosyvoice")),
            ),
            patch("src.tts.cosyvoice_engine.subprocess.Popen", return_value=fake_process),
            patch("src.tts.cosyvoice_engine.subprocess.run", return_value=completed),
            patch.object(CosyVoiceEngine, "_apply_results"),
        ):
            engine.synthesize(_make_segments(), tmp_path)

        # stdin 里的 reference_audio 应是转码后的 wav 路径，不是原始 mp3 路径
        expected_wav = str(tmp_path / "reference_audio.wav")
        assert captured.get("reference_audio") == expected_wav
        # 原始 mp3 路径不应出现在 stdin
        assert captured.get("reference_audio") != str(src_mp3)

    def test_synthesize_empty_reference_audio_backward_compatible(self, tmp_path: Path) -> None:
        """AC6 测试 2：reference_audio="" → 字段仍存在但为空，向后兼容。"""
        config = _make_config(reference_audio="")
        engine = CosyVoiceEngine(config)
        captured: dict[str, Any] = {}
        fake_process = _build_fake_process(captured)

        with (
            patch.object(
                engine,
                "_resolve_paths",
                return_value=(Path("/opt/conda/bin/python"), Path("/opt/cosyvoice")),
            ),
            patch("src.tts.cosyvoice_engine.subprocess.Popen", return_value=fake_process),
            patch.object(CosyVoiceEngine, "_apply_results"),
        ):
            engine.synthesize(_make_segments(), tmp_path)

        assert "reference_audio" in captured
        assert captured["reference_audio"] == ""
