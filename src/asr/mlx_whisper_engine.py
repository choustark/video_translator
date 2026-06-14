"""MLX-Whisper 引擎 — Apple Silicon 优化的 Whisper ASR。

MLX-Whisper 是 Whisper 模型的 Apple Silicon 优化实现（MIT License）。
利用 MPS/Metal 加速，支持 M 系列 GPU，提供本地高质量语音识别。
OOM 时可能直接 segfault，加载前必须用 psutil 预检可用内存。

GitHub: https://github.com/ml-explore/mlx-examples/tree/main/whisper
License: MIT License

GitHub: https://github.com/ml-explore/mlx-whisper
License: MIT License
"""

from __future__ import annotations

import gc
import logging
import subprocess
import sys
import threading
import time
from typing import Callable

from src.asr._helpers import (
    _apply_proper_noun_replacements,
    _build_initial_prompt,
    _build_proper_nouns_list,
    _check_memory,
    _merge_short_segments,
)
from src.asr.base import ASREngine
from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment

logger = logging.getLogger("video_translator")

# 策略 A（D22）所需的常量
# _MLX_WHISPER_RTF_ESTIMATE：large-v3-turbo 在 Apple Silicon M5 上的保守 RTF 估值。
#   RTF = 真实转录耗时 / 音频时长；M5 + large-v3-turbo 实测约 0.25-0.4，取上限。
#   用于将"已耗时秒数"换算成进度百分比，给用户实时反馈。
_MLX_WHISPER_RTF_ESTIMATE = 0.4

# _PROGRESS_INTERVAL_SECONDS：辅助线程每隔多少秒回调一次 progress_callback。
#   2 秒是平衡：太频繁会拖累 UI 线程；太疏会让用户以为卡死。
#   测试通过 patch 此值为 0.1 加速。
_PROGRESS_INTERVAL_SECONDS = 2.0

# 进度上限（转录期间）：避免提前接近 1.0 后又突然回落，给用户"快好了"的错觉。
#   真正的 1.0 在转录完成后由 transcribe() 主流程强制发送。
_PROGRESS_DURING_TRANSCRIPTION_CAP = 0.95


