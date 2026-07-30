import hashlib

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea,
    QPushButton, QProgressBar,
)
from PyQt6.QtCore import Qt

from launcher.api.api_manager import APIManager
from launcher.config import LauncherConfig, cache_projects, load_cached_projects
from launcher.ui.settings_dialog import SettingsDialog
from launcher.game.starter import GameStarter
from launcher.game.version_manager import VersionManager
from launcher.game.assets import AssetManager
from launcher.ui.widgets.console import ConsoleWidget
from launcher.ui.widgets.modpack_card import ModpackCard
from launcher.utils.storage import get_modpack_dir
from launcher.utils.async_worker import run_async


class MainWindow(QWidget):
    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.api = APIManager(config.api_url)
        self.project = None
        self.modpacks = []
        self.modpack_cards = []
        self._game_running = False
        self._cancel_requested = False
        self.starter = GameStarter()
        self.version_manager = VersionManager()

        self._setup_ui()
        self._load_project()

    def _setup_ui(self):
        self.setObjectName("MainWindow")
        self.setStyleSheet("QWidget#MainWindow { background: #11111b; }")
        layout = QVBoxLayout(self)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        header.setContentsMargins(20, 12, 20, 12)
        self.title_label = QLabel("Uroboros", self)
        self.title_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #cdd6f4;")
        header.addWidget(self.title_label)
        header.addStretch()
        self.settings_btn = QPushButton("Settings", self)
        self.settings_btn.setStyleSheet("""
            QPushButton { background: #313244; color: #cdd6f4; border: none;
                border-radius: 6px; padding: 8px 18px; font-size: 13px; }
            QPushButton:hover { background: #45475a; }
        """)
        self.settings_btn.clicked.connect(self._open_settings)
        header.addWidget(self.settings_btn)
        layout.addLayout(header)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content = QWidget()
        content.setStyleSheet("background: transparent;")
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(8)
        self.content_layout.setContentsMargins(20, 8, 20, 20)

        self.loading_label = QLabel("Loading project...", content)
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.loading_label.setStyleSheet("color: #6c7086; font-size: 14px;")
        self.content_layout.addWidget(self.loading_label)

        self.project_section = QWidget(content)
        self.project_section.setVisible(False)
        self.project_section.setStyleSheet("background: transparent;")
        ps_layout = QVBoxLayout(self.project_section)
        ps_layout.setSpacing(8)
        ps_layout.setContentsMargins(0, 0, 0, 0)

        self.desc_label = QLabel("", self.project_section)
        self.desc_label.setWordWrap(True)
        self.desc_label.setStyleSheet("color: #a6adc8; font-size: 13px;")
        ps_layout.addWidget(self.desc_label)

        self.modpacks_header = QLabel("Modpacks", self.project_section)
        self.modpacks_header.setStyleSheet("font-size: 15px; font-weight: bold; color: #cdd6f4; margin-top: 4px;")
        ps_layout.addWidget(self.modpacks_header)

        self.cards_widget = QWidget(self.project_section)
        self.cards_widget.setStyleSheet("background: transparent;")
        self.cards_layout = QVBoxLayout(self.cards_widget)
        self.cards_layout.setSpacing(8)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        ps_layout.addWidget(self.cards_widget)

        self.status_label = QLabel("", self.project_section)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet("color: #6c7086; font-size: 12px;")
        ps_layout.addWidget(self.status_label)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(8)
        self.progress_bar = QProgressBar(self.project_section)
        self.progress_bar.setVisible(False)
        self.progress_bar.setStyleSheet("""
            QProgressBar { border: none; border-radius: 4px; background: #313244;
                height: 8px; text-align: center; font-size: 11px; color: #6c7086; }
            QProgressBar::chunk { background: #89b4fa; border-radius: 4px; }
        """)
        progress_row.addWidget(self.progress_bar, 1)
        self.cancel_btn = QPushButton("Cancel", self.project_section)
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setStyleSheet("""
            QPushButton { background: #f38ba8; color: #111; border: none;
                border-radius: 4px; padding: 6px 14px; font-weight: bold; font-size: 12px; }
            QPushButton:hover { background: #f5a0b8; }
        """)
        self.cancel_btn.clicked.connect(self._cancel_install)
        progress_row.addWidget(self.cancel_btn)
        ps_layout.addLayout(progress_row)

        self.content_layout.addWidget(self.project_section)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)

        self.console = ConsoleWidget(self)
        self.console.setMaximumHeight(150)
        layout.addWidget(self.console)

    def _load_project(self):
        pid = self.config.project_id
        if not pid:
            self.loading_label.setText("No project configured. Open Settings and set a Project ID.")
            self.settings_btn.setText("Configure")
            return

        def do_fetch():
            try:
                return self.api.get_project(pid), False
            except Exception:
                cached = load_cached_projects()
                if cached:
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
            self._populate_ui()

        def on_error(err):
            self.loading_label.setText(f"Failed to load project: {err}")

        run_async(do_fetch, on_done=on_done, on_error=on_error)

    def _populate_ui(self):
        p = self.project
        title = p.get("brand_name") or p.get("name") or "Uroboros"
        self.title_label.setText(title)
        color = p.get("primary_color", "#89b4fa")
        self.title_label.setStyleSheet(f"font-size: 18px; font-weight: bold; color: {color};")
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
            no.setStyleSheet("color: #6c7086; font-size: 13px; padding: 20px;")
            no.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.cards_layout.addWidget(no)
            return

        for m in self.modpacks:
            mp_dir = get_modpack_dir(self.project["id"], m["id"])
            installed = mp_dir.exists() and any(mp_dir.iterdir())
            card = ModpackCard(m, installed=installed, game_running=self._game_running, parent=self.cards_widget)
            card.install_clicked.connect(self._on_install_clicked)
            card.play_clicked.connect(self._on_play_clicked)
            self.cards_layout.addWidget(card)
            self.modpack_cards.append(card)

    def _on_install_clicked(self, modpack):
        self.current_modpack = modpack
        self._install()

    def _on_play_clicked(self, modpack):
        self.current_modpack = modpack
        self._play()

    def _refresh_card_states(self):
        for card in self.modpack_cards:
            mp_dir = get_modpack_dir(self.project["id"], card.modpack["id"])
            installed = mp_dir.exists() and any(mp_dir.iterdir())
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
            if self._cancel_requested:
                return "cancelled"

            vm = VersionManager()
            if not vm.is_version_installed(version):
                vm.download_version(version, self._update_progress)

            meta = vm.get_version_meta(version)
            if meta and meta.assets:
                am = AssetManager()
                am.download_assets(meta.assets, self._update_progress)

            mp_dir = get_modpack_dir(self.project["id"], m["id"])
            mp_dir.mkdir(parents=True, exist_ok=True)

            try:
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
            except Exception as e:
                self.status_label.setText(f"Download error: {e}")
                return False
            return True

        def on_done(result):
            self.progress_bar.setVisible(False)
            self.cancel_btn.setVisible(False)
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
            self.status_label.setText(f"Install failed: {err}")

        run_async(do_install, on_done=on_done, on_error=on_error)

    def _update_progress(self, value):
        self.progress_bar.setValue(value)

    def _play(self):
        m = self.current_modpack
        if not m or self._game_running:
            return
        version = m.get("mc_version", "")

        self.status_label.setText("Starting game...")
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        def do_launch():
            meta = self.version_manager.get_version_meta(version)
            java = m.get("java_path") or self.config.java_path
            xmx = m.get("max_memory") or self.config.max_memory
            xms = m.get("min_memory") or self.config.min_memory
            jvm_args = m.get("java_args") or self.config.java_args
            return meta, java, xmx, xms, jvm_args

        def on_done(result):
            meta, java, xmx, xms, jvm_args = result

            class OfflineSession:
                access_token = "offline"
                client_token = "offline"
                uuid = ""
                username = "Player"
                display_name = "Player"
                selected_profile = {}
                available_profiles = []
                user_properties = {}

            mp_dir = get_modpack_dir(self.project["id"], m["id"])
            try:
                self.starter.start(
                    version_id=version,
                    session=OfflineSession(),
                    java_path=java,
                    max_mem=xmx,
                    min_mem=xms,
                    extra_jvm_args=jvm_args,
                    output_callback=lambda text: self.console.append(text),
                    game_dir=str(mp_dir),
                )
                self._game_running = True
                self.status_label.setText("Game running")
                self.progress_bar.setVisible(False)
                self._refresh_card_states()
                if not self.config.keep_launcher_open:
                    self.window().hide()
            except Exception as e:
                self.progress_bar.setVisible(False)
                self.status_label.setText(f"Launch failed: {e}")
                self._refresh_card_states()

        def on_error(err):
            self.progress_bar.setVisible(False)
            self.status_label.setText(f"Error: {err}")
            self._refresh_card_states()

        run_async(do_launch, on_done=on_done, on_error=on_error)

    def _open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec():
            self.config = LauncherConfig.load()
            self.api = APIManager(self.config.api_url)
            self._load_project()

    def cleanup(self):
        if self._game_running:
            try:
                self.starter.stop()
            except Exception:
                pass
