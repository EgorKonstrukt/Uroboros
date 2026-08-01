from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtGui import QCloseEvent

from launcher.config import LauncherConfig
from launcher.ui.widgets.console import ConsoleWidget


class ConsoleWindow(QWidget):
    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setObjectName("ConsoleWindow")
        self.setWindowTitle("Uroboros Console")
        self._restore_geometry()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self.console = ConsoleWidget(self)
        layout.addWidget(self.console)

    def _restore_geometry(self):
        self.resize(self.config.console_width, self.config.console_height)
        if self.config.console_x >= 0 and self.config.console_y >= 0:
            self.move(self.config.console_x, self.config.console_y)

    def _save_geometry(self):
        geo = self.geometry()
        self.config.console_width = geo.width()
        self.config.console_height = geo.height()
        self.config.console_x = geo.x()
        self.config.console_y = geo.y()
        self.config.save()

    def closeEvent(self, event: QCloseEvent):
        self._save_geometry()
        super().closeEvent(event)

    def append(self, text: str):
        self.console.append(text)

    def clear(self):
        self.console.clear()