class MLXWhisperEngine(ASREngine):
    """基于 mlx-whisper 的 ASR 引擎，针对 Apple Silicon MPS/Metal 加速。"""

    def transcribe(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
    ) -> list[SubtitleSegment]:
        self._check_memory(self.memory_warning_gb)

        try:
            import mlx_whisper  # type: ignore[import-untyped]
        except ImportError as e:
            raise PipelineError(
                "mlx-whisper 未安装",
                stage="ASR",
                suggestion="请运行 uv add mlx-whisper",
            ) from e

        all_nouns = _build_proper_nouns_list(user_nouns=self.config.proper_nouns)
        initial_prompt = _build_initial_prompt(all_nouns)

        logger.info("ASR | 开始 | audio=%s, model=%s", audio_path, self.config.model_path)

        # 启动周期性进度线程（D22）：mlx_whisper.transcribe 是单次阻塞调用，
        # 无流式回调入口，因此用辅助线程在转录期间周期性估算进度。
        progress_thread, stop_event = self._start_progress_thread(audio_path, progress_callback)

        try:
            result = mlx_whisper.transcribe(
                str(audio_path),
                path_or_hf_repo=self.config.model_path,
                language=self.config.language,
                word_timestamps=True,
                verbose=False,
                initial_prompt=initial_prompt,
            )
        except Exception as e:
            raise PipelineError(
                f"ASR 转录失败: {e}",
                stage="ASR",
                suggestion="请确认模型路径有效且音频格式正确",
            ) from e
        finally:
            # 不论成功失败，都要停止进度线程，避免线程泄露
            stop_event.set()
            if progress_thread is not None and progress_thread.is_alive():
                progress_thread.join(timeout=_PROGRESS_INTERVAL_SECONDS * 2)

        raw_segments = result.get("segments", [])
        segments: list[SubtitleSegment] = []
        for seg in raw_segments:
            text = seg.get("text", "").strip()
            if not text:
                continue
            start = seg.get("start")
            end = seg.get("end")
            if start is None or end is None:
                continue
            segments.append(
                SubtitleSegment(
                    index=len(segments),
                    start_time=start,
                    end_time=end,
                    source_text=text,
                )
            )

        segments = _apply_proper_noun_replacements(segments, all_nouns)
        segments = _merge_short_segments(segments)

        logger.info("ASR | 完成 | segments=%d", len(segments))

        # 转录完成后强制发送 100% 进度事件（D22）
        self._emit_completion(segments, progress_callback)

        # 主动释放 ASR 模型内存：删除原始结果 + 清 Python GC + 清 MLX Metal 缓存
        del result
        self._release_mlx_memory()

        return segments

    def _start_progress_thread(
        self,
        audio_path: str,
        progress_callback: Callable[[ProgressEvent], None] | None,
    ) -> tuple[threading.Thread | None, threading.Event]:
        """启动周期性进度估算线程。

        mlx_whisper.transcribe 没有流式回调，本线程在转录期间周期性
        调用 progress_callback，基于"已耗时秒数 / 预估总耗时"估算进度。

        返回 (thread, stop_event)；当回调为 None 时返回 (None, dummy_event)，
        让主流程统一用 stop_event.set() 而无需 None 判断。
        """
        # dummy event：callback 为 None 时也返回一个已置位的 event，让 join 跳过
        if progress_callback is None:
            dummy = threading.Event()
            dummy.set()
            return None, dummy

        stop_event = threading.Event()
        audio_duration = self._get_audio_duration(audio_path)
        start_time = time.monotonic()

        # 预估总耗时 = 音频时长 × RTF；若拿不到时长则用 0.0 触发降级（仅显示 elapsed）
        estimated_total = max(audio_duration * _MLX_WHISPER_RTF_ESTIMATE, 1.0)

        def _loop() -> None:
            while not stop_event.wait(_PROGRESS_INTERVAL_SECONDS):
                elapsed = time.monotonic() - start_time
                # 降级路径：拿不到音频时长时，elapsed/1.0 仍能给一个递增反馈
                ratio = elapsed / estimated_total
                progress = min(ratio, _PROGRESS_DURING_TRANSCRIPTION_CAP)
                # 避免发出 0% 这种无意义事件（首次 wait 至少 _PROGRESS_INTERVAL_SECONDS 后才到这里）
                if progress <= 0.0:
                    continue
                try:
                    progress_callback(
                        ProgressEvent(
                            stage="ASR",
                            progress=progress,
                            message=f"正在识别语音…（{elapsed:.0f}s）",
                        )
                    )
                except Exception:
                    logger.error("ASR | 进度回调异常（忽略，不阻断转录）", exc_info=True)

        thread = threading.Thread(target=_loop, daemon=True, name="mlx-asr-progress")
        thread.start()
        return thread, stop_event

    @staticmethod
    def _emit_completion(
        segments: list[SubtitleSegment],
        callback: Callable[[ProgressEvent], None] | None,
    ) -> None:
        """转录完成后发送 progress=1.0 的最终事件。

        即使 segments 为空（极罕见：整段音频识别失败）也发送完成事件，
        让 UI 能正确推进到下一阶段而不是永远停在 95%。
        """
        if callback is None:
            return
        callback(
            ProgressEvent(
                stage="ASR",
                progress=1.0,
                message=f"已识别 {len(segments)} 段",
            )
        )

    def _get_audio_duration(self, audio_path: str) -> float:
        """通过 ffprobe 获取音频时长（秒），失败时返回 0.0 降级。

        失败原因可能：ffprobe 未安装、文件损坏、超时。本方法是 best-effort，
        失败时进度估算降级为 elapsed/1.0，仍能给用户反馈。
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                timeout=10,
                check=True,
                text=True,
            )
            return float(result.stdout.strip())
        except Exception:
            logger.debug("ASR | ffprobe 获取音频时长失败，进度估算降级", exc_info=True)
            return 0.0

    def _release_mlx_memory(self) -> None:
        """释放 MLX Metal 缓存，归还 GPU 内存。best-effort，不阻断管线。"""
        gc.collect()

        mx = sys.modules.get("mlx.core")
        if mx is None:
            logger.debug("ASR | 内存释放 | mlx.core 未加载，跳过 Metal 缓存清理")
            return

        try:
            mx.synchronize()
            mx.clear_cache()
            logger.info(
                "ASR | 内存释放 | active=%.0fMB cache=%.0fMB",
                mx.get_active_memory() / 1024 / 1024,
                mx.get_cache_memory() / 1024 / 1024,
            )
        except Exception:
            logger.debug("ASR | 内存释放 | MLX 缓存清理异常（可忽略）", exc_info=True)

    def _check_memory(self, requirement_gb: float = 6.0) -> None:
        _check_memory(requirement_gb)
