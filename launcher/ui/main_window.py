import hashlib
import shutil

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QProgressBar, QMenu, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, QObject, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap

from launcher.api.api_manager import APIManager
from launcher.api.auth import YggdrasilSession, YggdrasilAuth
from launcher.config import LauncherConfig, cache_projects, load_cached_projects, cached_projects_stale
from launcher.ui.settings_dialog import SettingsDialog
from launcher.ui.login_dialog import LoginDialog
from launcher.game.starter import GameStarter
from launcher.game.version_manager import VersionManager
from launcher.game.assets import AssetManager
from launcher.game.java_manager import JavaManager
from launcher.ui.console_window import ConsoleWindow
from launcher.ui.widgets.modpack_card import ModpackCard
from launcher.utils.storage import get_modpack_dir
from launcher.utils.async_worker import run_async
from launcher.utils.progress import CancelledError
from launcher.theme import load_theme


INSTALL_MARKER = "installed.marker"


def _is_modpack_installed(mp_dir) -> bool:
    if not mp_dir.exists():
        return False
    if (mp_dir / INSTALL_MARKER).exists():
        return True
    return any(p for p in mp_dir.iterdir() if p.name != INSTALL_MARKER)


class _GameSignals(QObject):
    exited = pyqtSignal()
    progress = pyqtSignal(object)


