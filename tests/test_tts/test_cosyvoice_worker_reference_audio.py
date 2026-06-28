"""D60 CosyVoice 声音克隆 — worker 脚本 cross_lingual 分支测试。

worker 运行在 conda Python 3.10 环境，主进程无法直接 import cosyvoice。
测试通过 monkeypatch sys.modules 注入 mock 模块，模拟两种推理路径。

D60 hotfix #3（2026-06-19）：worker 直接把参考音频路径字符串透传给
inference_cross_lingual，不再做 tensor 归一化（CosyVoice 内部 load_wav 自带）。
"""

from __future__ import annotations

import io
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# torch / torchaudio 是 CosyVoice worker 的运行时依赖，主 venv 不装（CosyVoice 走 conda 子进程）。
# 用 importorskip 让"无 torch 环境"（Linux/Windows CI）在 collection 阶段直接 SKIP 整个文件，
# 而不是 ModuleNotFoundError 中断整个 pytest（exit code 2）。
# 注意：CI 的 -k "not cosyvoice" 是执行阶段的过滤器，无法阻止 collection 阶段的 import 失败。
torch = pytest.importorskip("torch")
torchaudio = pytest.importorskip("torchaudio")


def _install_cosyvoice_mocks(
    monkeypatch: pytest.MonkeyPatch,
    inference_sft: MagicMock | None = None,
    inference_cross_lingual: MagicMock | None = None,
) -> tuple[types.ModuleType, types.ModuleType]:
    """向 sys.modules 注入 mock 的 cosyvoice 和 torchaudio 模块。

    worker 通过 `import torchaudio` 和 `from cosyvoice.cli.cosyvoice import CosyVoice` 引用，
    因此需要构造对应的子模块结构。

    D60 hotfix #3 后 worker 直接传路径字符串给 inference_cross_lingual，
    不再对 prompt_wav 做 tensor 处理。torchaudio.save 仍需 mock 避免写盘。
    """
    cosyvoice_pkg = types.ModuleType("cosyvoice")
    cli_pkg = types.ModuleType("cosyvoice.cli")
    cosyvoice_mod = types.ModuleType("cosyvoice.cli.cosyvoice")

    mock_instance = MagicMock()
    mock_instance.inference_sft = inference_sft or MagicMock(return_value=iter([]))
    mock_instance.inference_cross_lingual = inference_cross_lingual or MagicMock(
        return_value=iter([])
    )
    mock_instance.list_available_spks = MagicMock(return_value=["中文女"])
    cosyvoice_mod.CosyVoice = MagicMock(return_value=mock_instance)

    cosyvoice_pkg.cli = cli_pkg
    cli_pkg.cosyvoice = cosyvoice_mod

    # worker 不再调 torchaudio.load（路径透传），但推理成功仍走 torchaudio.save
    torchaudio.save = MagicMock()  # type: ignore[method-assign]

    monkeypatch.setitem(sys.modules, "cosyvoice", cosyvoice_pkg)
    monkeypatch.setitem(sys.modules, "cosyvoice.cli", cli_pkg)
    monkeypatch.setitem(sys.modules, "cosyvoice.cli.cosyvoice", cosyvoice_mod)

    return cosyvoice_mod, torchaudio


def _run_worker(stdin_data: str) -> tuple[list[dict], int]:
    """运行 worker.main()，返回（stdout 输出的 NDJSON 解析列表，进程退出码）。"""
    # 加载 worker 模块（独立路径，避免被项目根的 src/ 影响）
    import importlib.util

    worker_path = Path(__file__).resolve().parents[2] / "scripts" / "cosyvoice_worker.py"
    spec = importlib.util.spec_from_file_location("cosyvoice_worker_test", worker_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    # 捕获 stdout / exit code
    captured_stdout = io.StringIO()
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(stdin_data)
    sys.stdout = captured_stdout
    exit_code = 0
    try:
        try:
            spec.loader.exec_module(module)
            module.main()
        except SystemExit as e:
            exit_code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdin = old_stdin
        sys.stdout = old_stdout

    lines = [json.loads(line) for line in captured_stdout.getvalue().splitlines() if line.strip()]
    return lines, exit_code


import json  # noqa: E402


class TestWorkerReferenceAudioBranch:
    def test_worker_uses_cross_lingual_when_reference_audio_provided(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC6 测试 3：reference_audio 字段非空 → inference_cross_lingual 被调用。"""
        ref_wav = tmp_path / "ref.wav"
        ref_wav.write_bytes(b"fake")

        sft_mock = MagicMock(return_value=iter([]))
        cross_mock = MagicMock(
            return_value=iter([{"tts_speech": torch.randn(1, 22050, dtype=torch.float32)}])
        )
        cosyvoice_mod, _ = _install_cosyvoice_mocks(
            monkeypatch,
            inference_sft=sft_mock,
            inference_cross_lingual=cross_mock,
        )

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

        lines, exit_code = _run_worker(stdin)

        assert exit_code == 0
        assert cross_mock.called, "inference_cross_lingual 应被调用"
        assert not sft_mock.called, "inference_sft 不应被调用"
        # D60 hotfix #3：路径字符串应原样透传给 inference_cross_lingual 的第二个位置参数
        prompt_wav_arg = cross_mock.call_args.args[1]
        assert prompt_wav_arg == str(ref_wav), "应透传路径字符串，不是 tensor"
        # 验证结果
        assert any(line.get("type") == "done" and line.get("success_count") == 1 for line in lines)

    def test_worker_uses_sft_when_reference_audio_empty(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC6 测试 4：reference_audio="" → 走默认 SFT 路径（回归测试）。"""
        sft_mock = MagicMock(
            return_value=iter([{"tts_speech": torch.randn(1, 22050, dtype=torch.float32)}])
        )
        cross_mock = MagicMock(return_value=iter([]))
        _install_cosyvoice_mocks(
            monkeypatch,
            inference_sft=sft_mock,
            inference_cross_lingual=cross_mock,
        )

        out_wav = tmp_path / "out.wav"
        stdin = json.dumps(
            {
                "model_path": "/model",
                "speaker": "中文女",
                "speed": 1.0,
                "reference_audio": "",
                "segments": [{"index": 0, "text": "你好", "output_path": str(out_wav)}],
            }
        )

        lines, exit_code = _run_worker(stdin)

        assert exit_code == 0
        assert sft_mock.called, "inference_sft 应被调用"
        assert not cross_mock.called, "inference_cross_lingual 不应被调用"

    def test_worker_handles_missing_reference_audio_gracefully(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC6 测试 5：reference_audio 指向不存在文件 → 输出 error 并退出。"""
        _install_cosyvoice_mocks(monkeypatch)

        out_wav = tmp_path / "out.wav"
        stdin = json.dumps(
            {
                "model_path": "/model",
                "speaker": "中文女",
                "speed": 1.0,
                "reference_audio": str(tmp_path / "nonexistent.wav"),
                "segments": [{"index": 0, "text": "你好", "output_path": str(out_wav)}],
            }
        )

        lines, exit_code = _run_worker(stdin)

        assert exit_code == 1
        assert any(line.get("type") == "error" for line in lines)
