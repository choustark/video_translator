"""D6-DEV-1 回归测试：_run_in_thread 未捕获异常路径必须遵守契约不变量 2。

验证 emit 顺序：stage_failed 必须先于 pipeline_finished，确保 PipelineProgress
端 _has_failure 标志被正确设置，不会误显示"全部完成"。

参考 docs/pipeline-signals-contract.md §2.4 与 §三 不变量 2。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ASRConfig, AppConfig, TranslationConfig, TTSConfig
from src.pipeline import Pipeline
from src.signals import PipelineSignals


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        asr=ASRConfig(engine="mlx-whisper", model_path="/asr"),
        translation=TranslationConfig(engine="glm"),
        tts=TTSConfig(engine="cosyvoice", speed=1.0),
    )


def test_run_in_thread_uncaught_exception_emits_stage_failed_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D6-DEV-1：未捕获异常路径 emit 顺序验证。

    Given：mock process() 抛 RuntimeError（非 PipelineError，模拟 _run_in_thread 兜底路径）
    When：调用 _run_in_thread()
    Then：stage_failed 在 pipeline_finished 之前 emit，且 stage_name 为 _current_stage 初始值
    """
    pipeline = Pipeline(_make_config(tmp_path), PipelineSignals())

    # 记录所有 emit 的顺序
    emitted: list[tuple] = []
    pipeline.signals.stage_failed.connect(
        lambda name, err: emitted.append(("stage_failed", name, err))
    )
    pipeline.signals.pipeline_finished.connect(lambda: emitted.append(("pipeline_finished",)))

    # 让 process() 抛非 PipelineError 的异常
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("模拟未捕获异常")

    monkeypatch.setattr(pipeline, "process", boom)

    video = tmp_path / "input.mp4"
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    pipeline._run_in_thread(video, output_dir)

    # 不变量 2：stage_failed 必须先于 pipeline_finished
    assert len(emitted) == 2
    assert emitted[0][0] == "stage_failed"
    assert emitted[1][0] == "pipeline_finished"

    # stage_name 应为 _current_stage 初始值（STAGE_NAMES[0] = "音频提取"）
    assert emitted[0][1] == "音频提取"
    assert "模拟未捕获异常" in emitted[0][2]
