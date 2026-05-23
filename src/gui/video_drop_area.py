import logging
import math
import shutil
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget

from src.gui.constants import (
    COLOR_ACCENT,
    COLOR_BORDER,
    COLOR_ERROR,
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY_BG,
    COLOR_SECONDARY_TEXT,
    COLOR_SUCCESS,
    COLOR_TERTIARY_TEXT,
    DROP_AREA_MIN_HEIGHT,
    RADIUS_XL,
)

logger = logging.getLogger("video_translator")

# 支持的视频格式后缀
SUPPORTED_FORMATS = {".mp4", ".mkv", ".mov", ".avi"}
# 视频时长上限（秒），限制 30 分钟
MAX_DURATION_SECONDS = 1800


class VideoDropArea(QFrame):
    """视频拖放区组件，支持拖入视频文件并显示基本信息。

    四个视觉状态：
    - idle：虚线边框 + "拖入视频文件到此处" 提示
    - hover：蓝色边框 + 浅蓝背景 + "释放以添加视频"
    - loaded：绿色边框 + 文件名、时长（mm:ss）、格式
    - error：红色边框 + 错误提示信息

    拖入时校验文件格式和视频时长，通过 ffprobe 获取时长信息。
    """

    # 有效视频加载成功后 emit，携带文件路径
    video_loaded = Signal(Path)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._video_path: Path | None = None
        self._video_info: dict | None = None

        self._setup_ui()
        self._set_idle_state()

    @property
    def video_path(self) -> Path | None:
        """用户拖入的视频文件路径，未加载时返回 None"""
        return self._video_path

    @property
    def video_info(self) -> dict | None:
        """已加载视频的信息字典：file_name, duration, format, duration_seconds"""
        return self._video_info

    # ==================== UI 初始化 ====================

    def _setup_ui(self) -> None:
        self.setAcceptDrops(True)
        self.setMinimumHeight(DROP_AREA_MIN_HEIGHT)
        self.setFrameStyle(QFrame.Shape.StyledPanel)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        self._hint_label = QLabel("拖入视频文件到此处")
        self._hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._hint_label)

        self._sub_hint_label = QLabel("支持 MP4、MKV、MOV、AVI 格式")
        self._sub_hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub_hint_label)

        self._select_file_btn = QPushButton("选择文件")
        self._select_file_btn.setObjectName("textButton")
        self._select_file_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._select_file_btn.clicked.connect(self._on_select_file)
        layout.addWidget(self._select_file_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._info_label = QLabel("")
        self._info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._info_label.setVisible(False)
        layout.addWidget(self._info_label)

    # ==================== 四状态视觉管理 ====================

    def _set_idle_state(self) -> None:
        self.setStyleSheet(f"""
            VideoDropArea {{
                border: 2px dashed {COLOR_BORDER};
                background: transparent;
                border-radius: {RADIUS_XL}px;
            }}
        """)
        self._hint_label.setStyleSheet(f"""
            color: {COLOR_SECONDARY_TEXT};
            font-size: 14pt;
        """)
        self._sub_hint_label.setStyleSheet(f"""
            color: {COLOR_TERTIARY_TEXT};
            font-size: 10pt;
        """)
        self._hint_label.setText("拖入视频文件到此处")
        self._hint_label.setVisible(True)
        self._sub_hint_label.setVisible(True)
        self._select_file_btn.setVisible(True)
        self._info_label.setVisible(False)

    def _set_hover_state(self) -> None:
        self.setStyleSheet(f"""
            VideoDropArea {{
                border: 2px solid {COLOR_ACCENT};
                background: rgba(0, 122, 255, 0.04);
                border-radius: {RADIUS_XL}px;
            }}
        """)
        self._hint_label.setStyleSheet(f"""
            color: {COLOR_ACCENT};
            font-size: 14pt;
        """)
        self._sub_hint_label.setStyleSheet(f"""
            color: {COLOR_ACCENT};
            font-size: 10pt;
        """)
        self._hint_label.setText("释放以添加视频")
        self._hint_label.setVisible(True)
        self._sub_hint_label.setVisible(False)
        self._select_file_btn.setVisible(False)
        self._info_label.setVisible(False)

    def _set_loaded_state(self, file_name: str, duration_str: str, fmt: str) -> None:
        self.setStyleSheet(f"""
            VideoDropArea {{
                border: 2px solid {COLOR_SUCCESS};
                background: {COLOR_SECONDARY_BG};
                border-radius: {RADIUS_XL}px;
            }}
        """)
        self._hint_label.setStyleSheet(f"""
            color: {COLOR_PRIMARY_TEXT};
            font-size: 13pt;
            font-weight: bold;
        """)
        self._info_label.setStyleSheet(f"""
            color: {COLOR_SECONDARY_TEXT};
            font-size: 11pt;
        """)
        self._hint_label.setText(file_name)
        self._hint_label.setVisible(True)
        self._sub_hint_label.setVisible(False)
        self._select_file_btn.setVisible(True)
        self._info_label.setText(f"{duration_str} | {fmt}")
        self._info_label.setVisible(True)

    def _set_error_state(self, message: str) -> None:
        self._video_path = None
        self._video_info = None
        self.setStyleSheet(f"""
            VideoDropArea {{
                border: 2px solid {COLOR_ERROR};
                background: rgba(255, 59, 48, 0.04);
                border-radius: {RADIUS_XL}px;
            }}
        """)
        self._hint_label.setStyleSheet(f"""
            color: {COLOR_ERROR};
            font-size: 12pt;
        """)
        self._hint_label.setText(message)
        self._hint_label.setVisible(True)
        self._sub_hint_label.setVisible(False)
        self._select_file_btn.setVisible(True)
        self._info_label.setVisible(False)

    # ==================== 文件选择 ====================

    def _on_select_file(self) -> None:
        filter_str = "视频文件 (*.mp4 *.mkv *.mov *.avi);;所有文件 (*)"
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频文件", str(Path.home()), filter_str,
        )
        if not path:
            return
        self._process_file(Path(path))

    # ==================== 拖放事件处理 ====================

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        """拖入时检查 MIME 类型：仅接受文件 URL，其他类型直接拒绝"""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_hover_state()
        else:
            event.ignore()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        """离开时恢复状态：已加载过文件则恢复 loaded，否则回到 idle"""
        if self._video_path is not None and self._video_info is not None:
            info = self._video_info
            self._set_loaded_state(info["file_name"], info["duration"], info["format"])
        else:
            self._set_idle_state()

    def dropEvent(self, event: QDropEvent) -> None:
        """Qt 拖放事件重写：从拖放事件中提取视频文件路径并处理。

        Args:
            event: Qt 拖放事件对象。
        """
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        urls = event.mimeData().urls()
        if not urls:
            event.ignore()
            return

        file_path_str = urls[0].toLocalFile()
        if not file_path_str:
            event.ignore()
            return

        self._process_file(Path(file_path_str))
        if self._video_path is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def _process_file(self, file_path: Path) -> None:
        suffix = file_path.suffix.lower()

        if suffix not in SUPPORTED_FORMATS:
            self._set_error_state("不支持的视频格式（仅支持 mp4、mkv、mov、avi）")
            logger.warning("不支持的文件格式: %s", suffix)
            return

        if not file_path.is_file():
            self._set_error_state("文件不存在或不是有效的视频文件")
            logger.warning("文件不存在: %s", file_path)
            return

        try:
            duration_seconds = self._get_video_duration(file_path)
        except FileNotFoundError:
            self._set_error_state("ffprobe 未找到，请安装 ffmpeg")
            logger.error("ffprobe 不可用")
            return
        except (subprocess.TimeoutExpired, RuntimeError, OSError) as e:
            self._set_error_state(f"无法获取视频时长: {e}")
            logger.error("ffprobe 调用失败: %s", e)
            return

        if duration_seconds > MAX_DURATION_SECONDS:
            minutes = duration_seconds / 60
            self._set_error_state(f"视频时长超过 30 分钟限制（{minutes:.1f} 分钟）")
            logger.warning("视频时长超限: %.1f 秒", duration_seconds)
            return

        duration_str = self._format_duration(duration_seconds)
        fmt = suffix.lstrip(".").upper()

        self._video_path = file_path
        self._video_info = {
            "file_name": file_path.name,
            "duration": duration_str,
            "format": fmt,
            "duration_seconds": duration_seconds,
        }

        self._set_loaded_state(file_path.name, duration_str, fmt)
        self.video_loaded.emit(file_path)
        logger.info("视频加载成功: %s (%.1fs)", file_path.name, duration_seconds)

    # ==================== ffprobe 时长提取 ====================

    @staticmethod
    def _get_video_duration(file_path: Path) -> float:
        """通过 ffprobe 获取视频时长（秒）。

        ffprobe 使用 -v error 将日志级别降到最低，-show_entries format=duration
        只输出时长字段，-of default=noprint_wrappers=1:nokey=1 确保只输出纯数字。

        Args:
            file_path: 视频文件路径

        Returns:
            float: 视频时长（秒）

        Raises:
            FileNotFoundError: ffprobe 未安装
            RuntimeError: ffprobe 调用失败、超时或输出解析失败
        """
        if not shutil.which("ffprobe"):
            raise FileNotFoundError("ffprobe 未找到，请安装 ffmpeg")

        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(file_path),
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffprobe 调用超时（10 秒）")

        if result.returncode != 0:
            raise RuntimeError(f"ffprobe 失败: {result.stderr.strip()}")

        try:
            value = float(result.stdout.strip())
        except ValueError:
            raise RuntimeError(f"ffprobe 输出解析失败: {result.stdout.strip()}")

        if not math.isfinite(value):
            raise RuntimeError(f"ffprobe 返回无效时长: {value}")

        return value

    @staticmethod
    def _format_duration(seconds: float) -> str:
        """将秒数转换为 mm:ss 格式字符串"""
        total_seconds = int(seconds)
        minutes = total_seconds // 60
        secs = total_seconds % 60
        return f"{minutes:02d}:{secs:02d}"
