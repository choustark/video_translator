"""ChatTTSEngine 单元测试 — mock ChatTTS 库验证核心路径。

测试策略：chattts_engine.py 模块级 import ChatTTS/torch/torchaudio，
测试必须在 import 前注入 mock 模块到 sys.modules，并清除缓存的引擎模块。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.config import TTSConfig
from src.exceptions import PipelineError
from src.models import SubtitleSegment


def _make_segments(count: int, *, empty_last: bool = False) -> list[SubtitleSegment]:
    segs = [
        SubtitleSegment(
            index=i,
            start_time=i * 2.0,
            end_time=i * 2.0 + 1.5,
            source_text=f"hello {i}",
            translated_text=f"你好 {i}",
        )
        for i in range(count)
    ]
    if empty_last and segs:
        segs[-1].translated_text = ""
    return segs


class _FakeTensor:
    """模拟 torch.Tensor 的最小实现。"""

    def __init__(self, data: np.ndarray) -> None:
        self.data = data

    def unsqueeze(self, dim: int) -> _FakeTensor:
        return self


def _make_fake_torch() -> ModuleType:
    mod = ModuleType("torch")
    mod.from_numpy = lambda x: _FakeTensor(x)  # type: ignore[attr-defined]
    return mod


def _make_fake_torchaudio() -> ModuleType:
    mod = ModuleType("torchaudio")
    mod.save = MagicMock()  # type: ignore[attr-defined]
    return mod


def _make_fake_chattts() -> ModuleType:
    mod = ModuleType("ChatTTS")

    class FakeChat:
        class InferCodeParams:
            def __init__(self, **kwargs: object) -> None:
                pass

        def __init__(self) -> None:
            self._loaded = False

        def load(self, compile: bool = False) -> None:  # noqa: A002
            self._loaded = True

        def sample_random_speaker(self) -> str:
            return "fake_speaker"

        def infer(
            self,
            texts: list[str],
            params_infer_code: object | None = None,
        ) -> list[np.ndarray]:
            return [np.random.randn(24000).astype(np.float32)]

    mod.Chat = FakeChat  # type: ignore[attr-defined]
    return mod


@pytest.fixture()
def chattts_env(tmp_path: Path):
    """注入 mock 的 ChatTTS/torch/torchaudio 到 sys.modules，返回引擎实例。

    用法::

        def test_something(chattts_env):
            engine, tmp = chattts_env
            segments = _make_segments(2)
            result = engine.synthesize(segments, tmp)
    """
    saved = {}
    mocks = {
        "ChatTTS": _make_fake_chattts(),
        "torch": _make_fake_torch(),
        "torchaudio": _make_fake_torchaudio(),
    }
    # 清除可能缓存的引擎模块
    for key in ("src.tts.chattts_engine",):
        if key in sys.modules:
            saved[key] = sys.modules.pop(key)

    for name, mod in mocks.items():
        saved[name] = sys.modules.get(name)
        sys.modules[name] = mod

    try:
        from src.tts.chattts_engine import ChatTTSEngine

        config = TTSConfig(engine="chattts")
        engine = ChatTTSEngine(config)
        yield engine, tmp_path
    finally:
        for name, orig in saved.items():
            if orig is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = orig
        # 再次清除，防止残留
        sys.modules.pop("src.tts.chattts_engine", None)


def _write_stub_wav(path, *args, **kwargs) -> None:
    """写入一个最小的 WAV 文件（44 字节头 + 48000 字节数据 = 1s @24kHz/16bit）。

    兼容 torchaudio.save(path, tensor, sr) 调用签名。
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(b"\x00" * (44 + 48000))


# ── 正常合成 ──────────────────────────────────────────


