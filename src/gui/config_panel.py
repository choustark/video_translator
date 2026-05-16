import re
from pathlib import Path
from typing import Literal, cast

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from src.config import (
    PRESETS,
    AppConfig,
    ASRConfig,
    TranslationConfig,
    TTSConfig,
    get_preset,
    load_config,
    save_config,
)
from src.exceptions import ConfigError
from src.gui.constants import (
    COLOR_PRIMARY_TEXT,
    COLOR_SECONDARY_BG,
    FONT_SECTION_TITLE,
    SPACING_FORM_ITEM,
    SPACING_SECTION,
    SPACING_WIDGET,
)
from src.scheme_manager import SchemeManager

_PRESET_DISPLAY: dict[str, str] = {
    "high_quality": "高质量",
    "balanced": "均衡",
    "fast": "快速",
    "offline": "全离线",
}
_PRESET_KEYS: dict[str, str] = {v: k for k, v in _PRESET_DISPLAY.items()}

_TRANSLATION_DISPLAY: dict[str, str] = {
    "glm": "GLM",
    "deepseek": "DeepSeek",
    "openai": "OpenAI",
    "deepl": "DeepL",
    "nllb": "本地 NLLB",
}
_TRANSLATION_KEYS: dict[str, str] = {v: k for k, v in _TRANSLATION_DISPLAY.items()}

_SCHEME_NAME_RE = re.compile(r'^[\w一-鿿-]+$')
_SCHEMES_DIR = Path.home() / ".video_translator" / "schemes"


