"""临时目录与检查点共享工具。

`compute_video_hash` 是 video_translator 项目对单个视频文件的稳定身份标识，
pipeline.py 与 gui/video_drop_area.py 共享此公式以避免漂移（DRY）。

公式：md5(f"{file_name}_{file_size_bytes}").hexdigest()[:8]
- 仅依赖文件名和大小，不读取内容，避免大文件 IO 开销
- 截取 8 位 hex（32 bit），对个人项目单机使用场景碰撞风险可接受
- 检查点目录路径：`output/.temp/{video_hash}/`
"""

from __future__ import annotations

import hashlib
from pathlib import Path


def compute_video_hash(video_path: Path) -> str:
    """根据视频文件名与大小计算 8 位 hash 作为检查点目录键。

    Args:
        video_path: 视频文件路径。

    Returns:
        8 位十六进制字符串。文件不存在时抛 OSError（由调用方决定如何处理）。
    """
    raw = f"{video_path.name}_{video_path.stat().st_size}".encode()
    return hashlib.md5(raw).hexdigest()[:8]