class TestSynthesize:
    def test_synthesize_fills_audio_path_and_duration(self, chattts_env) -> None:
        engine, tmp_path = chattts_env

        with (
            patch("src.tts.chattts_engine.torchaudio") as mock_ta,
            patch("src.tts.chattts_engine.AudioSegment") as mock_as,
        ):
            mock_ta.save = _write_stub_wav
            mock_seg = MagicMock()
            mock_seg.__len__ = MagicMock(return_value=1000)
            mock_as.from_wav.return_value = mock_seg

            segments = _make_segments(2)
            result = engine.synthesize(segments, tmp_path)

        assert result[0].audio_path != Path()
        assert result[0].audio_duration == 1.0
        assert result[1].audio_path != Path()
        assert result[1].audio_duration == 1.0

    def test_skips_empty_text_segments(self, chattts_env) -> None:
        engine, tmp_path = chattts_env

        with (
            patch("src.tts.chattts_engine.torchaudio") as mock_ta,
            patch("src.tts.chattts_engine.AudioSegment") as mock_as,
        ):
            mock_ta.save = _write_stub_wav
            mock_seg = MagicMock()
            mock_seg.__len__ = MagicMock(return_value=500)
            mock_as.from_wav.return_value = mock_seg

            segments = _make_segments(3, empty_last=True)
            result = engine.synthesize(segments, tmp_path)

        assert result[2].audio_path == Path()
        assert result[2].audio_duration == 0.0

    def test_progress_callback(self, chattts_env) -> None:
        engine, tmp_path = chattts_env

        with (
            patch("src.tts.chattts_engine.torchaudio") as mock_ta,
            patch("src.tts.chattts_engine.AudioSegment") as mock_as,
        ):
            mock_ta.save = _write_stub_wav
            mock_seg = MagicMock()
            mock_seg.__len__ = MagicMock(return_value=800)
            mock_as.from_wav.return_value = mock_seg

            events: list[object] = []
            segments = _make_segments(2)
            engine.synthesize(segments, tmp_path, progress_callback=events.append)

        assert len(events) >= 2
        assert events[-1].progress == pytest.approx(1.0, abs=0.05)

    def test_empty_segments_returns_early(self, chattts_env) -> None:
        engine, tmp_path = chattts_env
        result = engine.synthesize([], tmp_path)
        assert result == []


# ── 推理失败 ──────────────────────────────────────────


class TestSynthesizeErrors:
    def test_infer_returns_empty_raises_pipeline_error(self, tmp_path: Path) -> None:
        fake = _make_fake_chattts()
        # 修改类方法让 infer 返回 [None]
        original_infer = fake.Chat.infer  # type: ignore[attr-defined]
        fake.Chat.infer = lambda self, texts, params_infer_code=None: [None]  # type: ignore[attr-defined]

        saved = {}
        for key in ("src.tts.chattts_engine", "ChatTTS", "torch", "torchaudio"):
            if key in sys.modules:
                saved[key] = sys.modules.pop(key)
        sys.modules["ChatTTS"] = fake
        sys.modules["torch"] = _make_fake_torch()
        sys.modules["torchaudio"] = _make_fake_torchaudio()

        try:
            from src.tts.chattts_engine import ChatTTSEngine

            config = TTSConfig(engine="chattts")
            engine = ChatTTSEngine(config)

            segments = _make_segments(1)
            with pytest.raises(PipelineError, match="ChatTTS 未返回音频"):
                engine.synthesize(segments, tmp_path)
        finally:
            for name, orig in saved.items():
                if orig is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = orig
            sys.modules.pop("src.tts.chattts_engine", None)

    def test_infer_exception_raises_pipeline_error(self, tmp_path: Path) -> None:
        fake = _make_fake_chattts()

        class BrokenChat(fake.Chat):  # type: ignore[attr-defined]
            def infer(self, texts, params_infer_code=None):
                raise RuntimeError("CUDA OOM")

        fake.Chat = BrokenChat  # type: ignore[attr-defined]

        saved = {}
        for key in ("src.tts.chattts_engine", "ChatTTS", "torch", "torchaudio"):
            if key in sys.modules:
                saved[key] = sys.modules.pop(key)
        sys.modules["ChatTTS"] = fake
        sys.modules["torch"] = _make_fake_torch()
        sys.modules["torchaudio"] = _make_fake_torchaudio()

        try:
            from src.tts.chattts_engine import ChatTTSEngine

            config = TTSConfig(engine="chattts")
            engine = ChatTTSEngine(config)

            segments = _make_segments(1)
            with pytest.raises(PipelineError, match="ChatTTS 合成失败"):
                engine.synthesize(segments, tmp_path)
        finally:
            for name, orig in saved.items():
                if orig is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = orig
            sys.modules.pop("src.tts.chattts_engine", None)


# ── import guard ──────────────────────────────────────


class TestImportGuard:
    def test_import_error_when_chattts_not_installed(self) -> None:
        saved = {}
        for key in ("src.tts.chattts_engine", "ChatTTS"):
            if key in sys.modules:
                saved[key] = sys.modules.pop(key)
        sys.modules["ChatTTS"] = None

        try:
            with pytest.raises(ImportError, match="ChatTTS"):
                import src.tts.chattts_engine as mod

                importlib.reload(mod)
        finally:
            sys.modules.pop("ChatTTS", None)
            sys.modules.pop("src.tts.chattts_engine", None)
            for name, orig in saved.items():
                if orig is not None:
                    sys.modules[name] = orig
