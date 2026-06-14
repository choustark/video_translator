"""D60 hotfix — prompt_wav 归一化测试。

worker 在加载参考音频后强制做三件事：
1. 多声道 → 单声道（取均值）
2. 非 16kHz → 重采样到 16kHz
3. MPS/CUDA tensor → CPU

这三步缺一不可，否则 CosyVoice cross_lingual 静音返回，
torchaudio.save 报 "Invalid file: tensor([[0., 0., ...]])"。

测试通过 importlib 动态加载 worker 模块，注入 mock cosyvoice，并让 torchaudio
走主环境真实模块（torch 2.11 + torchaudio 2.11 都已随 mlx-whisper 安装）。
"""

from __future__ import annotations

import io
import json
import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import torch
import torchaudio


def _load_worker_module(monkeypatch: pytest.MonkeyPatch):
    """动态加载 scripts/cosyvoice_worker.py，注入 mock 的 cosyvoice。

    torchaudio 走主环境真实模块，便于用真 tensor 验证归一化逻辑。
    """
    cosyvoice_pkg = types.ModuleType("cosyvoice")
    cli_pkg = types.ModuleType("cosyvoice.cli")
    cosyvoice_mod = types.ModuleType("cosyvoice.cli.cosyvoice")

    mock_instance = MagicMock()
    mock_instance.inference_cross_lingual = MagicMock(return_value=iter([]))
    mock_instance.inference_sft = MagicMock(return_value=iter([]))
    mock_instance.list_available_spks = MagicMock(return_value=["中文女"])
    cosyvoice_mod.CosyVoice = MagicMock(return_value=mock_instance)

    cosyvoice_pkg.cli = cli_pkg
    cli_pkg.cosyvoice = cosyvoice_mod

    monkeypatch.setitem(sys.modules, "cosyvoice", cosyvoice_pkg)
    monkeypatch.setitem(sys.modules, "cosyvoice.cli", cli_pkg)
    monkeypatch.setitem(sys.modules, "cosyvoice.cli.cosyvoice", cosyvoice_mod)

    worker_path = Path(__file__).resolve().parents[2] / "scripts" / "cosyvoice_worker.py"
    spec = spec_from_file_location("cosyvoice_worker_norm_test", worker_path)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, mock_instance


class TestNormalizePromptWavUnit:
    """_normalize_prompt_wav 单元测试。"""

    def test_stereo_downmixes_to_mono(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module, _ = _load_worker_module(monkeypatch)

        stereo = torch.stack(
            [
                torch.sin(torch.arange(16000, dtype=torch.float32)),
                torch.cos(torch.arange(16000, dtype=torch.float32)),
            ]
        )
        out, sr = module._normalize_prompt_wav(stereo, 16000, torchaudio)

        assert sr == 16000
        assert out.dim() == 2
        assert out.shape[0] == 1, "立体声应被降混到 (1, N)"
        expected = (stereo[0] + stereo[1]) / 2
        assert torch.allclose(out[0], expected)

    def test_resamples_non_16khz(self, monkeypatch: pytest.MonkeyPatch) -> None:
        module, _ = _load_worker_module(monkeypatch)

        mono_48k = torch.randn(1, 48000, dtype=torch.float32)
        out, sr = module._normalize_prompt_wav(mono_48k, 48000, torchaudio)

        assert sr == 16000
        # 48k → 16k 下采样，样本数应为 1/3
        assert out.shape[-1] == 16000

    def test_mono_16khz_passes_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """16kHz mono 输入应原样返回，不触发重采样。"""
        module, _ = _load_worker_module(monkeypatch)

        mono_16k = torch.randn(1, 16000, dtype=torch.float32)
        out, sr = module._normalize_prompt_wav(mono_16k, 16000, torchaudio)

        assert sr == 16000
        assert torch.equal(out, mono_16k)

    def test_mps_tensor_moved_to_cpu(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """MPS 设备的 tensor 应被搬到 CPU（避免 torchaudio.save 失败）。"""
        module, _ = _load_worker_module(monkeypatch)

        if not torch.backends.mps.is_available():
            pytest.skip("MPS 不可用，跳过")
        mps_tensor = torch.randn(1, 16000, device="mps", dtype=torch.float32)
        out, _ = module._normalize_prompt_wav(mps_tensor, 16000, torchaudio)

        assert out.device.type == "cpu"

    def test_stereo_non_16khz_combined(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """立体声 48kHz 输入应同时降混 + 重采样。"""
        module, _ = _load_worker_module(monkeypatch)

        stereo_48k = torch.randn(2, 48000, dtype=torch.float32)
        out, sr = module._normalize_prompt_wav(stereo_48k, 48000, torchaudio)

        assert sr == 16000
        assert out.shape[0] == 1
        assert out.shape[-1] == 16000


class TestWorkerNormalizesPromptWav:
    """worker main() 端到端：验证 reference_audio 经过归一化后再传给 inference_cross_lingual。"""

    def test_worker_normalizes_stereo_48khz_before_cross_lingual(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        module, mock_instance = _load_worker_module(monkeypatch)

        # 模拟合成成功返回 (1, 22050) tensor
        mock_instance.inference_cross_lingual.return_value = iter(
            [{"tts_speech": torch.randn(1, 22050, dtype=torch.float32)}]
        )

        # 把 worker 内的 torchaudio.save 替换为 noop，避免写盘
        torchaudio.save = MagicMock()  # type: ignore[method-assign]

        ref_wav = tmp_path / "ref.wav"
        ref_wav.write_bytes(b"fake")

        # 模拟 torchaudio.load 返回 stereo 48kHz tensor
        stereo_48k = torch.randn(2, 48000, dtype=torch.float32)
        torchaudio.load = MagicMock(return_value=(stereo_48k, 48000))  # type: ignore[method-assign]

        out_wav = tmp_path / "out.wav"
        stdin = json.dumps(
            {
                "model_path": "/model",
                "speaker": "中文女",
                "speed": 1.0,
                "reference_audio": str(ref_wav),
                "segments": [{"index": 0, "text": "你好", "output_path": str(out_wav)}],
            }
        )

        captured_stdout = io.StringIO()
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO(stdin)
        sys.stdout = captured_stdout
        exit_code = 0
        try:
            try:
                module.main()
            except SystemExit as e:
                exit_code = e.code if isinstance(e.code, int) else 1
        finally:
            sys.stdin = old_stdin
            sys.stdout = old_stdout

        assert exit_code == 0
        mock_instance.inference_cross_lingual.assert_called_once()
        # 第二个位置参数是 prompt_wav，必须是 mono 16kHz CPU tensor
        call_args = mock_instance.inference_cross_lingual.call_args
        prompt_wav_arg = call_args.args[1]
        assert isinstance(prompt_wav_arg, torch.Tensor)
        assert prompt_wav_arg.dim() == 2
        assert prompt_wav_arg.shape[0] == 1, "传给 cross_lingual 的应是单声道"
        assert prompt_wav_arg.shape[-1] == 16000, "应是 16kHz（48k → 16k 下采样后）"
        assert prompt_wav_arg.device.type == "cpu"

        lines = [
            json.loads(line) for line in captured_stdout.getvalue().splitlines() if line.strip()
        ]
        assert any(line.get("type") == "done" and line.get("success_count") == 1 for line in lines)
