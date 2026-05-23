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
