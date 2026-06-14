"""CosyVoice 引擎 — 高质量本地中文语音合成。

CosyVoice 是一个开源的高质量 TTS 引擎（Apache 2.0 License），支持多语言、多说话人。
通过 subprocess 桥接独立 conda 环境（Python 3.10）运行，与项目 Python 3.13 隔离。
支持语速参数控制，输出 24kHz WAV 音频。

GitHub: https://github.com/FunAudioLLM/CosyVoice
License: Apache 2.0 License

GitHub: https://github.com/FunAudioLLM/CosyVoice
License: Apache 2.0 License
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import IO, Callable

from src.exceptions import PipelineError
from src.models import ProgressEvent, SubtitleSegment
from src.tts.base import TTSEngine
from src.utils.platform_utils import get_process_group_kwargs

logger = logging.getLogger("video_translator")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_WORKER_SCRIPT = _PROJECT_ROOT / "scripts" / "cosyvoice_worker.py"

_VOICE_MAP: dict[str, str] = {
    "default": "中文女",
}


class CosyVoiceEngine(TTSEngine):
    def synthesize(
        self,
        segments: list[SubtitleSegment],
        temp_dir: Path,
        progress_callback: Callable[[ProgressEvent], None] | None = None,
        process_registry: list[subprocess.Popen[bytes]] | None = None,
    ) -> list[SubtitleSegment]:
        python_path, source_path = self._resolve_paths()
        speaker = _VOICE_MAP.get(self.config.voice, self.config.voice)
        segments_dir = temp_dir / "segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        task_segments: list[dict[str, object]] = [
            {
                "index": seg.index,
                "text": seg.translated_text,
                "output_path": str(segments_dir / f"{seg.index:04d}.wav"),
            }
            for seg in segments
            if seg.translated_text.strip()
        ]
        input_data: dict[str, object] = {
            "model_path": self.config.model_path,
            "speaker": speaker,
            "speed": self.config.speed,
            "reference_audio": self.config.reference_audio,
            "segments": task_segments,
        }

        total = len(task_segments)
        if total == 0:
            return segments

        env = self._build_env(source_path)
        process = subprocess.Popen(
            [str(python_path), str(_WORKER_SCRIPT)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            **get_process_group_kwargs(),
        )
        if process_registry is not None:
            process_registry.append(process)

        stdin = process.stdin
        assert stdin is not None
        stdin.write(json.dumps(input_data, ensure_ascii=False).encode("utf-8"))
        stdin.close()

        stderr_chunks: list[bytes] = []
        stderr_thread = threading.Thread(
            target=self._drain_stderr,
            args=(process.stderr, stderr_chunks),
            daemon=True,
        )
        stderr_thread.start()

        results = self._read_results(process, total, progress_callback)

        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            logger.warning("CosyVoice worker 超时（30秒），强制终止")
            try:
                process.kill()
                process.wait(timeout=5)
            except OSError:
                pass
            if process_registry is not None and process in process_registry:
                process_registry.remove(process)
            raise ImportError("CosyVoice worker 超时（30秒），已强制终止")

        stderr_thread.join(timeout=5)

        if process.returncode != 0:
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace")
            raise ImportError(
                f"CosyVoice worker 异常退出 (code={process.returncode}): {stderr_text[:500]}"
            )

        self._apply_results(results, segments, segments_dir)

        if process_registry is not None and process in process_registry:
            process_registry.remove(process)

        if progress_callback:
            progress_callback(
                ProgressEvent(
                    stage="TTS",
                    progress=1.0,
                    message=f"合成完成 {total}/{total}",
                )
            )

        return segments

    def _resolve_paths(self) -> tuple[Path, Path]:
        conda = self.config.conda_python_path
        source = self.config.cosyvoice_source_path
        python_path = Path(conda) if conda else None
        source_path = Path(source) if source else None

        if not python_path or not python_path.is_file():
            raise ImportError(
                f"conda Python 未找到: {python_path}。请在 config.yaml 中设置 tts.conda_python_path"
            )
        if not source_path or not source_path.is_dir():
            raise ImportError(
                f"CosyVoice 源码目录未找到: {source_path}。"
                "请在 config.yaml 中设置 tts.cosyvoice_source_path"
            )
        if not _WORKER_SCRIPT.is_file():
            raise ImportError(f"Worker 脚本未找到: {_WORKER_SCRIPT}")

        return python_path, source_path

    @staticmethod
    def _build_env(source_path: Path) -> dict[str, str]:
        env = os.environ.copy()
        pythonpath_parts = [
            str(source_path / "third_party" / "Matcha-TTS"),
            str(source_path),
        ]
        existing = env.get("PYTHONPATH", "")
        if existing:
            pythonpath_parts.append(existing)
        env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
        env["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    @staticmethod
    def _drain_stderr(stderr: IO[bytes], chunks: list[bytes]) -> None:
        try:
            for line in stderr:
                chunks.append(line)
                text = line.decode("utf-8", errors="replace").rstrip()
                if text:
                    logger.info("CosyVoice worker | %s", text)
        except (ValueError, OSError):
            pass

    @staticmethod
    def _read_results(
        process: subprocess.Popen,
        total: int,
        progress_callback: Callable[[ProgressEvent], None] | None,
    ) -> dict[int, dict]:
        results: dict[int, dict] = {}
        stdout = process.stdout
        assert stdout is not None  # PIPE 保证非 None
        for line in stdout:
            try:
                data = json.loads(line.decode("utf-8").strip())
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue

            msg_type = data.get("type")
            if msg_type == "result":
                idx = data["index"]
                results[idx] = data
                if data.get("status") == "error":
                    logger.warning("TTS | 段 %d 失败 | %s", idx, data.get("error", ""))
                if progress_callback:
                    done = len(results)
                    progress_callback(
                        ProgressEvent(
                            stage="TTS",
                            progress=done / total,
                            message=f"正在合成 {done}/{total}",
                        )
                    )
            elif msg_type == "error":
                raise ImportError(f"CosyVoice worker 错误: {data.get('message', '')}")
        return results

    @staticmethod
    def _apply_results(
        results: dict[int, dict],
        segments: list[SubtitleSegment],
        segments_dir: Path,
    ) -> None:
        errors: list[str] = []
        for seg in segments:
            if not seg.translated_text.strip():
                continue
            result = results.get(seg.index)
            if result is None:
                errors.append(f"段 {seg.index} 无合成结果")
                continue
            if result["status"] == "error":
                errors.append(f"段 {seg.index}: {result.get('error', '未知错误')}")
                continue
            if result["status"] == "ok":
                audio_path = segments_dir / f"{seg.index:04d}.wav"
                seg.audio_path = audio_path
                seg.audio_duration = result["duration"]

        if errors:
            raise PipelineError(
                f"CosyVoice 部分段合成失败: {'; '.join(errors[:5])}",
                stage="TTS",
                suggestion="将自动降级到 Edge-TTS",
            )
