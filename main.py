import logging
import logging.handlers
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow

_PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = _PROJECT_ROOT / "config.yaml"
LOG_DIR = _PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "video_translator.log"
_MAX_BYTES = 10 * 1024 * 1024  # 10MB
_BACKUP_COUNT = 5

# 管道分隔格式：timestamp | level | 已有消息（stage | status | key=value）
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def _setup_logging() -> None:
    """配置日志：RotatingFileHandler(10MB×5) 写文件，StreamHandler(WARNING) 输出控制台。"""
    LOG_DIR.mkdir(exist_ok=True)

    root_logger = logging.getLogger("video_translator")
    root_logger.setLevel(logging.INFO)

    # 避免重复添加 handler（hot-reload 场景）
    if root_logger.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=_MAX_BYTES, backupCount=_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)


def main() -> None:
    _setup_logging()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow(CONFIG_PATH)
    window.load_config()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
