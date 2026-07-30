from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal


class ModpackCard(QFrame):
    install_clicked = pyqtSignal(object)
    play_clicked = pyqtSignal(object)

    def __init__(self, modpack: dict, installed: bool = False, game_running: bool = False, parent=None):
        super().__init__(parent)
        self.modpack = modpack
        self._installed = installed
        self._game_running = game_running

        self.setObjectName("ModpackCard")
        self.setStyleSheet("""
            QFrame#ModpackCard {
                background: #1e1e2e; border: 1px solid #313244;
                border-radius: 8px; padding: 0px;
            }
            QFrame#ModpackCard:hover { border-color: #89b4fa; }
        """)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(14, 12, 14, 12)

        header = QHBoxLayout()
        icon = QLabel(modpack.get("name", "?")[0].upper(), self)
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background: #89b4fa; color: #111; font-weight: bold; font-size: 16px; border-radius: 6px;")
        header.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(1)
        name = QLabel(modpack.get("name", "Unknown"), self)
        name.setStyleSheet("font-weight: bold; font-size: 14px; color: #cdd6f4;")
        info.addWidget(name)

        mc = modpack.get("mc_version", "")
        loader = modpack.get("loader", "")
        lv = modpack.get("loader_version", "")
        meta_parts = [f"v{modpack.get('version', '?')}"]
        if mc:
            meta_parts.append(f"MC {mc}")
        if loader:
            meta_parts.append(f"{loader} {lv or ''}")
        meta_parts.append(f"{modpack.get('file_count', 0)} files")
        meta_label = QLabel("  |  ".join(meta_parts), self)
        meta_label.setStyleSheet("font-size: 12px; color: #6c7086;")
        info.addWidget(meta_label)
        header.addLayout(info, 1)
        layout.addLayout(header)

        if modpack.get("description"):
            desc = QLabel(modpack["description"], self)
            desc.setWordWrap(True)
            desc.setStyleSheet("font-size: 12px; color: #a6adc8; margin-top: 2px;")
            desc.setMaximumHeight(36)
            layout.addWidget(desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.install_btn = QPushButton("Install" if not installed else "Reinstall", self)
        self.install_btn.setStyleSheet(self._btn_style("#89b4fa", "#111", "#b4d0fb"))
        self.install_btn.clicked.connect(lambda: self.install_clicked.emit(self.modpack))
        btn_row.addWidget(self.install_btn)

        self.play_btn = QPushButton("Play", self)
        self.play_btn.setEnabled(installed and not game_running)
        self.play_btn.setStyleSheet(
            self._btn_style("#a6e3a1", "#111", "#b8f0b5") if self.play_btn.isEnabled()
            else self._btn_style("#45475a", "#6c7086")
        )
        self.play_btn.clicked.connect(lambda: self.play_clicked.emit(self.modpack))
        btn_row.addWidget(self.play_btn)

        if installed:
            badge = QLabel("Installed", self)
            badge.setStyleSheet("color: #a6e3a1; font-size: 11px; font-weight: bold; padding: 4px 8px; border: 1px solid #a6e3a1; border-radius: 4px;")
            btn_row.addWidget(badge)

        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _btn_style(self, bg, fg, hover_bg=None):
        base = f"background: {bg}; color: {fg}; border: none; border-radius: 4px; padding: 6px 16px; font-weight: bold; font-size: 12px;"
        if hover_bg:
            base += f" QPushButton:hover {{ background: {hover_bg}; }}"
        return base

    def set_installed(self, installed: bool, game_running: bool = False):
        self._installed = installed
        self._game_running = game_running
        self.install_btn.setText("Install" if not installed else "Reinstall")
        self.play_btn.setEnabled(installed and not game_running)
        if installed and not game_running:
            self.play_btn.setStyleSheet(self._btn_style("#a6e3a1", "#111", "#b8f0b5"))
        else:
            self.play_btn.setStyleSheet(self._btn_style("#45475a", "#6c7086"))
