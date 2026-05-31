import logging
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from src.config import AppConfig
from src.gui.config_panel import ConfigPanel
from src.gui.constants import (
    COLOR_SECONDARY_BG,
    PANEL_DEFAULT_WIDTH,
    PANEL_MIN_WIDTH,
    SPACING_CONTENT_MARGIN,
    SPACING_MD,
    SPACING_SM,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from src.gui.pipeline_progress import PipelineProgress
from src.gui.transcript_panel import TranscriptPanel
from src.gui.video_drop_area import VideoDropArea
from src.pipeline import Pipeline
from src.signals import PipelineSignals
from src.utils.platform_utils import open_with_default_app
from src.validators import validate_all

logger = logging.getLogger("video_translator")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_OUTPUT_DIR = _PROJECT_ROOT / "output"


class MainWindow(QMainWindow):
    def __init__(self, config_path: Path) -> None:
        super().__init__()
        self.setWindowTitle("video_translator")
        self.setMinimumSize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)

        self._config_path = config_path
        self._settings = QSettings("video_translator", "MainWindow")
        self._translating = False
        self._validation_passed = False
        self._pipeline: Pipeline | None = None
        self._signals = PipelineSignals()

        self._setup_ui()
        self._load_qss()
        self._restore_geometry()

    def _setup_ui(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)

        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setStyleSheet(f"QScrollArea {{ background: {COLOR_SECONDARY_BG}; }}")

        self._config_panel = ConfigPanel(self._config_path, self)
        scroll_area.setWidget(self._config_panel)
        scroll_area.setMinimumWidth(PANEL_MIN_WIDTH)
        splitter.addWidget(scroll_area)

        right_panel = QWidget()
        right_panel.setObjectName("rightPanel")
        right_panel.setStyleSheet("QWidget#rightPanel { background: #FFFFFF; }")
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(
            SPACING_CONTENT_MARGIN, SPACING_CONTENT_MARGIN,
            SPACING_CONTENT_MARGIN, SPACING_CONTENT_MARGIN,
        )
        right_layout.setSpacing(SPACING_SM)

        self._video_drop_area = VideoDropArea()
        right_layout.addWidget(self._video_drop_area)

        right_layout.addSpacing(SPACING_MD)

        self._pipeline_progress = PipelineProgress()
        right_layout.addWidget(self._pipeline_progress)

        right_layout.addSpacing(SPACING_SM)

        self._transcript_panel = TranscriptPanel()
        right_layout.addWidget(self._transcript_panel)

        right_layout.addSpacing(SPACING_MD)

        self._translate_btn = QPushButton("开始翻译")
        self._translate_btn.setObjectName("primaryButton")
        self._translate_btn.setEnabled(False)
        right_layout.addWidget(self._translate_btn)

        self._open_output_btn = QPushButton("打开输出目录")
        self._open_output_btn.setObjectName("secondaryButton")
        right_layout.addWidget(self._open_output_btn)

        right_layout.addStretch()

        splitter.addWidget(right_panel)

        splitter.setSizes([PANEL_DEFAULT_WIDTH, 560])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)

        self._splitter = splitter

        self._connect_signals()
        QTimer.singleShot(0, self._setup_tab_order)

    def _connect_signals(self) -> None:
        self._video_drop_area.video_loaded.connect(self._on_video_loaded)
        self._translate_btn.clicked.connect(self._on_translate_clicked)
        self._open_output_btn.clicked.connect(self._open_output_dir)

        self._config_panel.validation_changed.connect(self._on_validation_changed)
        self._signals.pipeline_finished.connect(self._on_pipeline_finished)
        self._signals.stage_failed.connect(self._on_stage_failed)

        self._signals.stage_started.connect(self._pipeline_progress._on_stage_started)
        self._signals.stage_progress.connect(self._pipeline_progress._on_stage_progress)
        self._signals.stage_completed.connect(self._pipeline_progress._on_stage_completed)
        self._signals.pipeline_finished.connect(self._pipeline_progress._on_pipeline_finished)
        self._signals.tts_degraded.connect(self._pipeline_progress._on_tts_degraded)
        self._signals.stage_failed.connect(self._pipeline_progress._on_stage_failed)
        self._signals.transcript_updated.connect(self._transcript_panel._on_transcript_updated)

    def _on_video_loaded(self, path: Path) -> None:
        if not isinstance(path, Path):
            return
        self._config_panel.set_video_path(path)
        if not self._translating:
            self._translate_btn.setEnabled(self._validation_passed)

    def _on_translate_clicked(self) -> None:
        if self._translating:
            logger.info("用户中止翻译")
            if self._pipeline is not None:
                self._pipeline.abort()
            return

        if not self._translate_btn.isEnabled():
            return
        config = self._config_panel.get_config()
        video_path = self._video_drop_area.video_path
        if video_path is None:
            return

        # 翻译前校验防弹窗：按钮联动已做第一道防线，此为第二道保险
        result = validate_all(config, video_path)
        if not result.is_valid:
            self._show_validation_failure_dialog(result.errors)
            return

        logger.info(
            "翻译启动: %s，预设: %s", video_path, config.preset
        )
        self._translating = True
        self._translate_btn.setText("中止翻译")
        self._translate_btn.setEnabled(True)
        self._config_panel.setEnabled(False)
        self._video_drop_area.set_translating(True)
        self._pipeline_progress.reset()
        self._transcript_panel.reset()

        self._pipeline = Pipeline(config, self._signals)
        try:
            self._pipeline.start(video_path, _OUTPUT_DIR)
        except RuntimeError:
            self._on_pipeline_finished()

    def _on_pipeline_finished(self) -> None:
        """管线完成后恢复 UI 状态。"""
        self._translating = False
        self._translate_btn.setText("开始翻译")
        self._config_panel.setEnabled(True)
        self._video_drop_area.set_translating(False)
        has_video = self._video_drop_area.video_path is not None
        self._translate_btn.setEnabled(has_video and self._validation_passed)
        self._pipeline = None

    def _on_stage_failed(self, stage: str, error: str) -> None:
        """管线阶段失败时显示错误弹窗。用户主动中止则跳过。"""
        if self._pipeline is not None and self._pipeline._abort_requested.is_set():
            logger.info("用户中止，跳过失败弹窗 | stage=%s | error=%s", stage, error)
            return
        QMessageBox.critical(
            self,
            f"翻译失败 — {stage}",
            f"阶段「{stage}」失败：\n\n{error}",
        )

    def _on_validation_changed(self, is_valid: bool) -> None:
        """校验状态变化时更新按钮启用条件。"""
        self._validation_passed = is_valid
        if not self._translating:
            has_video = self._video_drop_area.video_path is not None
            self._translate_btn.setEnabled(has_video and is_valid)

    def _show_validation_failure_dialog(self, errors: list) -> None:
        """弹出校验失败 QMessageBox，列出所有失败项的三要素信息。"""
        from src.exceptions import ValidationError

        lines: list[str] = []
        for e in errors:
            if isinstance(e, ValidationError):
                lines.append(f"• [{e.stage}] {e}")
                lines.append(f"  修复: {e.suggestion}")
            else:
                lines.append(f"• {e}")
        detail = "\n".join(lines)
        QMessageBox.warning(
            self,
            "翻译前校验未通过",
            f"以下 {len(errors)} 项检查未通过：\n\n{detail}",
        )

    def _open_output_dir(self) -> None:
        try:
            _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            open_with_default_app(_OUTPUT_DIR)
        except Exception:
            logger.error("无法打开输出目录: %s", _OUTPUT_DIR, exc_info=True)

    def _setup_tab_order(self) -> None:
        """设置 Tab 焦点顺序：左侧配置项 → 右侧操作区，按界面从上到下（AC7 / UX-DR21）。

        用 findChildren(QWidget) 获取文档顺序（即视觉从上到下顺序），
        再按 isinstance 类型白名单过滤——只保留真正可聚焦的交互控件，
        排除 QComboBox 内部的 QListView 等弹出控件（它们不在同一窗口中，
        串进焦点链会触发 setTabOrder warning）。
        """
        from shiboken6 import isValid

        if not isValid(self):
            return
        focusable_types = (QComboBox, QLineEdit, QPushButton)

        # 左侧面板：文档顺序（视觉从上到下）→ 类型白名单过滤
        left_all = self._config_panel.findChildren(QWidget)
        left_focusable = [
            w
            for w in left_all
            if isinstance(w, focusable_types)
            and w.focusPolicy() != Qt.FocusPolicy.NoFocus
        ]

        prev: QWidget | None = None
        for w in left_focusable:
            if prev is not None:
                self.setTabOrder(prev, w)
            prev = w

        # 右侧面板焦点控件（目前为占位区域，Story 2-2/2-3 添加按钮后自动纳入）
        right_panel = self._splitter.widget(1)
        if right_panel is not None:
            right_all = right_panel.findChildren(QWidget)
            right_focusable = [
                w
                for w in right_all
                if isinstance(w, focusable_types)
                and w.focusPolicy() != Qt.FocusPolicy.NoFocus
            ]
            for w in right_focusable:
                if prev is not None:
                    self.setTabOrder(prev, w)
                prev = w

    def _load_qss(self) -> None:
        from PySide6.QtWidgets import QApplication

        qss_path = Path(__file__).parent / "styles.qss"
        try:
            qss_text = qss_path.read_text()
        except OSError:
            logger.warning("QSS file not readable: %s, using default styles", qss_path)
            return
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(qss_text)

    def _save_geometry(self) -> None:
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.setValue("windowState", self.saveState())

    def _restore_geometry(self) -> None:
        geometry = self._settings.value("geometry")
        if geometry is not None:
            if not self.restoreGeometry(geometry):
                self.resize(800, 600)
        else:
            self.resize(800, 600)

        state = self._settings.value("windowState")
        if state is not None:
            self.restoreState(state)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._translating and self._pipeline is not None:
            reply = QMessageBox.question(
                self,
                "确认退出",
                "翻译正在进行中，确定要退出吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self._pipeline.abort()
            self._translating = False

        try:
            if self._config_panel._save_timer.isActive():
                self._config_panel._save_timer.stop()
                self._config_panel._do_save()
            self._config_panel._validation_timer.stop()
        except AttributeError:
            pass
        self._save_geometry()
        super().closeEvent(event)

    def load_config(self) -> None:
        """委托 ConfigPanel 从 config.yaml 加载配置并填充面板"""
        self._config_panel.load_config()

    def get_config(self) -> AppConfig:
        """返回当前面板配置的深拷贝（pydantic AppConfig 模型）"""
        return self._config_panel.get_config()

    def refresh_schemes(self) -> None:
        """委托 ConfigPanel 刷新已保存方案下拉框。"""
        self._config_panel.refresh_schemes()
