from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


@dataclass
class SubtitleSegment:
    index: int
    start_time: float
    end_time: float
    source_text: str
    translated_text: str = ""
    audio_path: Path = Path()
    audio_duration: float = 0.0
    actual_start_time: float | None = None
    actual_end_time: float | None = None

    def to_dict(self) -> dict:
        """序列化为 JSON 兼容 dict。Path 转为字符串，None 保留。"""
        d = {}
        for f in _SEGMENT_FIELDS:
            v = getattr(self, f.name)
            if isinstance(v, Path):
                d[f.name] = str(v)
            else:
                d[f.name] = v
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "SubtitleSegment":
        """从 dict 反序列化，自动转换 audio_path 为 Path。

        未知字段会被忽略（向前兼容：未来版本写入的新字段不会让旧版本崩溃）。
        缺失的可选字段由 dataclass 默认值兜底。
        """
        known = {f.name for f in _SEGMENT_FIELDS}
        kwargs = {k: v for k, v in data.items() if k in known}
        if isinstance(kwargs.get("audio_path"), str):
            kwargs["audio_path"] = Path(kwargs["audio_path"])
        return cls(**kwargs)


_SEGMENT_FIELDS = list(SubtitleSegment.__dataclass_fields__.values())


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class StageState:
    name: str
    status: StageStatus = StageStatus.PENDING
    progress: float = 0.0
    start_time: float | None = None
    end_time: float | None = None
    error: str | None = None

    @property
    def duration(self) -> float | None:
        """计算阶段持续时长（秒）。

        Returns:
            当 start_time 和 end_time 都已设置时返回二者之差，否则返回 ``None``。
        """
        if self.start_time is not None and self.end_time is not None:
            return self.end_time - self.start_time
        return None


@dataclass
class ProgressEvent:
    stage: str
    progress: float
    message: str = ""


@dataclass
class PipelineResult:
    video_path: Path
    output_dir: Path
    audio_path: Path = Path()
    success: bool = True
    error: str | None = None