class ConfigPanel(QWidget):
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
        self._scheme_mgr = SchemeManager(_SCHEMES_DIR)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._do_save)

        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(SPACING_SECTION)

        # 预设方案
        preset_form = self._make_form()

        self._preset_combo = QComboBox()
        for key in _PRESET_DISPLAY:
            self._preset_combo.addItem(_PRESET_DISPLAY[key], key)
        preset_form.addRow("预设方案", self._preset_combo)
        layout.addLayout(preset_form)

        # 已保存方案
        scheme_form = self._make_form()
        self._scheme_combo = QComboBox()
        self._scheme_combo.addItem("（无）", "")
        scheme_form.addRow("已保存方案", self._scheme_combo)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(SPACING_WIDGET)
        self._btn_save_scheme = QPushButton("保存")
        self._btn_delete_scheme = QPushButton("删除")
        self._btn_import_scheme = QPushButton("导入")
        self._btn_export_scheme = QPushButton("导出")
        for btn in (self._btn_save_scheme, self._btn_delete_scheme,
                    self._btn_import_scheme, self._btn_export_scheme):
            btn_row.addWidget(btn)
        scheme_form.addRow("", btn_row)
        layout.addLayout(scheme_form)

        # ASR 配置区块
        layout.addWidget(self._section_title("ASR 语音识别"))
        asr_form = self._make_form()

        self._asr_path_input = QLineEdit()
        self._asr_path_input.setReadOnly(True)
        self._asr_path_input.setPlaceholderText("选择模型目录...")
        asr_path_btn = QPushButton("浏览...")
        asr_path_row = QHBoxLayout()
        asr_path_row.addWidget(self._asr_path_input)
        asr_path_row.addWidget(asr_path_btn)
        asr_path_btn.clicked.connect(lambda: self._browse_directory(self._asr_path_input))
        asr_form.addRow("模型路径", asr_path_row)
        layout.addLayout(asr_form)

        # 翻译配置区块
        layout.addWidget(self._section_title("翻译"))
        trans_form = self._make_form()

        self._translation_combo = QComboBox()
        for key in _TRANSLATION_DISPLAY:
            self._translation_combo.addItem(_TRANSLATION_DISPLAY[key], key)
        trans_form.addRow("翻译后端", self._translation_combo)

        self._api_key_input = QLineEdit()
        self._api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._api_key_input.setPlaceholderText("输入 API Key...")
        self._api_key_toggle = QPushButton("显示")
        self._api_key_toggle.setFixedWidth(50)
        self._api_key_toggle.clicked.connect(self._toggle_api_key_visibility)
        api_key_row = QHBoxLayout()
        api_key_row.addWidget(self._api_key_input)
        api_key_row.addWidget(self._api_key_toggle)
        trans_form.addRow("API Key", api_key_row)
        layout.addLayout(trans_form)

        # TTS 配置区块
        layout.addWidget(self._section_title("语音合成"))
        tts_form = self._make_form()

        self._tts_path_input = QLineEdit()
        self._tts_path_input.setReadOnly(True)
        self._tts_path_input.setPlaceholderText("选择模型目录...")
        tts_path_btn = QPushButton("浏览...")
        tts_path_row = QHBoxLayout()
        tts_path_row.addWidget(self._tts_path_input)
        tts_path_row.addWidget(tts_path_btn)
        tts_path_btn.clicked.connect(lambda: self._browse_directory(self._tts_path_input))
        tts_form.addRow("模型路径", tts_path_row)

        self._speed_slider = QSlider(Qt.Orientation.Horizontal)
        self._speed_slider.setRange(5, 20)
        self._speed_slider.setValue(10)
        self._speed_slider.setTickInterval(1)
        self._speed_label = QLabel("1.0x")
        self._speed_label.setFixedWidth(40)
        speed_row = QHBoxLayout()
        speed_row.addWidget(self._speed_slider)
        speed_row.addWidget(self._speed_label)
        tts_form.addRow("语速", speed_row)

        layout.addLayout(tts_form)
        layout.addStretch()

    def _section_title(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: {FONT_SECTION_TITLE}pt; font-weight: bold;"
            f" color: {COLOR_PRIMARY_TEXT};"
            f" background-color: {COLOR_SECONDARY_BG};"
            f" padding: {SPACING_FORM_ITEM // 2}px;"
        )
        return label

    def _connect_signals(self) -> None:
        self._preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self._asr_path_input.textChanged.connect(self._on_config_changed)
        self._translation_combo.currentIndexChanged.connect(self._on_config_changed)
        self._api_key_input.textChanged.connect(self._on_config_changed)
        self._tts_path_input.textChanged.connect(self._on_config_changed)
        self._speed_slider.valueChanged.connect(self._on_speed_changed)
        self._scheme_combo.currentIndexChanged.connect(self._on_scheme_selected)
        self._btn_save_scheme.clicked.connect(self._save_current_scheme)
        self._btn_delete_scheme.clicked.connect(self._delete_selected_scheme)
        self._btn_import_scheme.clicked.connect(self._import_scheme)
        self._btn_export_scheme.clicked.connect(self._export_scheme)

    def _on_speed_changed(self, value: int) -> None:
        self._speed_label.setText(f"{value / 10:.1f}x")
        self._on_config_changed()

    def _on_preset_changed(self, _index: int) -> None:
        key = self._preset_combo.currentData()
        if not key:
            return
        current_api_key = self._api_key_input.text()
        config = get_preset(key)
        self._fill_from_config(config)
        if current_api_key:
            self._api_key_input.setText(current_api_key)
        self._on_config_changed()

    def _fill_from_config(self, config: AppConfig) -> None:
        self._preset_combo.blockSignals(True)
        self._asr_path_input.blockSignals(True)
        self._translation_combo.blockSignals(True)
        self._api_key_input.blockSignals(True)
        self._tts_path_input.blockSignals(True)
        self._speed_slider.blockSignals(True)

        preset_idx = self._preset_combo.findData(config.preset)
        if preset_idx >= 0:
            self._preset_combo.setCurrentIndex(preset_idx)

        self._asr_path_input.setText(config.asr.model_path)

        trans_idx = self._translation_combo.findData(config.translation.engine)
        if trans_idx >= 0:
            self._translation_combo.setCurrentIndex(trans_idx)

        self._api_key_input.setText(config.translation.api_key)
        self._tts_path_input.setText(config.tts.model_path)
        self._speed_slider.setValue(int(config.tts.speed * 10))
        self._speed_label.setText(f"{config.tts.speed:.1f}x")

        self._preset_combo.blockSignals(False)
        self._asr_path_input.blockSignals(False)
        self._translation_combo.blockSignals(False)
        self._api_key_input.blockSignals(False)
        self._tts_path_input.blockSignals(False)
        self._speed_slider.blockSignals(False)

    def _on_config_changed(self) -> None:
        self._save_timer.start()

    def _do_save(self) -> None:
        config = self._collect_config()
        if config is not None:
            save_config(config, self._config_path)

    def _collect_config(self) -> AppConfig | None:
        preset_key = str(self._preset_combo.currentData() or "high_quality")
        trans_key = cast(
            Literal["glm", "deepseek", "openai", "deepl", "nllb"],
            str(self._translation_combo.currentData() or "glm"),
        )
        try:
            return AppConfig(
                preset=preset_key,
                asr=ASRConfig(
                    engine=PRESETS[preset_key].asr.engine,
                    model_path=self._asr_path_input.text(),
                    language="en",
                ),
                translation=TranslationConfig(
                    engine=trans_key,
                    api_key=self._api_key_input.text(),
                    source_lang="EN",
                    target_lang="ZH",
                ),
                tts=TTSConfig(
                    engine=PRESETS[preset_key].tts.engine,
                    model_path=self._tts_path_input.text(),
                    voice="default",
                    speed=self._speed_slider.value() / 10,
                ),
            )
        except Exception:
            return None

    def load_config(self) -> None:
        if self._config_path.exists():
            try:
                config = load_config(self._config_path)
            except Exception:
                config = get_preset("high_quality")
        else:
            config = get_preset("high_quality")
            save_config(config, self._config_path)
        self._fill_from_config(config)
        self.refresh_schemes()

    def get_config(self) -> AppConfig:
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
                self, "名称无效",
                "方案名仅支持字母、数字、中文、下划线和横线，最长 50 字符。",
            )
            return
        existing = self._scheme_mgr.list_schemes()
        if name in existing:
            reply = QMessageBox.question(
                self, "覆盖方案",
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
            self, "删除方案",
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
            self, "导入方案", str(Path.home()), "YAML 文件 (*.yaml *.yml)",
        )
        if not path:
            return
        source = Path(path)
        name = source.stem.strip()
        if not name or not _SCHEME_NAME_RE.match(name) or len(name) > 50:
            QMessageBox.warning(
                self, "名称无效",
                f"文件名 '{source.stem}' 不符合方案命名规则。\n"
                "方案名仅支持字母、数字、中文、下划线和横线，最长 50 字符。",
            )
            return
        existing = self._scheme_mgr.list_schemes()
        if name in existing:
            reply = QMessageBox.question(
                self, "覆盖方案",
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
                self, "导入失败",
                f"文件: {source.name}\n原因: {e}\n建议: {e.suggestion}",
            )

    def _export_scheme(self) -> None:
        name = self._scheme_combo.currentData()
        if not name:
            QMessageBox.information(self, "导出方案", "请先选择一个已保存的方案。")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出方案", f"{name}.yaml", "YAML 文件 (*.yaml)",
        )
        if not path:
            return
        try:
            self._scheme_mgr.export_scheme(name, Path(path))
        except ConfigError as e:
            QMessageBox.warning(self, "导出失败", str(e))
