import hashlib
import json
import logging
import math
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.config import MAX_VIDEO_DURATION_SECONDS, OUTPUT_DIR, AppConfig, format_duration_limit
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
from src.pipeline import STAGE_NAMES

logger = logging.getLogger("video_translator")

# 阶段总数：与 pipeline.STAGE_NAMES 长度同步，避免硬编码魔法数
_TOTAL_STAGES = len(STAGE_NAMES)

# 支持的视频格式后缀
SUPPORTED_FORMATS = {".mp4", ".mkv", ".mov", ".avi"}


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
        self.resume_requested: bool = False
        self.checkpoint_data: dict | None = None
        self._config_provider: Callable[[], AppConfig | None] | None = None

        self._setup_ui()
        self._set_idle_state()

    def set_config_provider(self, provider: Callable[[], AppConfig | None]) -> None:
        """注入配置获取回调。

        `_check_for_resume` 调用此回调获取当前 AppConfig 实例，
        用于计算 config_hash 与检查点中保存的 hash 比对（异常流程 B 校验）。
        """
        self._config_provider = provider

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

    # ==================== 翻译状态切换 ====================

    def set_translating(self, translating: bool) -> None:
        """切换翻译中状态：禁用拖放，按钮变为"翻译中..."并禁用。

        翻译结束后恢复为 loaded 状态（如已加载视频）或 idle 状态。
        """
        self.setAcceptDrops(not translating)
        if translating:
            self._select_file_btn.setText("翻译中...")
            self._select_file_btn.setEnabled(False)
        else:
            self._select_file_btn.setText("选择文件")
            self._select_file_btn.setEnabled(True)
            if self._video_path is not None and self._video_info is not None:
                info = self._video_info
                self._set_loaded_state(info["file_name"], info["duration"], info["format"])
            else:
                self._set_idle_state()

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
            self,
            "选择视频文件",
            str(Path.home()),
            filter_str,
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

        if duration_seconds > MAX_VIDEO_DURATION_SECONDS:
            minutes = duration_seconds / 60
            limit_display = format_duration_limit(MAX_VIDEO_DURATION_SECONDS)
            self._set_error_state(f"视频时长超过 {limit_display} 限制（{minutes:.1f} 分钟）")
            logger.warning("视频时长超限: %.1f 秒", duration_seconds)
            return

        # 检测断点续传
        self._check_for_resume(file_path)

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

    def _check_for_resume(self, file_path: Path) -> None:
        """检测断点续传检查点，校验 video_size/config_hash，按情况弹窗。

        - 主流程（hash/size 都匹配）：询问"是否继续"
        - 异常流程 A（video_size 不匹配）：警告"视频已变更"，自动清理
        - 异常流程 B（config_hash 不匹配）：提示"配置已变更"，由用户决定
        """
        self.resume_requested = False
        self.checkpoint_data = None

        try:
            actual_size = file_path.stat().st_size
        except OSError:
            return
        raw = f"{file_path.name}_{actual_size}".encode()
        video_hash = hashlib.md5(raw).hexdigest()[:8]
        temp_dir = OUTPUT_DIR / ".temp" / video_hash
        checkpoint_path = temp_dir / "checkpoint.json"

        if not checkpoint_path.exists():
            return

        try:
            data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if not isinstance(data, dict):
            return

        completed = data.get("completed_stages", [])
        current = data.get("current_stage", "")
        if not completed:
            return

        # ── 异常流程 A：视频已变更（大小不匹配） ──
        if data.get("video_size") != actual_size:
            QMessageBox.warning(
                self,
                "视频文件已变更",
                "检测到视频文件大小与上次翻译不一致，上次的翻译进度无法复用，将从头开始。",
            )
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("断点续传 | 视频已变更 | 已清理 %s", temp_dir)
            return

        # ── 异常流程 B：配置已变更（config_hash 不匹配） ──
        provider = self._config_provider
        if provider is not None:
            try:
                config = provider()
            except Exception as e:
                logger.warning("断点续传 | 获取配置失败 | %s", e)
                config = None
            if config is not None:
                payload = json.dumps(config.model_dump(), sort_keys=True, default=str)
                current_hash = hashlib.sha256(payload.encode()).hexdigest()
                if data.get("config_hash") != current_hash:
                    reply = QMessageBox.question(
                        self,
                        "配置已变更",
                        "检测到 ASR/翻译/TTS 引擎或参数与上次不一致，"
                        "上次的翻译结果可能不匹配。\n\n"
                        "点击 Yes 仍然继续（跳过已完成阶段，但结果可能不一致）；\n"
                        "点击 No 从头开始。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        self.resume_requested = True
                        self.checkpoint_data = data
                        logger.info("断点续传 | 配置已变更 | 用户选择继续 | stages=%s", completed)
                    else:
                        shutil.rmtree(temp_dir, ignore_errors=True)
                        logger.info("断点续传 | 配置已变更 | 用户放弃 | 已清理 %s", temp_dir)
                    return

        # ── 主流程：正常的续传询问 ──
        total = _TOTAL_STAGES
        reply = QMessageBox.question(
            self,
            "检测到未完成的翻译",
            f"上次翻译已完成 {len(completed)}/{total} 阶段（{', '.join(completed)}），"
            f"下次将从「{current}」开始。\n\n是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.resume_requested = True
            self.checkpoint_data = data
            logger.info("断点续传 | 用户选择继续 | stages=%s", completed)
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info("断点续传 | 用户放弃续传 | 已清理 %s", temp_dir)

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
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
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
