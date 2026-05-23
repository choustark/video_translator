from __future__ import annotations

from pathlib import Path

from src.models import SubtitleSegment


class SubtitleGenerator:

    def generate_srt(self, segments: list[SubtitleSegment], output_path: Path) -> Path:
        """根据字幕段落列表生成 SRT 格式字幕文件。

        自动跳过 translated_text 为空的段落，序号从 1 开始连续递增。
        时间戳格式为 ``HH:MM:SS,mmm``。

        Args:
            segments: 字幕段落列表，需包含 start_time、end_time 和 translated_text。
            output_path: 输出 ``.srt`` 文件路径，父目录不存在时会自动创建。

        Returns:
            实际写入的 ``.srt`` 文件路径。
        """
        entries: list[str] = []
        seq = 1
        for seg in segments:
            if not seg.translated_text:
                continue
            start = self._format_timestamp(
                seg.actual_start_time if seg.actual_start_time is not None else seg.start_time,
            )
            end = self._format_timestamp(
                seg.actual_end_time if seg.actual_end_time is not None else seg.end_time,
            )
            entries.append(f"{seq}\n{start} --> {end}\n{seg.translated_text}")
            seq += 1

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n\n".join(entries) + "\n" if entries else "", encoding="utf-8")
        return output_path

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        total_ms = round(seconds * 1000)
        ms = total_ms % 1000
        total_secs = total_ms // 1000
        s = total_secs % 60
        m = (total_secs // 60) % 60
        h = total_secs // 3600
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