class MainWindow(QWidget):
    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.api = APIManager(config.api_url, verify_ssl=config.verify_ssl)
        self.project = None
        self.modpacks = []
        self.modpack_cards = []
        self.servers = []
        self.bans = {"global": None, "servers": []}
        self._game_running = False
        self._cancel_requested = False
        self.starter = GameStarter()
        self.version_manager = VersionManager()

        self._setup_ui()
        self._restore_geometry()
        self._game_signals = _GameSignals()
        self._game_signals.exited.connect(self._on_game_exited)
        self._game_signals.progress.connect(self._apply_progress)
        self._load_project()
        self._update_account_button()
        self._server_timer = QTimer(self)
        self._server_timer.timeout.connect(self._load_servers)
        self._server_timer.start(30000)

    def _setup_ui(self):
        self.setObjectName("MainWindow")
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        header.setContentsMargins(20, 12, 20, 12)
        self.title_label = QLabel("Uroboros", self)
        self.title_label.setObjectName("TitleLabel")
        header.addWidget(self.title_label)
        header.addStretch()
        self.account_btn = QPushButton("Login", self)
        self.account_btn.setObjectName("AccountButton")
        self.account_btn.setIconSize(QSize(24, 24))
        self.account_btn.clicked.connect(self._on_account_clicked)
        header.addWidget(self.account_btn)
        self.refresh_btn = QPushButton("Refresh", self)
        self.refresh_btn.setObjectName("RefreshButton")
        self.refresh_btn.clicked.connect(self._refresh_all)
        header.addWidget(self.refresh_btn)
        self.settings_btn = QPushButton("Settings", self)
        self.settings_btn.setObjectName("SettingsButton")
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)
        layout.addLayout(header)

        self.banned_label = QLabel("", self)
        self.banned_label.setObjectName("BannedLabel")
        self.banned_label.setWordWrap(True)
        self.banned_label.setVisible(False)
        layout.addWidget(self.banned_label)

        scroll = QScrollArea(self)
        scroll.setObjectName("MainScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        content.setObjectName("MainContent")
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(8)
        self.content_layout.setContentsMargins(20, 8, 20, 20)

        self.loading_label = QLabel("Loading project...", content)
        self.loading_label.setObjectName("LoadingLabel")
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(self.loading_label)

        self.project_section = QWidget(content)
        self.project_section.setObjectName("ProjectSection")
        self.project_section.setVisible(False)
        ps_layout = QVBoxLayout(self.project_section)
        ps_layout.setSpacing(8)
        ps_layout.setContentsMargins(0, 0, 0, 0)

        self.desc_label = QLabel("", self.project_section)
        self.desc_label.setObjectName("DescLabel")
        self.desc_label.setWordWrap(True)
        ps_layout.addWidget(self.desc_label)

        self.modpacks_header = QLabel("Modpacks", self.project_section)
        self.modpacks_header.setObjectName("ModpacksHeader")
        ps_layout.addWidget(self.modpacks_header)

        self.cards_widget = QWidget(self.project_section)
        self.cards_widget.setObjectName("CardsWidget")
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setSpacing(8)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        ps_layout.addWidget(self.cards_widget)

        self.content_layout.addWidget(self.project_section)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.console_window = ConsoleWindow(self.config)
        self.console = self.console_window.console
        self._apply_console_mode()

        self.download_status = QWidget(self)
        self.download_status.setObjectName("DownloadStatus")
        ds_layout = QVBoxLayout(self.download_status)
        ds_layout.setContentsMargins(20, 8, 20, 8)
        ds_layout.setSpacing(4)

        self.status_label = QLabel("", self.download_status)
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ds_layout.addWidget(self.status_label)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.progress_bar = QProgressBar(self.download_status)
        self.progress_bar.setVisible(False)
        progress_row.addWidget(self.progress_bar, 1)
        self.cancel_btn = QPushButton("Cancel", self.download_status)
        self.cancel_btn.setObjectName("CancelButton")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_install)
        progress_row.addWidget(self.cancel_btn)
        ds_layout.addLayout(progress_row)

        self.detail_rows = {}
        self.details_widget = QWidget(self.download_status)
        self.details_widget.setObjectName("DetailsWidget")
        details_layout = QVBoxLayout(self.details_widget)
        details_layout.setContentsMargins(0, 0, 0, 0)
        details_layout.setSpacing(2)
        for key, name in (("phase", "Phase"), ("file", "File"), ("files", "Files"), ("size", "Size"), ("speed", "Speed")):
            row = QWidget(self.details_widget)
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            k = QLabel(name, row)
            k.setObjectName("DetailKey")
            k.setFixedWidth(52)
            v = QLabel("", row)
            v.setObjectName("DetailValue")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            row_layout.addWidget(k)
            row_layout.addWidget(v, 1)
            details_layout.addWidget(row)
            self.detail_rows[key] = (row, k, v)
        self.details_widget.setVisible(False)
        ds_layout.addWidget(self.details_widget)

        layout.addWidget(self.download_status)

    def _set_detail(self, key: str, text: str):
        row, k, v = self.detail_rows[key]
        v.setText(text)
        row.setVisible(bool(text))
        any_visible = any(not r.isHidden() for r, _, _ in self.detail_rows.values())
        self.details_widget.setVisible(any_visible)

    def _clear_details(self):
        for key in self.detail_rows:
            self._set_detail(key, "")

    def _apply_console_mode(self):
        if self.config.console_mode == "always":
            self.console_window.show()
        else:
            self.console_window.hide()

    def _restore_geometry(self):
        self.resize(self.config.window_width, self.config.window_height)
        if self.config.window_x >= 0 and self.config.window_y >= 0:
            self.move(self.config.window_x, self.config.window_y)

    def _save_geometry(self):
        geo = self.geometry()
        self.config.window_width = geo.width()
        self.config.window_height = geo.height()
        self.config.window_x = geo.x()
        self.config.window_y = geo.y()
        self.config.save()

    def closeEvent(self, event):
        self._save_geometry()
        self.console_window.close()
        super().closeEvent(event)

    def _load_project(self, force: bool = False):
        pid = self.config.project_id
        if not pid:
            self.loading_label.setText("No project configured. Open Settings and set a Project ID.")
            self.settings_btn.setText("Configure")
            return

        def do_fetch():
            if force:
                return self.api.get_project(pid), False
            try:
                return self.api.get_project(pid), False
            except Exception:
                cached = load_cached_projects()
                if cached and not cached_projects_stale(cached):
                    return cached, True
                raise

        def on_done(result):
            data, from_cache = result
            self.loading_label.setVisible(False)
            self.project_section.setVisible(True)
            self.project = {
                "id": data.get("id", pid),
                "name": data.get("name", ""),
                "description": data.get("description", ""),
                "brand_name": data.get("brand_name", ""),
                "primary_color": data.get("primary_color", "#6c63ff"),
            }
            self.modpacks = data.get("modpacks", [])
            if not from_cache:
                cache_projects(data)
                self.status_label.setText("")
            else:
                self.status_label.setText("Offline — showing cached data")
            self._populate_ui()

        def on_error(err):
            self.loading_label.setText(f"Failed to load project: {err}")

        run_async(do_fetch, on_done=on_done, on_error=on_error)

    def _populate_ui(self):
        p = self.project
        title = p.get("brand_name") or p.get("name") or "Uroboros"
        self.title_label.setText(title)
        color = p.get("primary_color", "#89b4fa")
        self.title_label.setStyleSheet(f"color: {color};")
        self.desc_label.setText(p.get("description", ""))
        self.status_label.setText("")
        self._render_cards()

    def _clear_cards(self):
        self.modpack_cards = []
        for i in reversed(range(self.cards_layout.count())):
            w = self.cards_layout.itemAt(i).widget()
            if w:
                w.deleteLater()

    def _render_cards(self):
        self._clear_cards()
        if not self.modpacks:
            no = QLabel("No modpacks available", self.cards_widget)
            no.setObjectName("EmptyLabel")
            no.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(no)
            return

        for m in self.modpacks:
            mp_dir = get_modpack_dir(self.project["id"], m["id"])
            installed = _is_modpack_installed(mp_dir)
            card = ModpackCard(m, installed=installed, game_running=self._game_running, parent=self.cards_widget)
            card.install_clicked.connect(self._on_install_clicked)
            card.play_clicked.connect(self._on_play_clicked)
            card.connect_clicked.connect(self._on_connect_clicked)
            card.settings_clicked.connect(self._on_modpack_settings_clicked)
            card.delete_clicked.connect(self._on_delete_clicked)
            self.cards_layout.addWidget(card)
            self.modpack_cards.append(card)
        self._apply_servers()
        self._load_servers()
        self._load_bans()

    def _load_servers(self):
        pid = self.config.project_id
        if not pid:
            return

        def do_fetch():
            return self.api.get_servers(pid)

        def on_done(servers):
            self.servers = servers
            self._apply_servers()

        run_async(do_fetch, on_done=on_done, on_error=lambda err: None)

    def _apply_servers(self):
        banned_by_id = {}
        for b in self.bans.get("servers", []):
            banned_by_id[b.get("instance_id") or ""] = b
        for card in self.modpack_cards:
            servers = [dict(s) for s in self.servers if s.get("modpack_id") == card.modpack.get("id")]
            for s in servers:
                ban = banned_by_id.get(s.get("id", ""))
                if ban:
                    s["banned"] = True
                    s["ban_expires"] = ban.get("expires_at", "")
            card.set_servers(servers)

    def _load_bans(self):
        uid = self.config.account_uuid
        if not uid:
            self.bans = {"global": None, "servers": []}
            self._update_ban_banner()
            self._apply_servers()
            return

        def do_fetch():
            return self.api.get_bans(uid)

        def on_done(data):
            self.bans = {
                "global": data.get("global"),
                "servers": data.get("servers", []),
            }
            self._update_ban_banner()
            self._apply_servers()

        def on_error(err):
            self.bans = {"global": None, "servers": []}
            self._update_ban_banner()

        run_async(do_fetch, on_done=on_done, on_error=on_error)

    def _update_ban_banner(self):
        global_ban = self.bans.get("global")
        server_bans = self.bans.get("servers", [])
        if not global_ban and not server_bans:
            self.banned_label.setVisible(False)
            return
        parts = []
        if global_ban:
            text = "You are banned from this project"
            if global_ban.get("reason"):
                text += f" — {global_ban['reason']}"
            if global_ban.get("expires_at"):
                text += f" (until {global_ban['expires_at']})"
            parts.append(text)
        if server_bans:
            names = []
            for b in server_bans:
                n = b.get("server_name") or b.get("instance_id") or "?"
                if b.get("expires_at"):
                    n += f" (until {b['expires_at']})"
                names.append(n)
            parts.append("You are banned on: " + ", ".join(names))
        self.banned_label.setText("\n".join(parts))
        self.banned_label.setVisible(True)

    def _refresh_all(self):
        self.status_label.setText("Refreshing...")
        self._load_project(force=True)
        self._load_servers()
        self._load_bans()

    def _on_install_clicked(self, modpack):
        self.current_modpack = modpack
        self._install()

    def _on_play_clicked(self, modpack):
        self.current_modpack = modpack
        self._play()

    def _on_connect_clicked(self, modpack, server):
        self.current_modpack = modpack
        self._play(
            server_address=server.get("address", ""),
            server_port=str(server.get("port", 25565)),
        )

    def _on_modpack_settings_clicked(self, modpack):
        from launcher.ui.modpack_settings_dialog import ModpackSettingsDialog
        dialog = ModpackSettingsDialog(self.config, self.project["id"], modpack, self)
        dialog.exec()

    def _on_delete_clicked(self, modpack):
        if self._game_running:
            self.status_label.setText("Cannot delete modpack while game is running")
            return
        mp_dir = get_modpack_dir(self.project["id"], modpack["id"])
        if not _is_modpack_installed(mp_dir):
            self._refresh_card_states()
            return
        name = modpack.get("name") or modpack.get("id") or "this modpack"
        answer = QMessageBox.question(
            self,
            "Delete modpack",
            f"Delete '{name}' and all its files? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(mp_dir, ignore_errors=True)
            key = f"{self.project['id']}:{modpack.get('id', '')}"
            if self.config.modpack_settings.pop(key, None):
                self.config.save()
            self.status_label.setText(f"Modpack '{name}' deleted")
        except Exception as e:
            self.status_label.setText(f"Delete failed: {e}")
        self._refresh_card_states()

    def _modpack_override(self, modpack_id: str) -> dict:
        if not self.project:
            return {}
        return dict(self.config.modpack_settings.get(f"{self.project['id']}:{modpack_id}", {}) or {})

    def _refresh_card_states(self):
        for card in self.modpack_cards:
            mp_dir = get_modpack_dir(self.project["id"], card.modpack["id"])
            installed = _is_modpack_installed(mp_dir)
            card.set_installed(installed, self._game_running)

    def _cancel_install(self):
        self._cancel_requested = True
        self.status_label.setText("Cancelling...")
        self.cancel_btn.setEnabled(False)

    def _install(self):
        m = self.current_modpack
        if not m:
            return
        version = m.get("mc_version", "")
        if not version:
            self.status_label.setText("Modpack has no MC version")
            return

        self._cancel_requested = False
        self.cancel_btn.setEnabled(True)
        self.status_label.setText("Installing...")
        self.progress_bar.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.progress_bar.setValue(0)

        def do_install():
            try:
                if self._cancel_requested:
                    return "cancelled"
                should_cancel = lambda: self._cancel_requested
                try:
                    m = self.api.get_modpack(self.project["id"], self.current_modpack["id"])
                except Exception:
                    pass

                vm = VersionManager()
                version = vm.install_loader(m.get("mc_version", ""), m.get("loader", ""), m.get("loader_version", ""), self._update_progress, should_cancel)
                if not vm.is_version_installed(version):
                    vm.download_version(version, self._update_progress, should_cancel)

                meta = vm.get_version_meta(version)
                if meta and meta.assets:
                    am = AssetManager()
                    am.download_assets(meta.assets, self._update_progress, should_cancel)

                mp_dir = get_modpack_dir(self.project["id"], m["id"])
                mp_dir.mkdir(parents=True, exist_ok=True)

                files = self.api.get_modpack_files(self.project["id"], m["id"])
                total = len(files)
                for i, f in enumerate(files):
                    if self._cancel_requested:
                        return "cancelled"
                    dest = mp_dir / f["name"]
                    expected_hash = f.get("sha256", "")
                    if dest.exists():
                        if expected_hash:
                            actual = hashlib.sha256(dest.read_bytes()).hexdigest()
                            if actual == expected_hash:
                                continue
                        elif dest.stat().st_size == f.get("size", 0):
                            continue
                    self.api.download_modpack_file(self.project["id"], m["id"], f["name"], dest)
                    if expected_hash:
                        actual = hashlib.sha256(dest.read_bytes()).hexdigest()
                        if actual != expected_hash:
                            raise IOError(f"Hash mismatch for {f['name']}")
                    self._update_progress(int((i + 1) / total * 100) if total > 0 else 100)
                mp_dir.joinpath(INSTALL_MARKER).write_text("installed by Uroboros launcher", encoding="utf-8")
                return True
            except CancelledError:
                return "cancelled"
            except Exception:
                return False

        def on_done(result):
            self.progress_bar.setVisible(False)
            self.cancel_btn.setVisible(False)
            self._clear_details()
            if result == "cancelled":
                self.status_label.setText("Installation cancelled")
            elif result:
                self.status_label.setText("Installation complete")
                self._refresh_card_states()
            else:
                self.status_label.setText("Installation failed")

        def on_error(err):
            self.progress_bar.setVisible(False)
            self.cancel_btn.setVisible(False)
            self._clear_details()
            self.status_label.setText(f"Install failed: {err}")

        run_async(do_install, on_done=on_done, on_error=on_error)

    def _update_progress(self, info):
        self._game_signals.progress.emit(info)

    def _apply_progress(self, info):
        if not isinstance(info, dict):
            self.progress_bar.setValue(int(info or 0))
            return
        phase = info.get("phase", "")
        current = info.get("current", 0)
        total = info.get("total", 0)
        speed = info.get("speed", 0)
        files_done = info.get("files_done")
        files_total = info.get("files_total")

        titles = {
            "client": "Downloading Minecraft client...",
            "library": "Downloading libraries...",
            "asset": "Downloading assets...",
            "assets_index": "Downloading asset index...",
            "logging": "Downloading logging config...",
            "java": "Downloading Java runtime...",
            "java_extract": "Extracting Java runtime...",
            "neoforge": "Installing NeoForge (patching client)...",
        }
        if phase in titles:
            self.status_label.setText(titles[phase])

        if phase == "client":
            pct = int(current / total * 100) if total else 0
        elif phase == "library":
            if files_total:
                frac = (current / total) if total else 0
                pct = int((files_done - 1 + frac) / files_total * 100)
            else:
                pct = 0
        elif phase == "asset":
            pct = int(files_done / files_total * 100) if files_total else 0
        elif phase == "java":
            pct = int(current / total * 100) if total else 0
        elif phase == "neoforge":
            pct = int(current / total * 100) if total else 0
        else:
            pct = 0
        self.progress_bar.setValue(max(0, min(100, pct)))

        phase_names = {
            "client": "Client",
            "library": "Libraries",
            "asset": "Assets",
            "assets_index": "Asset index",
            "logging": "Logging config",
            "java": "Java runtime",
            "java_extract": "Java extract",
            "neoforge": "NeoForge",
        }
        self._set_detail("phase", phase_names.get(phase, ""))
        self._set_detail("file", str(info.get("file", "")) if info.get("file") else "")
        if files_done is not None and files_total:
            self._set_detail("files", f"{files_done} / {files_total}")
        else:
            self._set_detail("files", "")
        if total:
            self._set_detail("size", f"{current / 1048576:.1f} / {total / 1048576:.1f} MB")
        elif current:
            self._set_detail("size", f"{current / 1048576:.1f} MB")
        else:
            self._set_detail("size", "")
        if speed:
            if speed >= 1048576:
                self._set_detail("speed", f"{speed / 1048576:.1f} MB/s")
            else:
                self._set_detail("speed", f"{speed / 1024:.0f} KB/s")
        else:
            self._set_detail("speed", "")

    def _make_offline_session(self):
        name = self.config.account_name.strip() or "Player"
        profile_uuid = hashlib.md5(f"OfflinePlayer:{name}".encode()).hexdigest()
        return YggdrasilSession(
            access_token="0",
            client_token="0",
            uuid=profile_uuid,
            username=name,
            display_name=name,
            selected_profile={"id": profile_uuid, "name": name},
            available_profiles=[{"id": profile_uuid, "name": name}],
            user_properties=[],
        )

    def _play(self, server_address: str = "", server_port: str = ""):
        m = self.current_modpack
        if not m or self._game_running:
            return
        version = m.get("mc_version", "")
        if not version:
            self.status_label.setText("Modpack has no MC version")
            return

        if not self.config.account_name:
            self.status_label.setText("Log in to your account first")
            self._open_login()
            if not self.config.account_name:
                return
        if not self.config.access_token:
            self.status_label.setText("Session expired — please log in")
            self._open_login()
            if not self.config.access_token:
                return

        self._cancel_requested = False
        self.status_label.setText("Preparing to launch...")
        self.progress_bar.setVisible(True)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setValue(0)

        def do_prepare():
            try:
                if self._cancel_requested:
                    return None
                should_cancel = lambda: self._cancel_requested
                try:
                    m = self.api.get_modpack(self.project["id"], self.current_modpack["id"])
                except Exception:
                    pass

                vm = VersionManager()
                version = vm.install_loader(m.get("mc_version", ""), m.get("loader", ""), m.get("loader_version", ""), self._update_progress, should_cancel)
                if not vm.is_version_installed(version):
                    vm.download_version(version, self._update_progress, should_cancel)
                if not vm.is_version_installed(version):
                    raise RuntimeError(f"Failed to install Minecraft {version}")
                meta = vm.get_version_meta(version)
                if meta and meta.assets:
                    am = AssetManager()
                    am.download_assets(meta.assets, self._update_progress, should_cancel)

                over = self._modpack_override(m.get("id", ""))
                java = over.get("java_path") or m.get("java_path") or self.config.java_path
                if not java or java.strip().lower() == "java":
                    jv = meta.java_version or {}
                    required = int(jv.get("majorVersion") or jv.get("major") or 0) or 0
                    if not required:
                        required = JavaManager.java_required_for_mc(m.get("mc_version", ""))
                    jm = JavaManager()
                    java = jm.ensure_java(required, self._update_progress, should_cancel)
                    if not java and required:
                        raise RuntimeError(
                            f"Java {required} required for Minecraft {m.get('mc_version', '')} "
                            f"could not be found or installed"
                        )
                if not java:
                    java = "java"
                session = self._refresh_session()
                if session is None:
                    return "no_session"
                return java, version, session
            except CancelledError:
                return None

        def on_done(result):
            if result == "no_session":
                self.progress_bar.setVisible(False)
                self.cancel_btn.setVisible(False)
                self._clear_details()
                self.status_label.setText("Session expired — please log in")
                self._refresh_card_states()
                self._open_login()
                return
            if result is None:
                self.progress_bar.setVisible(False)
                self.cancel_btn.setVisible(False)
                self._clear_details()
                self.status_label.setText("Preparation cancelled")
                self._refresh_card_states()
                return
            java, eff_version, session = result
            self._launch(m, eff_version, java, session, server_address, server_port)

        def on_error(err):
            self.progress_bar.setVisible(False)
            self.cancel_btn.setVisible(False)
            self._clear_details()
            self.status_label.setText(f"Prepare failed: {err}")
            self._refresh_card_states()
            if "Session expired" in err:
                self.status_label.setText("Session expired — please log in")
                self._open_login()
                if self.config.account_name:
                    self.status_label.setText(f"Logged in as {self.config.account_name}. Click Play to start.")

        run_async(do_prepare, on_done=on_done, on_error=on_error)

    def _launch(self, m, version, java, session, server_address: str = "", server_port: str = ""):
        mp_dir = get_modpack_dir(self.project["id"], m["id"])
        if not _is_modpack_installed(mp_dir):
            self.progress_bar.setVisible(False)
            self.status_label.setText("Modpack not installed")
            return

        self.status_label.setText("Starting game...")
        self.progress_bar.setValue(0)

        def do_launch():
            meta = self.version_manager.get_version_meta(version)
            over = self._modpack_override(m.get("id", ""))
            xmx = over.get("max_memory") or m.get("max_memory") or self.config.max_memory
            xms = over.get("min_memory") or m.get("min_memory") or self.config.min_memory
            jvm_args = over.get("java_args") or m.get("java_args") or self.config.java_args
            injector_jar = ""
            injector_url = ""
            if session.access_token and session.access_token != "0":
                from launcher.game.injector import download_injector, injector_downloaded, get_injector_path
                if not injector_downloaded():
                    download_injector(self.config.api_url, verify_ssl=self.config.verify_ssl)
                injector_jar = str(get_injector_path())
                injector_url = self.config.api_url.rstrip("/")
            return meta, xmx, xms, jvm_args, injector_jar, injector_url

        def on_done(result):
            _, xmx, xms, jvm_args, injector_jar, injector_url = result
            try:
                self.starter.start(
                    version_id=version,
                    session=session,
                    java_path=java,
                    max_mem=xmx,
                    min_mem=xms,
                    extra_jvm_args=jvm_args,
                    server_address=server_address,
                    server_port=server_port,
                    output_callback=lambda text: self.console.append(text),
                    on_exit=self._game_signals.exited.emit,
                    game_dir=str(mp_dir),
                    injector_jar=injector_jar,
                    injector_url=injector_url,
                )
                self._game_running = True
                self.status_label.setText("Game running")
                if self.config.console_mode in ("always", "on_launch"):
                    self.console_window.show()
                self.progress_bar.setVisible(False)
                self._clear_details()
                self._refresh_card_states()
                if not self.config.keep_launcher_open:
                    self.window().hide()
            except Exception as e:
                self.progress_bar.setVisible(False)
                self._clear_details()
                self.status_label.setText(f"Launch failed: {e}")
                self._refresh_card_states()

        def on_error(err):
            self.progress_bar.setVisible(False)
            self._clear_details()
            self.status_label.setText(f"Error: {err}")
            self._refresh_card_states()

        run_async(do_launch, on_done=on_done, on_error=on_error)

    def _on_game_exited(self):
        self._game_running = False
        self.status_label.setText("Game closed")
        self._refresh_card_states()
        if self.window().isHidden():
            self.window().show()

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.config = LauncherConfig.load()
            self.api = APIManager(self.config.api_url, verify_ssl=self.config.verify_ssl)
            self._apply_theme()
            self._apply_console_mode()
            self._load_project()

    def _apply_theme(self):
        app = QApplication.instance()
        if app:
            app.setStyleSheet(load_theme(self.config.theme_mode))

    def _update_account_button(self):
        name = self.config.account_name or "Login"
        self.account_btn.setText(name)
        if self.config.account_uuid:
            self._load_account_head()
        else:
            self.account_btn.setIcon(QIcon())

    def _load_account_head(self):
        uid = self.config.account_uuid
        api_url = self.config.api_url
        verify_ssl = self.config.verify_ssl

        def work():
            try:
                import requests
                resp = requests.get(f"{api_url}/auth/skin/{uid}", timeout=10, verify=verify_ssl)
                if resp.status_code == 200:
                    return resp.content
            except requests.RequestException:
                pass
            return None

        def on_done(data):
            if not data:
                return
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                scale = pixmap.width() // 64
                if scale < 1:
                    scale = 1
                head = pixmap.copy(8 * scale, 8 * scale, 8 * scale, 8 * scale)
                head = head.scaled(24, 24,
                                   Qt.AspectRatioMode.IgnoreAspectRatio,
                                   Qt.TransformationMode.FastTransformation)
                self.account_btn.setIcon(QIcon(head))

        run_async(work, on_done=on_done, on_error=lambda err: None)

    def _on_account_clicked(self):
        if not self.config.account_name:
            self._open_login()
            return
        menu = QMenu(self)
        account = menu.addAction(self.config.account_name)
        account.setEnabled(False)
        skin = menu.addAction("Change skin...")
        switch = menu.addAction("Switch account...")
        logout = menu.addAction("Log out")
        chosen = menu.exec(self.account_btn.mapToGlobal(self.account_btn.rect().bottomLeft()))
        if chosen == skin:
            self._open_skin_dialog()
        elif chosen == switch:
            self._open_login()
        elif chosen == logout:
            self._logout()

    def _open_skin_dialog(self):
        from launcher.ui.skin_dialog import SkinDialog
        dialog = SkinDialog(self.config, self)
        dialog.exec()
        self._load_account_head()

    def _open_login(self):
        dialog = LoginDialog(self.config, self)
        if dialog.exec() and dialog.session:
            self.config.access_token = dialog.session.access_token
            self.config.client_token = dialog.session.client_token
            self.config.account_uuid = dialog.session.uuid
            self.config.account_name = dialog.session.display_name or dialog.session.username
            self.config.account_properties = dialog.session.user_properties
            self.config.save()
            self._update_account_button()
            self.status_label.setText(f"Logged in as {self.config.account_name}")
            self._load_bans()

    def _logout(self):
        if self.config.access_token:
            try:
                auth = YggdrasilAuth(f"{self.config.api_url}/auth", verify_ssl=self.config.verify_ssl)
                auth.invalidate(self.config.access_token, self.config.client_token)
            except Exception:
                pass
        self.config.access_token = ""
        self.config.client_token = ""
        self.config.account_uuid = ""
        self.config.account_name = ""
        self.config.account_properties = []
        self.config.save()
        self._update_account_button()
        self.status_label.setText("Logged out")
        self._load_bans()

    def _refresh_session(self):
        if not (self.config.access_token and self.config.account_name):
            return None
        auth = YggdrasilAuth(f"{self.config.api_url}/auth", verify_ssl=self.config.verify_ssl)
        if not auth.validate(self.config.access_token, self.config.client_token):
            try:
                auth.refresh(self.config.access_token, self.config.client_token)
            except Exception:
                self.config.access_token = ""
                self.config.client_token = ""
                self.config.account_properties = []
                self.config.save()
                self._update_account_button()
                raise RuntimeError("Session expired, please log in again")
            self.config.access_token = auth.session.access_token
            self.config.client_token = auth.session.client_token
            self.config.account_uuid = auth.session.uuid
            self.config.account_name = auth.session.display_name or self.config.account_name
            self.config.account_properties = auth.session.user_properties
            self.config.save()
            self._update_account_button()
        return self._make_session()

    def _make_session(self):
        name = self.config.account_name
        if self.config.access_token and name:
            profile_uuid = self.config.account_uuid
            return YggdrasilSession(
                access_token=self.config.access_token,
                client_token=self.config.client_token,
                uuid=profile_uuid,
                username=name,
                display_name=name,
                selected_profile={"id": profile_uuid, "name": name},
                available_profiles=[{"id": profile_uuid, "name": name}],
                user_properties=self.config.account_properties or [],
            )
        return self._make_offline_session()

    def cleanup(self):
        if self._game_running:
            try:
                self.starter.stop()
            except Exception:
                pass
        try:
            self.console_window.close()
        except Exception:
            pass
