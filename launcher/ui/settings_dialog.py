from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QSpinBox, QFileDialog, QPushButton, QLabel, QLineEdit, QCheckBox, QComboBox

from launcher.config import LauncherConfig
from launcher.utils.storage import set_work_dir, ensure_dirs


class SettingsDialog(QDialog):
    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Settings")
        self.setMinimumSize(500, 350)
        self._setup_ui()
        self._load_config()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Settings", self)
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(12)

        self.api_url_input = QLineEdit(self)
        form.addRow("API URL:", self.api_url_input)

        self.project_id_input = QLineEdit(self)
        form.addRow("Project ID:", self.project_id_input)

        self.java_path_input = QLineEdit(self)
        java_manage = QPushButton("Java Manager", self)
        java_manage.clicked.connect(self._open_java_manager)
        java_row = QHBoxLayout()
        java_row.addWidget(self.java_path_input)
        java_row.addWidget(java_manage)
        form.addRow("Java Path:", java_row)

        self.min_mem = QSpinBox(self)
        self.min_mem.setRange(512, 32768)
        self.min_mem.setSingleStep(512)
        self.min_mem.setSuffix(" MB")
        form.addRow("Min Memory:", self.min_mem)

        self.max_mem = QSpinBox(self)
        self.max_mem.setRange(512, 65536)
        self.max_mem.setSingleStep(512)
        self.max_mem.setSuffix(" MB")
        form.addRow("Max Memory:", self.max_mem)

        self.java_args = QLineEdit(self)
        form.addRow("JVM Args:", self.java_args)

        self.game_dir_input = QLineEdit(self)
        dir_browse = QPushButton("Browse", self)
        dir_browse.clicked.connect(self._browse_game_dir)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.game_dir_input)
        dir_row.addWidget(dir_browse)
        form.addRow("Game Directory:", dir_row)

        self.verify_ssl = QCheckBox("Verify TLS certificate (uncheck for self-signed)", self)
        form.addRow("TLS:", self.verify_ssl)

        self.console_mode = QComboBox(self)
        self.console_mode.addItem("Always", "always")
        self.console_mode.addItem("On game launch", "on_launch")
        self.console_mode.addItem("Never", "never")
        form.addRow("Console:", self.console_mode)

        self.theme_mode = QComboBox(self)
        self.theme_mode.addItem("System", "system")
        self.theme_mode.addItem("Light", "light")
        self.theme_mode.addItem("Dark", "dark")
        form.addRow("Theme:", self.theme_mode)

        self.keep_open = QCheckBox("Keep launcher open after starting the game", self)
        form.addRow("Launcher:", self.keep_open)

        layout.addLayout(form)
        layout.addStretch()

        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save", self)
        save_btn.clicked.connect(self._save)
        btn_layout.addStretch()
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _load_config(self):
        self.api_url_input.setText(self.config.api_url)
        self.project_id_input.setText(self.config.project_id)
        self.java_path_input.setText(self.config.java_path)
        self.min_mem.setValue(self.config.min_memory)
        self.max_mem.setValue(self.config.max_memory)
        self.java_args.setText(self.config.java_args)
        self.game_dir_input.setText(self.config.work_dir)
        self.verify_ssl.setChecked(self.config.verify_ssl)
        idx = self.console_mode.findData(self.config.console_mode)
        if idx >= 0:
            self.console_mode.setCurrentIndex(idx)
        idx = self.theme_mode.findData(self.config.theme_mode)
        if idx >= 0:
            self.theme_mode.setCurrentIndex(idx)
        self.keep_open.setChecked(self.config.keep_launcher_open)

    def _open_java_manager(self):
        from launcher.ui.java_manager_dialog import JavaManagerDialog
        dialog = JavaManagerDialog(self.config, self)
        dialog.exec()
        self.java_path_input.setText(self.config.java_path)

    def _browse_game_dir(self):
        start = self.game_dir_input.text().strip() or ""
        path = QFileDialog.getExistingDirectory(self, "Select Game Directory", start)
        if path:
            self.game_dir_input.setText(path)

    def _save(self):
        self.config.api_url = self.api_url_input.text().strip()
        self.config.project_id = self.project_id_input.text().strip()
        self.config.java_path = self.java_path_input.text()
        self.config.min_memory = self.min_mem.value()
        self.config.max_memory = self.max_mem.value()
        self.config.java_args = self.java_args.text()
        self.config.work_dir = self.game_dir_input.text().strip()
        self.config.verify_ssl = self.verify_ssl.isChecked()
        self.config.console_mode = self.console_mode.currentData()
        self.config.theme_mode = self.theme_mode.currentData()
        self.config.keep_launcher_open = self.keep_open.isChecked()
        set_work_dir(self.config.work_dir)
        ensure_dirs()
        self.config.save()
        self.accept()
