import re
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.config import (
    AppConfig,
    ASRConfig,
    SubtitleConfig,
    TranslationConfig,
    TTSConfig,
    get_preset,
    load_config,
    save_api_key_to_env,
    save_config,
)
from src.exceptions import ConfigError
from src.gui.constants import (
    COLOR_SUCCESS,
    COLOR_WARNING,
    SPACING_CONTENT_MARGIN,
    SPACING_FORM_ITEM,
    SPACING_MD,
    SPACING_SECTION_TITLE_BOTTOM,
    SPACING_SECTION_TITLE_TOP,
    SPACING_XS,
)
from src.scheme_manager import SchemeManager
from src.validators import (
    ValidationError,
    validate_all,
    validate_config_only,
)

_PRESET_DISPLAY: dict[str, str] = {
    "high_quality": "高质量",
    "balanced": "均衡",
    "fast": "快速",
    "offline": "全离线",
    "custom": "自定义",
}
_PRESET_KEYS: dict[str, str] = {v: k for k, v in _PRESET_DISPLAY.items()}

_CUSTOM_KEY = "custom"

_PRESET_RESOURCE: dict[str, tuple[str, str]] = {
    "high_quality": ("≈7GB", "≈3GB"),
    "balanced": ("≈5.5GB", "≈1.5GB"),
    "fast": ("≈2.5GB", "≈2.3GB"),
    "offline": ("≈8GB", "≈5GB"),
}

_TRANSLATION_DISPLAY: dict[str, str] = {
    "glm": "GLM",
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "deepl": "DeepL",
    "nllb": "本地 NLLB",
}
_TRANSLATION_KEYS: dict[str, str] = {v: k for k, v in _TRANSLATION_DISPLAY.items()}

_ASR_ENGINE_DISPLAY: dict[str, str] = {
    "mlx-whisper": "mlx-whisper",
    "faster-whisper": "faster-whisper",
}
_TTS_ENGINE_DISPLAY: dict[str, str] = {
    "cosyvoice": "CosyVoice",
    "chattts": "ChatTTS",
    "edge-tts": "Edge-TTS",
}

_SUBTITLE_STYLE_DISPLAY: dict[str, str] = {
    "classic_white": "经典白字",
    "yellow_black": "黄字黑底",
    "white_clean": "白字无边",
}

_SCHEME_NAME_RE = re.compile(r"^[\w一-鿿-]+$")
_SCHEMES_DIR = Path.home() / ".video_translator" / "schemes"


