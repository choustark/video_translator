import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.gui.main_window import MainWindow

CONFIG_PATH = Path("config.yaml")


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = MainWindow(CONFIG_PATH)
    window.load_config()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
