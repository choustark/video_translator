import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMainWindow

from src.gui.config_panel import ConfigPanel

CONFIG_PATH = Path("config.yaml")


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = QMainWindow()
    window.setWindowTitle("video_translator")
    window.resize(800, 600)
    window.setMinimumSize(640, 480)

    config_panel = ConfigPanel(CONFIG_PATH, window)
    config_panel.load_config()
    window.setCentralWidget(config_panel)

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
