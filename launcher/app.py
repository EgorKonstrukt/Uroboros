import sys
from pathlib import Path

from PyQt6.QtWidgets import QApplication

from launcher.config import LauncherConfig
from launcher.utils.storage import ensure_dirs
from launcher.ui.main_window import MainWindow


class UroborosApplication:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Uroboros")
        self.app.setOrganizationName("Uroboros")

        ensure_dirs()
        self.config = LauncherConfig.load()

        self._load_theme()

        self.main_window = MainWindow(self.config)
        self.main_window.setWindowTitle("Uroboros")
        self.main_window.resize(self.config.window_width, self.config.window_height)
        self.main_window.show()

        self.app.aboutToQuit.connect(self._cleanup)

    def _load_theme(self):
        theme_path = Path(__file__).parent / "theme.qss"
        if theme_path.exists():
            with open(theme_path, "r", encoding="utf-8") as f:
                self.app.setStyleSheet(f.read())

    def _cleanup(self):
        self.main_window.cleanup()

    def run(self):
        return self.app.exec()
