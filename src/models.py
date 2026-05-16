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
        if self.start_time is not None and self.end_time is not None:
            return self.end_time - self.start_time
        return None


@dataclass
class ProgressEvent:
    stage: str
    progress: float
    message: str = ""