class ConfigPanel(QWidget):
    validation_changed = Signal(bool)

    @staticmethod
    def _make_form() -> QFormLayout:
        form = QFormLayout()
        form.setSpacing(SPACING_FORM_ITEM)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignTop)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        return form

    def __init__(self, config_path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config_path = config_path
        self._file_config: AppConfig | None = None
        self._scheme_mgr = SchemeManager(_SCHEMES_DIR)
        self._video_path: Path | None = None
        self._last_preset_key: str = "high_quality"

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._do_save)

        # 校验防抖 timer（独立于保存 timer，300ms debounce）
        self._validation_timer = QTimer(self)
        self._validation_timer.setSingleShot(True)
        self._validation_timer.setInterval(300)
        self._validation_timer.timeout.connect(self._do_validation)

        # 校验状态图标
        self._asr_status_icon = self._create_status_icon()
        self._translation_status_icon = self._create_status_icon()
        self._tts_status_icon = self._create_status_icon()

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(
            SPACING_CONTENT_MARGIN,
            SPACING_CONTENT_MARGIN,
            SPACING_CONTENT_MARGIN,
            SPACING_CONTENT_MARGIN,
        )
        layout.setSpacing(0)

        preset_form = self._make_form()

        self._preset_combo = QComboBox()
        for key in _PRESET_DISPLAY:
            self._preset_combo.addItem(_PRESET_DISPLAY[key], key)
        self._btn_restore_preset = QPushButton("恢复默认")
        self._btn_restore_preset.setObjectName("inlineButton")
        self._btn_restore_preset.setFixedWidth(70)
        self._btn_restore_preset.setVisible(False)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(SPACING_XS)
        preset_row.addWidget(self._preset_combo, 1)
        preset_row.addWidget(self._btn_restore_preset)
        self._preset_info_label = QLabel()
        self._preset_info_label.setFixedSize(16, 16)
        self._preset_info_label.setToolTip(self._build_preset_tooltip("high_quality"))
        style = QApplication.style()
        pixmap = style.standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation).pixmap(16, 16)
        self._preset_info_label.setPixmap(pixmap)
        preset_row.addWidget(self._preset_info_label)
        preset_form.addRow(self._field_label("预设方案"), preset_row)
        layout.addLayout(preset_form)

        layout.addSpacing(SPACING_MD)

        scheme_form = self._make_form()
        self._scheme_combo = QComboBox()
        self._scheme_combo.addItem("（无）", "")
        scheme_form.addRow(self._field_label("已保存方案"), self._scheme_combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(SPACING_XS)
        self._btn_save_scheme = QPushButton("保存")
        self._btn_delete_scheme = QPushButton("删除")
        self._btn_import_scheme = QPushButton("导入")
        self._btn_export_scheme = QPushButton("导出")
        for btn in (
            self._btn_save_scheme,
            self._btn_delete_scheme,
            self._btn_import_scheme,
            self._btn_export_scheme,
        ):
            btn.setObjectName("inlineButton")
            btn_row.addWidget(btn)
        scheme_form.addRow("", btn_row)
        layout.addLayout(scheme_form)

        layout.addSpacing(SPACING_SECTION_TITLE_TOP)
        layout.addWidget(self._section_divider())
        layout.addSpacing(SPACING_SECTION_TITLE_BOTTOM)

        layout.addWidget(self._section_title("ASR 语音识别"))
        layout.addSpacing(SPACING_XS)
        asr_form = self._make_form()

        self._asr_engine_combo = QComboBox()
        for key, display in _ASR_ENGINE_DISPLAY.items():
            self._asr_engine_combo.addItem(display, key)
        asr_form.addRow(self._field_label("引擎类型"), self._asr_engine_combo)

        self._asr_path_input = QLineEdit()
        self._asr_path_input.setReadOnly(True)
        self._asr_path_input.setPlaceholderText("选择模型目录...")
        asr_path_btn = QPushButton("浏览...")
        asr_path_btn.setObjectName("inlineButton")
        asr_path_row = QHBoxLayout()
        asr_path_row.setSpacing(SPACING_XS)
        asr_path_row.addWidget(self._asr_path_input)
        asr_path_row.addWidget(asr_path_btn)
        asr_path_row.addWidget(self._asr_status_icon)
        asr_path_btn.clicked.connect(lambda: self._browse_directory(self._asr_path_input))
        asr_form.addRow(self._field_label("模型路径"), asr_path_row)

        self._use_default_nouns_cb = QCheckBox("使用默认技术词汇")
        self._use_default_nouns_cb.setChecked(True)
        self._use_default_nouns_cb.setToolTip(
            "默认词汇：Claude Code、GPT-4、PySide6、ffmpeg、OpenAI 等\n"
            "取消勾选后仅使用下方自定义词汇"
        )
        asr_form.addRow("", self._use_default_nouns_cb)

        self._proper_nouns_input = QTextEdit()
        self._proper_nouns_input.setPlaceholderText(
            "输入专有名词，逗号或换行分隔...\n例如：人名、地名、专业术语"
        )
        self._proper_nouns_input.setMaximumHeight(60)
        asr_form.addRow(self._field_label("专有名词"), self._proper_nouns_input)

        layout.addLayout(asr_form)

        layout.addSpacing(SPACING_SECTION_TITLE_TOP)
        layout.addWidget(self._section_divider())
        layout.addSpacing(SPACING_SECTION_TITLE_BOTTOM)

        layout.addWidget(self._section_title("翻译"))
        layout.addSpacing(SPACING_XS)
        trans_form = self._make_form()

        self._translation_combo = QComboBox()
        for key in _TRANSLATION_DISPLAY:
            self._translation_combo.addItem(_TRANSLATION_DISPLAY[key], key)
        trans_form.addRow(self._field_label("翻译后端"), self._translation_combo)

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("输入 API Key...")
        self._api_key_toggle = QPushButton("显示")
        self._api_key_toggle.setObjectName("inlineButton")
        self._api_key_toggle.setFixedWidth(50)
        self._api_key_toggle.clicked.connect(self._toggle_api_key_visibility)
        api_key_row = QHBoxLayout()
        api_key_row.setSpacing(SPACING_XS)
        api_key_row.addWidget(self._api_key_input)
        api_key_row.addWidget(self._api_key_toggle)
        api_key_row.addWidget(self._translation_status_icon)
        trans_form.addRow(self._field_label("API Key"), api_key_row)
        layout.addLayout(trans_form)

        layout.addSpacing(SPACING_SECTION_TITLE_TOP)
        layout.addWidget(self._section_divider())
        layout.addSpacing(SPACING_SECTION_TITLE_BOTTOM)

        layout.addWidget(self._section_title("语音合成"))
        layout.addSpacing(SPACING_XS)
        tts_form = self._make_form()

        self._tts_engine_combo = QComboBox()
        for key, display in _TTS_ENGINE_DISPLAY.items():
            self._tts_engine_combo.addItem(display, key)
        tts_form.addRow(self._field_label("引擎类型"), self._tts_engine_combo)

        self._tts_path_input = QLineEdit()
        self._tts_path_input.setReadOnly(True)
        self._tts_path_input.setPlaceholderText("选择模型目录...")
        tts_path_btn = QPushButton("浏览...")
        tts_path_btn.setObjectName("inlineButton")
        tts_path_row = QHBoxLayout()
        tts_path_row.setSpacing(SPACING_XS)
        tts_path_row.addWidget(self._tts_path_input)
        tts_path_row.addWidget(tts_path_btn)
        tts_path_row.addWidget(self._tts_status_icon)
        tts_path_btn.clicked.connect(lambda: self._browse_directory(self._tts_path_input))
        tts_form.addRow(self._field_label("模型路径"), tts_path_row)

        self._subtitle_style_combo = QComboBox()
        for key, display in _SUBTITLE_STYLE_DISPLAY.items():
            self._subtitle_style_combo.addItem(display, key)
        tts_form.addRow(self._field_label("字幕样式"), self._subtitle_style_combo)

        layout.addLayout(tts_form)

        layout.addSpacing(SPACING_MD)
        self._validation_summary_label = QLabel()
        self._validation_summary_label.setObjectName("validationSummary")
        self._validation_summary_label.setVisible(False)  # 首次校验前隐藏
        layout.addWidget(self._validation_summary_label)

        layout.addStretch()

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("fieldLabel")
        return label

    def _create_status_icon(self) -> QLabel:
        """创建 16x16 固定尺寸的校验状态图标 QLabel，初始为空。"""
        icon = QLabel()
        icon.setFixedSize(16, 16)
        return icon

    def _set_icon_state(self, icon: QLabel, passed: bool, tooltip: str) -> None:
        """设置校验图标状态：通过显示绿色勾，失败显示红色叉 + tooltip。"""
        style = QApplication.style()
        if passed:
            pixmap = style.standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton).pixmap(16, 16)
        else:
            pixmap = style.standardIcon(QStyle.StandardPixmap.SP_DialogCancelButton).pixmap(16, 16)
        icon.setPixmap(pixmap)
        icon.setToolTip(tooltip if not passed else "")

    def _section_divider(self) -> QWidget:
        line = QWidget()
        line.setFixedHeight(1)
        line.setObjectName("sectionDivider")
        return line

    def _connect_signals(self) -> None:
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self._btn_restore_preset.clicked.connect(self._restore_preset)
        self._asr_engine_combo.currentIndexChanged.connect(self._on_config_changed)
        self._asr_path_input.textChanged.connect(self._on_config_changed)
        self._use_default_nouns_cb.stateChanged.connect(self._on_config_changed)
        self._proper_nouns_input.textChanged.connect(self._on_config_changed)
        self._translation_combo.currentIndexChanged.connect(self._on_config_changed)
        self._api_key_input.textChanged.connect(self._on_config_changed)
        self._tts_engine_combo.currentIndexChanged.connect(self._on_config_changed)
        self._tts_path_input.textChanged.connect(self._on_config_changed)
        self._subtitle_style_combo.currentIndexChanged.connect(self._on_config_changed)
        self._scheme_combo.currentIndexChanged.connect(self._on_scheme_selected)
        self._btn_save_scheme.clicked.connect(self._save_current_scheme)
        self._btn_delete_scheme.clicked.connect(self._delete_selected_scheme)
        self._btn_import_scheme.clicked.connect(self._import_scheme)
        self._btn_export_scheme.clicked.connect(self._export_scheme)

    def _on_preset_changed(self, _index: int) -> None:
        key = self._preset_combo.currentData()
        if not key or key == _CUSTOM_KEY:
            return
        self._last_preset_key = key
        current_api_key = self._api_key_input.text()
        config = get_preset(key)
        self._fill_from_config(config)
        if current_api_key:
            self._api_key_input.setText(current_api_key)
        self._btn_restore_preset.setVisible(False)
        self._preset_info_label.setToolTip(self._build_preset_tooltip(key))
        self._on_config_changed()

    def _fill_from_config(self, config: AppConfig) -> None:
        self._preset_combo.blockSignals(True)
        self._asr_engine_combo.blockSignals(True)
        self._asr_path_input.blockSignals(True)
        self._use_default_nouns_cb.blockSignals(True)
        self._proper_nouns_input.blockSignals(True)
        self._translation_combo.blockSignals(True)
        self._api_key_input.blockSignals(True)
        self._tts_engine_combo.blockSignals(True)
        self._tts_path_input.blockSignals(True)
        self._subtitle_style_combo.blockSignals(True)

        preset_idx = self._preset_combo.findData(config.preset)
        if preset_idx >= 0:
            self._preset_combo.setCurrentIndex(preset_idx)

        asr_engine_idx = self._asr_engine_combo.findData(config.asr.engine)
        if asr_engine_idx >= 0:
            self._asr_engine_combo.setCurrentIndex(asr_engine_idx)

        self._asr_path_input.setText(config.asr.model_path)
        self._use_default_nouns_cb.setChecked(config.asr.use_default_proper_nouns)
        self._proper_nouns_input.setPlainText(", ".join(config.asr.proper_nouns))

        trans_idx = self._translation_combo.findData(config.translation.engine)
        if trans_idx >= 0:
            self._translation_combo.setCurrentIndex(trans_idx)

        self._api_key_input.setText(config.translation.api_key)

        tts_engine_idx = self._tts_engine_combo.findData(config.tts.engine)
        if tts_engine_idx >= 0:
            self._tts_engine_combo.setCurrentIndex(tts_engine_idx)

        self._tts_path_input.setText(config.tts.model_path)

        style_idx = self._subtitle_style_combo.findData(config.subtitle.style)
        if style_idx >= 0:
            self._subtitle_style_combo.setCurrentIndex(style_idx)

        self._preset_combo.blockSignals(False)
        self._asr_engine_combo.blockSignals(False)
        self._asr_path_input.blockSignals(False)
        self._use_default_nouns_cb.blockSignals(False)
        self._proper_nouns_input.blockSignals(False)
        self._translation_combo.blockSignals(False)
        self._api_key_input.blockSignals(False)
        self._tts_engine_combo.blockSignals(False)
        self._tts_path_input.blockSignals(False)
        self._subtitle_style_combo.blockSignals(False)

    def _on_config_changed(self) -> None:
        self._detect_preset_drift()
        self._save_timer.start()
        self._schedule_validation()

    @staticmethod
    def _build_preset_tooltip(preset_key: str) -> str:
        resource = _PRESET_RESOURCE.get(preset_key)
        if not resource:
            return ""
        mem, disk = resource
        return f"内存需求：{mem}（基于默认模型估算）\n模型文件：{disk}"

    def _detect_preset_drift(self) -> None:
        """检查当前配置是否偏离了上次选中的预设，若偏离则切换到"自定义"。"""
        current_key = self._preset_combo.currentData()
        if current_key == _CUSTOM_KEY:
            return

        preset = get_preset(self._last_preset_key)
        if self._matches_preset(preset):
            return

        self._preset_combo.blockSignals(True)
        idx = self._preset_combo.findData(_CUSTOM_KEY)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.blockSignals(False)
        self._btn_restore_preset.setVisible(True)

    def _matches_preset(self, preset: AppConfig) -> bool:
        if self._asr_engine_combo.currentData() != preset.asr.engine:
            return False
        if self._asr_path_input.text() != preset.asr.model_path:
            return False
        if self._translation_combo.currentData() != preset.translation.engine:
            return False
        if self._tts_engine_combo.currentData() != preset.tts.engine:
            return False
        if self._tts_path_input.text() != preset.tts.model_path:
            return False
        if self._subtitle_style_combo.currentData() != preset.subtitle.style:
            return False
        return True

    def _restore_preset(self) -> None:
        """恢复到上次选中的预设配置。"""
        config = get_preset(self._last_preset_key)
        current_api_key = self._api_key_input.text()
        self._fill_from_config(config)
        if current_api_key:
            self._api_key_input.setText(current_api_key)

        self._preset_combo.blockSignals(True)
        idx = self._preset_combo.findData(self._last_preset_key)
        if idx >= 0:
            self._preset_combo.setCurrentIndex(idx)
        self._preset_combo.blockSignals(False)
        self._btn_restore_preset.setVisible(False)
        self._on_config_changed()

    def _do_save(self) -> None:
        config = self._collect_config()
        if config is not None:
            api_key = str(self._api_key_input.text())
            save_api_key_to_env(api_key)
            save_config(config, self._config_path)

    def _collect_config(self) -> AppConfig | None:
        preset_key = str(self._preset_combo.currentData() or "high_quality")
        trans_key = cast(
            Literal["glm", "deepseek", "openai", "deepl", "nllb"],
            str(self._translation_combo.currentData() or "glm"),
        )
        asr_engine = cast(
            Literal["mlx-whisper", "faster-whisper", "whisper"],
            str(self._asr_engine_combo.currentData() or "mlx-whisper"),
        )
        tts_engine = cast(
            Literal["cosyvoice", "edge-tts", "chattts"],
            str(self._tts_engine_combo.currentData() or "cosyvoice"),
        )
        subtitle_style = str(self._subtitle_style_combo.currentData() or "classic_white")

        # 解析专有名词：支持中英文标点和换行分隔，去空格，过滤空字符串
        proper_nouns_text = self._proper_nouns_input.toPlainText()
        proper_nouns = [
            noun.strip() for noun in re.split(r"[,，、;；\r\n]+", proper_nouns_text) if noun.strip()
        ]

        try:
            return AppConfig(
                preset=preset_key,
                asr=ASRConfig(
                    engine=asr_engine,
                    model_path=self._asr_path_input.text(),
                    language="en",
                    proper_nouns=proper_nouns,
                    use_default_proper_nouns=self._use_default_nouns_cb.isChecked(),
                ),
                translation=TranslationConfig(
                    engine=trans_key,
                    api_key=self._api_key_input.text(),
                    source_lang="EN",
                    target_lang="ZH",
                ),
                tts=TTSConfig(
                    engine=tts_engine,
                    model_path=self._tts_path_input.text(),
                    voice="default",
                    speed=1.0,
                    conda_python_path=self._file_cosyvoice_field("conda_python_path"),
                    cosyvoice_source_path=self._file_cosyvoice_field("cosyvoice_source_path"),
                ),
                subtitle=SubtitleConfig(style=subtitle_style),
            )
        except Exception:
            return None

    # --- 校验反馈 ---

    def _file_cosyvoice_field(self, field: str) -> str:
        if self._file_config is not None:
            return getattr(self._file_config.tts, field, "")
        return ""

    def set_video_path(self, path: Path | None) -> None:
        """设置当前视频路径，供 MainWindow 在 video_loaded 时调用。"""
        self._video_path = path
        self._schedule_validation()

    def _schedule_validation(self) -> None:
        """启动 300ms 防抖 timer，避免频繁校验。"""
        self._validation_timer.start()

    def _do_validation(self) -> None:
        """执行全部校验，更新图标状态和汇总标签，emit validation_changed 信号。"""
        config = self._collect_config()
        if config is None:
            return

        video_path = self._video_path
        if video_path is not None and video_path.exists():
            result = validate_all(config, video_path)
        else:
            result = validate_config_only(config)

        # 分类错误到各区块
        asr_errors = [e for e in result.errors if e.stage == "asr"]
        trans_errors = [e for e in result.errors if e.stage == "translation"]
        tts_errors = [e for e in result.errors if e.stage == "tts"]

        # 更新 3 个校验图标
        self._set_icon_state(
            self._asr_status_icon,
            passed=len(asr_errors) == 0,
            tooltip=self._build_tooltip(asr_errors),
        )
        self._set_icon_state(
            self._translation_status_icon,
            passed=len(trans_errors) == 0,
            tooltip=self._build_tooltip(trans_errors),
        )
        self._set_icon_state(
            self._tts_status_icon,
            passed=len(tts_errors) == 0,
            tooltip=self._build_tooltip(tts_errors),
        )

        # 更新汇总标签
        self._update_validation_summary(result.errors)

        self.validation_changed.emit(result.is_valid)

    def _build_tooltip(self, errors: list[ValidationError]) -> str:
        """构建 tooltip 文本：message + suggestion。"""
        if not errors:
            return ""
        parts: list[str] = []
        for e in errors:
            parts.append(f"{e}\n→ {e.suggestion}")
        return "\n\n".join(parts)

    def _update_validation_summary(self, errors: list[ValidationError]) -> None:
        """更新校验汇总标签：全部通过显示绿色，有失败显示橙色。"""
        self._validation_summary_label.setVisible(True)
        if len(errors) == 0:
            self._validation_summary_label.setText("✅ 全部就绪")
            self._validation_summary_label.setStyleSheet(
                f"color: {COLOR_SUCCESS}; font-size: 11pt; font-weight: bold;"
            )
        else:
            self._validation_summary_label.setText(f"⚠️ {len(errors)} 项未通过")
            self._validation_summary_label.setStyleSheet(
                f"color: {COLOR_WARNING}; font-size: 11pt; font-weight: bold;"
            )

    def load_config(self) -> None:
        if self._config_path.exists():
            try:
                config = load_config(self._config_path)
            except Exception:
                config = get_preset("high_quality")
        else:
            config = get_preset("high_quality")
            save_config(config, self._config_path)
        self._file_config = config

        if config.preset == _CUSTOM_KEY:
            self._last_preset_key = "high_quality"
        else:
            self._last_preset_key = config.preset

        self._fill_from_config(config)
        self.refresh_schemes()
        self._schedule_validation()

    def get_config(self) -> AppConfig:
        """返回当前面板配置的深拷贝。

        如果面板控件状态无法构建有效配置（_collect_config 返回 None），
        退回使用"高质量"预设。

        Returns:
            AppConfig: 当前配置的深拷贝，修改返回值不影响面板状态。
        """
        config = self._collect_config()
        if config is None:
            config = get_preset("high_quality")
        return config.model_copy(deep=True)

    def _browse_directory(self, line_edit: QLineEdit) -> None:
        current = line_edit.text()
        start_dir = current if current and Path(current).exists() else str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "选择模型目录", start_dir)
        if path:
            line_edit.setText(path)

    def _toggle_api_key_visibility(self) -> None:
        if self._api_key_input.echoMode() == QLineEdit.EchoMode.Password:
            self._api_key_input.setEchoMode(QLineEdit.EchoMode.Normal)
            self._api_key_toggle.setText("隐藏")
        else:
            self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
            self._api_key_toggle.setText("显示")

    # --- 方案管理 ---

    def refresh_schemes(self) -> None:
        """刷新已保存方案下拉框，重新加载方案列表并恢复之前选中项。"""
        self._scheme_combo.blockSignals(True)
        current_data = self._scheme_combo.currentData()
        self._scheme_combo.clear()
        self._scheme_combo.addItem("（无）", "")
        for name in self._scheme_mgr.list_schemes():
            self._scheme_combo.addItem(name, name)
        idx = self._scheme_combo.findData(current_data)
        self._scheme_combo.setCurrentIndex(max(idx, 0))
        self._scheme_combo.blockSignals(False)

    def _on_scheme_selected(self, index: int) -> None:
        name = self._scheme_combo.itemData(index)
        if not name:
            return
        try:
            config = self._scheme_mgr.load_scheme(name)
            current_api_key = self._api_key_input.text()
            self._fill_from_config(config)
            if current_api_key:
                self._api_key_input.setText(current_api_key)
            self._on_config_changed()
        except ConfigError as e:
            QMessageBox.warning(self, "加载方案失败", f"{e}\n\n建议: {e.suggestion}")

    def _save_current_scheme(self) -> None:
        name, ok = QInputDialog.getText(self, "保存方案", "方案名称:")
        if not ok or not name:
            return
        name = name.strip()
        if not name or not _SCHEME_NAME_RE.match(name) or len(name) > 50:
            QMessageBox.warning(
                self,
                "名称无效",
                "方案名仅支持字母、数字、中文、下划线和横线，最长 50 字符。",
            )
            return
        existing = self._scheme_mgr.list_schemes()
        if name in existing:
            reply = QMessageBox.question(
                self,
                "覆盖方案",
                f"方案 '{name}' 已存在，是否覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        config = self.get_config()
        self._scheme_mgr.save_scheme(name, config)
        self.refresh_schemes()
        idx = self._scheme_combo.findData(name)
        if idx >= 0:
            self._scheme_combo.setCurrentIndex(idx)

    def _delete_selected_scheme(self) -> None:
        name = self._scheme_combo.currentData()
        if not name:
            return
        reply = QMessageBox.question(
            self,
            "删除方案",
            f"确定要删除方案 '{name}' 吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._scheme_mgr.delete_scheme(name)
            self.refresh_schemes()
        except ConfigError as e:
            QMessageBox.warning(self, "删除失败", str(e))

    def _import_scheme(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "导入方案",
            str(Path.home()),
            "YAML 文件 (*.yaml *.yml)",
        )
        if not path:
            return
        source = Path(path)
        name = source.stem.strip()
        if not name or not _SCHEME_NAME_RE.match(name) or len(name) > 50:
            QMessageBox.warning(
                self,
                "名称无效",
                f"文件名 '{source.stem}' 不符合方案命名规则。\n"
                "方案名仅支持字母、数字、中文、下划线和横线，最长 50 字符。",
            )
            return
        existing = self._scheme_mgr.list_schemes()
        if name in existing:
            reply = QMessageBox.question(
                self,
                "覆盖方案",
                f"方案 '{name}' 已存在，是否覆盖？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        try:
            self._scheme_mgr.import_scheme(source, name)
            self.refresh_schemes()
            idx = self._scheme_combo.findData(name)
            if idx >= 0:
                self._scheme_combo.setCurrentIndex(idx)
        except ConfigError as e:
            QMessageBox.warning(
                self,
                "导入失败",
                f"文件: {source.name}\n原因: {e}\n建议: {e.suggestion}",
            )

    def _export_scheme(self) -> None:
        name = self._scheme_combo.currentData()
        if not name:
            QMessageBox.information(self, "导出方案", "请先选择一个已保存的方案。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self,
            "导出方案",
            f"{name}.yaml",
            "YAML 文件 (*.yaml)",
        )
        if not path:
            return
        try:
            self._scheme_mgr.export_scheme(name, Path(path))
        except ConfigError as e:
            QMessageBox.warning(self, "导出失败", str(e))
