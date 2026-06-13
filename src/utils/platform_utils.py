"""跨平台工具函数。

集中管理平台检测逻辑，避免在代码各处散落 sys.platform 判断。
"""

import os
import subprocess
import sys
from pathlib import Path

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
IS_LINUX = sys.platform == "linux"


def open_with_default_app(path: str | Path) -> None:
    """用系统默认应用打开文件或文件夹。"""
    path_str = str(path)
    if IS_WINDOWS:
        os.startfile(path_str)
    elif IS_MACOS:
        subprocess.run(["open", path_str], check=False)
    else:
        subprocess.run(["xdg-open", path_str], check=False)


def get_ffmpeg_install_hint() -> str:
    """返回当前平台的 ffmpeg 安装提示。"""
    if IS_MACOS:
        return "brew install ffmpeg"
    if IS_WINDOWS:
        return "winget install ffmpeg（或从 https://www.gyan.dev/ffmpeg/builds/ 下载）"
    return "sudo apt install ffmpeg  # 或等效包管理器"


def get_process_group_kwargs() -> dict:
    """返回创建独立进程组/会话的子进程参数。

    macOS/Linux: start_new_session=True（调用 setsid）
    Windows:     creationflags=CREATE_NEW_PROCESS_GROUP
    """
    if IS_WINDOWS:
        # 检查 subprocess 模块是否有 CREATE_NEW_PROCESS_GROUP 属性
        # macOS/Linux Python 中不存在此常量，使用硬编码值备选
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        # CREATE_NEW_PROCESS_GROUP = 0x00000200 (512)
        return {"creationflags": 0x00000200}
    return {"start_new_session": True}
