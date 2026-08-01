from PyQt6.QtWidgets import QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QWidget, QMenu
from PyQt6.QtCore import Qt, pyqtSignal


class ModpackCard(QFrame):
    install_clicked = pyqtSignal(object)
    play_clicked = pyqtSignal(object)
    connect_clicked = pyqtSignal(object, object)
    settings_clicked = pyqtSignal(object)
    delete_clicked = pyqtSignal(object)

    def __init__(self, modpack: dict, installed: bool = False, game_running: bool = False, parent=None):
        super().__init__(parent)
        self.modpack = modpack
        self._installed = installed
        self._game_running = game_running
        self._servers = []

        self.setObjectName("ModpackCard")
        layout = QVBoxLayout(self)
        layout.setSpacing(6)
        layout.setContentsMargins(14, 12, 14, 12)

        header = QHBoxLayout()
        icon = QLabel(modpack.get("name", "?")[0].upper(), self)
        icon.setObjectName("ModpackIcon")
        icon.setFixedSize(36, 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(icon)

        info = QVBoxLayout()
        info.setSpacing(1)
        name = QLabel(modpack.get("name", "Unknown"), self)
        name.setObjectName("ModpackName")
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
        meta_label.setObjectName("ModpackMeta")
        info.addWidget(meta_label)
        header.addLayout(info, 1)
        layout.addLayout(header)

        if modpack.get("description"):
            desc = QLabel(modpack["description"], self)
            desc.setObjectName("ModpackDesc")
            desc.setWordWrap(True)
            desc.setMaximumHeight(36)
            layout.addWidget(desc)

        self.servers_container = QVBoxLayout()
        self.servers_container.setSpacing(4)
        layout.addLayout(self.servers_container)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self.primary_btn = QPushButton(self)
        self.primary_btn.clicked.connect(self._on_primary_clicked)
        btn_row.addWidget(self.primary_btn)

        self.menu_btn = QPushButton("⋮", self)
        self.menu_btn.setObjectName("CardMenuButton")
        self.menu = QMenu(self)
        self.menu_btn.setMenu(self.menu)
        btn_row.addWidget(self.menu_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._update_primary(installed)
        self._build_menu(installed)

    @staticmethod
    def _repolish(widget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _on_primary_clicked(self):
        if self._installed:
            self.play_clicked.emit(self.modpack)
        else:
            self.install_clicked.emit(self.modpack)

    def _update_primary(self, installed: bool):
        self.primary_btn.setText("Play" if installed else "Install")
        self.primary_btn.setObjectName("PlayButton" if installed else "InstallButton")
        self.primary_btn.setEnabled(not self._game_running if installed else True)
        self._repolish(self.primary_btn)

    def _build_menu(self, installed: bool):
        self.menu.clear()
        self.menu.addAction("Settings", lambda: self.settings_clicked.emit(self.modpack))
        if installed:
            self.menu.addAction("Reinstall", lambda: self.install_clicked.emit(self.modpack))
            self.menu.addAction("Delete", lambda: self.delete_clicked.emit(self.modpack))

    def set_installed(self, installed: bool, game_running: bool = False):
        self._installed = installed
        self._game_running = game_running
        self._update_primary(installed)
        self._build_menu(installed)
        if self._servers:
            self.set_servers(self._servers)

    def set_servers(self, servers: list):
        self._servers = servers or []
        while self.servers_container.count():
            item = self.servers_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        if not self._servers:
            return

        header = QLabel("Servers", self)
        header.setObjectName("ServerHeader")
        self.servers_container.addWidget(header)

        for s in self._servers:
            row = QWidget(self)
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            label = QLabel(self._server_text(s), row)
            label.setObjectName("ServerLabel")
            label.setProperty("status", self._server_status(s))
            self._repolish(label)
            h.addWidget(label)
            h.addStretch()

            banned = bool(s.get("banned"))
            btn = QPushButton("Banned" if banned else "Connect", row)
            btn.setObjectName("ServerButton")
            can_connect = bool(s.get("online")) and not self._game_running and not banned
            btn.setEnabled(can_connect)
            btn.clicked.connect(lambda checked=False, srv=s: self.connect_clicked.emit(self.modpack, srv))
            h.addWidget(btn)
            self.servers_container.addWidget(row)

    def _server_text(self, s: dict) -> str:
        name = s.get("name") or "Server"
        if s.get("banned"):
            text = f"{name}: BANNED"
            expires = s.get("ban_expires")
            if expires:
                text += f" (until {expires})"
            return text
        if s.get("running") and not s.get("online"):
            return f"{name}: starting..."
        if s.get("online"):
            parts = [f"{name}: Online"]
            ping = s.get("latency_ms")
            if ping is not None:
                parts.append(f"{ping} ms")
            po = s.get("players_online")
            pm = s.get("players_max")
            if po is not None:
                parts.append(f"{po}/{pm} players")
            ver = s.get("version")
            if ver:
                parts.append(ver)
            return "  |  ".join(parts)
        return f"{name}: Offline"

    def _server_status(self, s: dict) -> str:
        if s.get("banned"):
            return "banned"
        if s.get("running") and not s.get("online"):
            return "starting"
        if s.get("online"):
            return "online"
        return "offline"
