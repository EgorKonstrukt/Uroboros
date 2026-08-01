from PyQt6.QtWidgets import QTextEdit, QWidget, QVBoxLayout, QPushButton, QHBoxLayout
from PyQt6.QtCore import pyqtSignal, Qt, QTimer


class ConsoleWidget(QWidget):
    clear_requested = pyqtSignal()
    append_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        toolbar = QHBoxLayout()
        clear_btn = QPushButton("Clear")
        clear_btn.setObjectName("ConsoleClearButton")
        clear_btn.clicked.connect(self.clear)
        toolbar.addStretch()
        toolbar.addWidget(clear_btn)

        self.output = QTextEdit(self)
        self.output.setObjectName("ConsoleOutput")
        self.output.setReadOnly(True)

        self.append_requested.connect(self._do_append)

        layout.addLayout(toolbar)
        layout.addWidget(self.output)

    def _do_append(self, text: str):
        self.output.append(text)
        sb = self.output.verticalScrollBar()
        if sb:
            sb.setValue(sb.maximum())

    def append(self, text: str):
        self.append_requested.emit(text)

    def clear(self):
        self.output.clear()
