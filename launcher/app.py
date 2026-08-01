import sys

from PyQt6.QtWidgets import QApplication

from launcher.config import LauncherConfig
from launcher.theme import load_theme
from launcher.utils.storage import ensure_dirs
from launcher.ui.main_window import MainWindow


class UroborosApplication:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Uroboros")
        self.app.setOrganizationName("Uroboros")

        self.config = LauncherConfig.load()
        ensure_dirs()

        self._load_theme()

        self.main_window = MainWindow(self.config)
        self.main_window.setWindowTitle("Uroboros")
        self.main_window.show()

        self.app.aboutToQuit.connect(self._cleanup)

    def _load_theme(self):
        self.app.setStyleSheet(load_theme(self.config.theme_mode))

    def _cleanup(self):
        self.main_window.cleanup()

    def run(self):
        return self.app.exec()
