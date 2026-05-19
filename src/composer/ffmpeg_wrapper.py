from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from src.exceptions import PipelineError
from src.models import SubtitleSegment

logger = logging.getLogger("video_translator")


class FFmpegWrapper:
    """ffmpeg/ffprobe 命令封装，负责音频拼接和视频合成。"""

    def get_video_duration(self, video_path: Path) -> float:
        """通过 ffprobe 获取视频时长（秒）。"""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, timeout=30, check=True, text=True,
            )
            return float(result.stdout.strip())
        except subprocess.CalledProcessError as e:
            stderr_text = (
                e.stderr
                if isinstance(e.stderr, str)
                else (e.stderr or b"").decode("utf-8", errors="replace")
            )
            raise PipelineError(
                f"ffprobe 获取时长失败: {stderr_text[:200]}",
                stage="合成",
                suggestion="请确认视频文件有效且 ffprobe 已安装",
            ) from e
        except subprocess.TimeoutExpired:
            raise PipelineError(
                "ffprobe 超时（30秒）",
                stage="合成",
                suggestion="视频文件可能损坏或过大",
            )
        except FileNotFoundError:
            raise PipelineError(
                "ffprobe 未找到",
                stage="合成",
                suggestion="请安装 ffmpeg: brew install ffmpeg",
            )

    def compose_chinese_audio(
        self,
        segments: list[SubtitleSegment],
        video_duration: float,
        temp_dir: Path,
        output_path: Path,
    ) -> Path:
        """将多段中文音频按时间轴拼接为完整音轨，段间静音填充。"""

        valid_segments = [
            s for s in segments if s.audio_path and s.audio_duration > 0
        ]
        if not valid_segments:
            raise PipelineError(
                "没有有效的音频段可供合成",
                stage="合成",
                suggestion="请检查 TTS 和语速自适应阶段是否正常完成",
            )

        concat_dir = temp_dir / "concat"
        concat_dir.mkdir(parents=True, exist_ok=True)
        entries: list[str] = []

        if valid_segments[0].start_time > 0.01:
            silence_path = concat_dir / "silence_pre.wav"
            self._create_silence(valid_segments[0].start_time, silence_path)
            entries.append(f"file '{silence_path}'")

        for i, seg in enumerate(valid_segments):
            entries.append(f"file '{seg.audio_path}'")
            if i < len(valid_segments) - 1:
                gap = valid_segments[i + 1].start_time - seg.end_time
                if gap > 0.01:
                    silence_path = concat_dir / f"silence_gap_{i}.wav"
                    self._create_silence(gap, silence_path)
                    entries.append(f"file '{silence_path}'")

        concat_file = concat_dir / "concat_list.txt"
        concat_file.write_text("\n".join(entries), encoding="utf-8")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_file),
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, timeout=300)
        logger.info("合成 | 中文音频 | output=%s", output_path)
        return output_path

    def compose_video(
        self,
        video_path: Path,
        audio_path: Path,
        srt_path: Path,
        output_path: Path,
    ) -> Path:
        """合成最终视频：替换原音轨为中文配音 + 烧录硬字幕。"""

        escaped_srt = str(srt_path).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
        subtitle_filter = (
            f"subtitles='{escaped_srt}'"
            ":force_style='FontSize=20,PrimaryColour=&Hffffff&,"
            "OutlineColour=&H40000000,BorderStyle=1,Outline=2,Alignment=2'"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-vf", subtitle_filter,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, timeout=300)
        logger.info("合成 | 视频 | output=%s", output_path)
        return output_path

    def _create_silence(self, duration: float, output_path: Path) -> None:
        """生成指定时长的静音 WAV（16kHz 单声道 PCM）。"""
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono",
            "-t", f"{duration:.3f}",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            str(output_path),
        ]
        self._run_ffmpeg(cmd, timeout=30)

    def _run_ffmpeg(self, cmd: list[str], timeout: int = 300) -> None:
        """执行 ffmpeg 子进程，统一处理 CalledProcessError/TimeoutExpired/FileNotFoundError。"""
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout, check=True)
        except subprocess.CalledProcessError as e:
            stderr_text = e.stderr.decode("utf-8", errors="replace") if e.stderr else ""
            raise PipelineError(
                f"ffmpeg 合成失败: {stderr_text[:200]}",
                stage="合成",
                suggestion="请确认 ffmpeg 已安装且视频/音频文件有效",
            ) from e
        except subprocess.TimeoutExpired:
            raise PipelineError(
                f"ffmpeg 合成超时（{timeout}秒）",
                stage="合成",
                suggestion="视频可能过大或 ffmpeg 处理卡住",
            )
        except FileNotFoundError:
            raise PipelineError(
                "ffmpeg 未找到",
                stage="合成",
                suggestion="请安装 ffmpeg: brew install ffmpeg",
            )
