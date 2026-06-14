"""D60 CosyVoice 声音克隆 — 引擎层 reference_audio 透传测试。

验证 CosyVoiceEngine.synthesize 将 config.reference_audio 透传到 worker stdin JSON。
"""

from __future__ import annotations

import io
import json
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
    def test_synthesize_passes_reference_audio_to_worker_stdin(self, tmp_path: Path) -> None:
        """AC6 测试 1：reference_audio 非空时，stdin JSON 包含该字段且值正确。"""
        config = _make_config(reference_audio="/abs/path/ref.wav")
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

        assert captured.get("reference_audio") == "/abs/path/ref.wav"

    def test_synthesize_empty_reference_audio_backward_compatible(self, tmp_path: Path) -> None:
        """AC6 测试 2：reference_audio="" 时 stdin JSON 仍含字段（值为空），向后兼容。"""
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
