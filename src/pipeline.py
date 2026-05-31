from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from src.config import AppConfig
from src.exceptions import PipelineError
from src.models import PipelineResult, StageState, StageStatus, SubtitleSegment
from src.signals import PipelineSignals
from src.utils.platform_utils import get_ffmpeg_install_hint

logger = logging.getLogger("video_translator")

STAGE_NAMES = ["音频提取", "ASR", "翻译", "TTS", "语速自适应", "合成"]

_TIME_RE = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
_EXTRACT_AUDIO_TIMEOUT = 60


class Pipeline:
    """六阶段翻译管线编排器，在后台线程中执行。"""

    def __init__(self, config: AppConfig, signals: PipelineSignals) -> None:
        self.config = config.model_copy(deep=True)
        self.signals = signals
        self.states: dict[str, StageState] = {name: StageState(name) for name in STAGE_NAMES}
        self._current_stage: str = STAGE_NAMES[0]
        self._tts_ready_event = threading.Event()
        self._abort_requested = threading.Event()
        self._temp_dir: Path | None = None
        self._active_processes: list[subprocess.Popen[bytes]] = []

    def start(self, video_path: Path, output_dir: Path) -> None:
        """在后台守护线程中启动管线。"""
        thread = threading.Thread(
            target=self._run_in_thread,
            args=(video_path, output_dir),
            daemon=True,
        )
        thread.start()

    def _run_in_thread(self, video_path: Path, output_dir: Path) -> None:
        try:
            self.process(video_path, output_dir)
        except Exception:
            logger.exception("管线 | 未捕获异常")
            self.signals.pipeline_finished.emit()

    def abort(self) -> None:
        self._abort_requested.set()

        # 终止所有已注册的子进程（CosyVoice worker 等）
        for proc in self._active_processes:
            try:
                proc.terminate()
            except OSError:
                pass
        for proc in self._active_processes:
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=2)
                except OSError:
                    pass
            except OSError:
                pass
        self._active_processes.clear()

        # 清理临时目录
        temp = self._temp_dir
        if temp and temp.exists():
            try:
                shutil.rmtree(temp)
                logger.info("临时目录 | abort 清理 | path=%s", temp)
            except OSError:
                pass

    def process(self, video_path: Path, output_dir: Path) -> PipelineResult:
        """主编排方法：六阶段顺序执行。"""
        temp_dir: Path | None = None
        try:
            temp_dir = self._create_temp_dir(output_dir, video_path)
            self._temp_dir = temp_dir

            # 阶段 1: 音频提取（本 Story 实际实现）
            self._start_stage("音频提取")
            audio_path = self._extract_audio(video_path, temp_dir)
            self._complete_stage("音频提取")

            # 阶段 2-6: 占位实现，后续 Story 逐个替换
            self._start_stage("ASR")
            segments = self._run_asr(audio_path)
            self._complete_stage("ASR")

            self._start_stage("翻译")
            segments = self._run_translation(segments)
            self._complete_stage("翻译")

            self._start_stage("TTS")
            segments = self._run_tts(segments, temp_dir)
            self._complete_stage("TTS")

            self._start_stage("语速自适应")
            segments = self._run_alignment(segments, temp_dir)
            self._complete_stage("语速自适应")

            self._start_stage("合成")
            self._compose(video_path, segments, temp_dir, output_dir)
            self._complete_stage("合成")

            self._cleanup_temp(temp_dir)

            result = PipelineResult(
                video_path=video_path,
                output_dir=output_dir,
                audio_path=audio_path,
            )
            self.signals.pipeline_finished.emit()
            return result

        except PipelineError as e:
            self._fail_stage(e.stage, str(e))
            result = PipelineResult(
                video_path=video_path,
                output_dir=output_dir,
                success=False,
                error=str(e),
            )
            self.signals.pipeline_finished.emit()
            return result
        except Exception as e:
            self._fail_stage(self._current_stage, str(e))
            result = PipelineResult(
                video_path=video_path,
                output_dir=output_dir,
                success=False,
                error=str(e),
            )
            self.signals.pipeline_finished.emit()
            return result

    # ── 临时目录管理 ──────────────────────────────────────────

    def _create_temp_dir(self, output_dir: Path, video_path: Path) -> Path:
        """创建 output/.temp/{video_hash}/ 临时目录。"""
        raw = f"{video_path.name}_{video_path.stat().st_size}".encode()
        video_hash = hashlib.md5(raw).hexdigest()[:8]
        temp_dir = output_dir / ".temp" / video_hash
        temp_dir.mkdir(parents=True, exist_ok=True)
        logger.info("临时目录 | 创建 | path=%s", temp_dir)
        return temp_dir

    def _cleanup_temp(self, temp_dir: Path) -> None:
        """管线成功完成后删除临时目录。"""
        try:
            shutil.rmtree(temp_dir)
            logger.info("临时目录 | 清理 | path=%s", temp_dir)
        except OSError:
            logger.warning("临时目录 | 清理失败 | path=%s", temp_dir)

    # ── 阶段状态管理 ──────────────────────────────────────────

    def _start_stage(self, name: str) -> None:
        if self._abort_requested.is_set():
            raise PipelineError("用户中止", stage=name, suggestion="")
        self._current_stage = name
        state = self.states[name]
        state.status = StageStatus.RUNNING
        state.start_time = time.monotonic()
        state.progress = 0.0
        self.signals.stage_started.emit(name)
        logger.info("%s | START", name)

    def _complete_stage(self, name: str) -> None:
        state = self.states[name]
        state.status = StageStatus.COMPLETED
        state.end_time = time.monotonic()
        state.progress = 1.0
        duration = state.duration or 0.0
        self.signals.stage_completed.emit(name, duration)
        logger.info("%s | DONE | duration=%.1fs", name, duration)

    def _fail_stage(self, name: str, error: str) -> None:
        state = self.states[name]
        state.status = StageStatus.FAILED
        state.end_time = time.monotonic()
        state.error = error
        self.signals.stage_failed.emit(name, error)
        logger.error("%s | ERROR | msg=%s", name, error)

    def _check_abort(self) -> None:
        """检查是否已请求中止，如果是则抛出 PipelineError 中断当前阶段。"""
        if self._abort_requested.is_set():
            raise PipelineError("用户中止", stage=self._current_stage, suggestion="")

    # ── 阶段 1: 音频提取 ────────────────────────────────────

    @staticmethod
    def _parse_ffmpeg_time(line: str) -> float | None:
        """解析 ffmpeg stderr 中的 time=HH:MM:SS.ms 为秒数。"""
        m = _TIME_RE.search(line)
        if not m:
            return None
        hours, minutes, seconds = int(m.group(1)), int(m.group(2)), float(m.group(3))
        return hours * 3600 + minutes * 60 + seconds

    def _get_video_duration_safe(self, video_path: Path) -> float:
        """获取视频总时长，失败时返回 0（无进度模式）。"""
        try:
            from src.composer.ffmpeg_wrapper import FFmpegWrapper
            return FFmpegWrapper().get_video_duration(video_path)
        except Exception:
            logger.warning("音频提取 | 无法获取视频时长，进度将不可用")
            return 0.0

    def _read_ffmpeg_progress(
        self, proc: subprocess.Popen[bytes], duration: float,
    ) -> list[str]:
        """逐行读取 ffmpeg stderr，解析进度并 emit 信号。返回 stderr 行供错误报告。"""
        start = time.monotonic()
        stderr = proc.stderr
        if stderr is None:
            proc.wait(timeout=_EXTRACT_AUDIO_TIMEOUT)
            return []

        lines: list[str] = []
        for raw_line in stderr:
            if time.monotonic() - start > _EXTRACT_AUDIO_TIMEOUT:
                proc.terminate()
                proc.wait(timeout=5)
                raise PipelineError(
                    "音频提取超时（60秒）",
                    stage="音频提取",
                    suggestion="请确认视频文件不是过大或损坏",
                )

            self._check_abort()

            line = raw_line.decode("utf-8", errors="replace")
            lines.append(line)

            current = self._parse_ffmpeg_time(line)
            if current is not None and duration > 0:
                progress = min(current / duration, 1.0)
                self.signals.stage_progress.emit("音频提取", progress)

        proc.wait(timeout=5)
        return lines

    def _extract_audio(self, video_path: Path, temp_dir: Path) -> Path:
        """通过 ffmpeg 从视频提取 WAV 音频（16kHz 单声道 PCM）。"""
        output_path = temp_dir / "audio.wav"
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            "-y",
            str(output_path),
        ]

        duration = self._get_video_duration_safe(video_path)

        try:
            proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
            )
        except FileNotFoundError as e:
            raise PipelineError(
                "ffmpeg 未找到",
                stage="音频提取",
                suggestion=f"请安装 ffmpeg: {get_ffmpeg_install_hint()}",
            ) from e

        self._active_processes.append(proc)
        try:
            stderr_lines = self._read_ffmpeg_progress(proc, duration)
        finally:
            if proc in self._active_processes:
                self._active_processes.remove(proc)

        if proc.returncode != 0:
            stderr_tail = "".join(stderr_lines)[-200:]
            raise PipelineError(
                f"音频提取失败: {stderr_tail}",
                stage="音频提取",
                suggestion="请确认视频文件有效且 ffmpeg 已安装",
            )

        logger.info("音频提取 | output=%s", output_path)
        return output_path

    # ── 占位阶段（后续 Story 实现） ───────────────────────────

    def _run_asr(self, audio_path: Path) -> list[SubtitleSegment]:
        """ASR 语音识别。"""
        from src.asr import create_asr_engine
        from src.models import ProgressEvent

        engine = create_asr_engine(self.config.asr)
        engine.memory_warning_gb = self.config.memory.warning_gb

        def progress_callback(event: ProgressEvent) -> None:
            self._check_abort()
            self.signals.stage_progress.emit(event.stage, event.progress)

        preload_thread = threading.Thread(
            target=self._preload_check_tts, daemon=True,
        )
        preload_thread.start()

        segments = engine.transcribe(str(audio_path), progress_callback)

        full_text = " ".join(seg.source_text for seg in segments)
        if full_text:
            self.signals.transcript_updated.emit(full_text)

        return segments

    def _preload_check_tts(self) -> None:
        """检查 TTS 模型文件就绪性（轻量 I/O）。"""
        try:
            tts_path = Path(self.config.tts.model_path)
            if tts_path.exists():
                logger.info("预加载 | TTS 模型文件就绪 | path=%s", tts_path)
            else:
                logger.warning("预加载 | TTS 模型文件未找到 | path=%s", tts_path)
        except Exception:
            logger.exception("预加载 | TTS 检查异常")
        finally:
            self._tts_ready_event.set()

    def _run_translation(self, segments: list[SubtitleSegment]) -> list[SubtitleSegment]:
        """文本翻译 — 调用翻译 API 引擎。"""
        from src.models import ProgressEvent
        from src.translation import create_translation_provider

        provider = create_translation_provider(self.config.translation)

        def progress_callback(event: ProgressEvent) -> None:
            self._check_abort()
            self.signals.stage_progress.emit(event.stage, event.progress)

        segments = provider.translate(segments, progress_callback)

        bilingual_lines: list[str] = []
        for seg in segments:
            if seg.source_text and seg.translated_text:
                bilingual_lines.append(f"[EN] {seg.source_text}")
                bilingual_lines.append(f"[中] {seg.translated_text}")
        if bilingual_lines:
            self.signals.transcript_updated.emit("\n".join(bilingual_lines))

        return segments

    _DEGRADATION_CHAIN: dict[str, str | None] = {
        "cosyvoice": "chattts",
        "chattts": "edge-tts",
        "edge-tts": None,
    }

    def _run_tts(self, segments: list[SubtitleSegment], temp_dir: Path) -> list[SubtitleSegment]:
        """TTS 语音合成 — 调用 TTS 引擎，支持三级降级链。

        降级顺序：CosyVoice → ChatTTS → Edge-TTS。
        已尝试过的引擎不会被重复尝试，避免循环降级。
        """
        from src.config import TTSConfig
        from src.models import ProgressEvent
        from src.tts import create_tts_engine

        if not self._tts_ready_event.wait(timeout=30):
            raise PipelineError(
                "TTS 预加载超时（30秒）",
                stage="TTS",
                suggestion="请检查 TTS 模型路径配置或磁盘 I/O 状态",
            )

        def progress_callback(event: ProgressEvent) -> None:
            self._check_abort()
            self.signals.stage_progress.emit(event.stage, event.progress)

        engine_name: str | None = self.config.tts.engine
        tried: set[str] = set()
        errors: list[str] = []

        while engine_name is not None:
            if engine_name in tried:
                break
            tried.add(engine_name)

            try:
                if engine_name == self.config.tts.engine:
                    tts_config = self.config.tts
                else:
                    tts_config = TTSConfig(
                        engine=engine_name, speed=self.config.tts.speed,
                    )
                engine = create_tts_engine(tts_config)
                return engine.synthesize(
                    segments, temp_dir, progress_callback,
                    process_registry=self._active_processes,
                )
            except (PipelineError, MemoryError, RuntimeError, ImportError) as e:
                fallback = self._DEGRADATION_CHAIN.get(engine_name)
                degraded_msg = str(e) or type(e).__name__
                errors.append(f"{engine_name}: {degraded_msg}")

                if fallback is not None:
                    logger.warning(
                        'TTS | DEGRADED | %s → %s | msg="%s"',
                        engine_name, fallback, degraded_msg,
                    )
                    self.signals.tts_degraded.emit(engine_name, fallback)
                    engine_name = fallback
                else:
                    break

        raise PipelineError(
            f"TTS 所有引擎均失败 — {'; '.join(errors)}",
            stage="TTS",
            suggestion="请检查网络连接、模型路径，或尝试重新运行",
        )

    def _run_alignment(
        self, segments: list[SubtitleSegment], temp_dir: Path,
    ) -> list[SubtitleSegment]:
        """语速自适应对齐 — ffmpeg atempo + 静音填充。"""
        from src.composer.speed_adapter import SpeedAdapter
        from src.models import ProgressEvent

        adapter = SpeedAdapter()

        def progress_callback(event: ProgressEvent) -> None:
            self._check_abort()
            self.signals.stage_progress.emit(event.stage, event.progress)

        segments = adapter.align(segments, temp_dir, progress_callback)
        return segments

    def _compose(
        self, video_path: Path, segments: list[SubtitleSegment],
        temp_dir: Path, output_dir: Path,
    ) -> Path:
        from src.composer.ffmpeg_wrapper import FFmpegWrapper
        from src.composer.subtitle_generator import SubtitleGenerator

        generator = SubtitleGenerator()
        wrapper = FFmpegWrapper()
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = video_path.stem

        self._calc_actual_timestamps(segments)

        srt_path = temp_dir / "subtitles.srt"
        generator.generate_srt(segments, srt_path)
        srt_output = output_dir / f"{stem}.srt"
        srt_output.write_text(srt_path.read_text(encoding="utf-8"), encoding="utf-8")
        self.signals.stage_progress.emit("合成", 0.33)
        logger.info("合成 | SRT | output=%s", srt_output)

        video_duration = wrapper.get_video_duration(video_path)
        chinese_audio_path = output_dir / f"{stem}_chinese_audio.wav"
        wrapper.compose_chinese_audio(segments, video_duration, temp_dir, chinese_audio_path)
        self.signals.stage_progress.emit("合成", 0.67)
        logger.info("合成 | 中文音频 | output=%s", chinese_audio_path)

        output_video_path = output_dir / f"{stem}_translated.mp4"
        wrapper.compose_video(
            video_path, chinese_audio_path, srt_path, output_video_path,
            style_name=self.config.subtitle.style,
        )
        self.signals.stage_progress.emit("合成", 1.0)
        logger.info("合成 | 视频 | output=%s", output_video_path)

        return output_video_path

    @staticmethod
    def _calc_actual_timestamps(segments: list[SubtitleSegment]) -> None:
        """根据对齐后的音频时长和拼接间隙，计算每段在实际音频流中的时间戳。"""
        valid = [s for s in segments if s.audio_path and s.audio_duration > 0]
        if not valid:
            return

        cursor = 0.0
        if valid[0].start_time > 0.01:
            cursor += valid[0].start_time

        for i, seg in enumerate(valid):
            seg.actual_start_time = cursor
            cursor += seg.audio_duration
            seg.actual_end_time = cursor

            if i < len(valid) - 1:
                gap = valid[i + 1].start_time - seg.end_time
                if gap > 0.01:
                    cursor += gap
