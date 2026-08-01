from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QSpinBox, QPushButton, QCheckBox, QFileDialog,
)

from launcher.config import LauncherConfig


class ModpackSettingsDialog(QDialog):
    def __init__(self, config: LauncherConfig, project_id: str, modpack: dict, parent=None):
        super().__init__(parent)
        self.config = config
        self.modpack = modpack
        self._key = f"{project_id}:{modpack.get('id', '')}"
        self._override = dict(config.modpack_settings.get(self._key, {}) or {})
        self.setWindowTitle(f"Settings - {modpack.get('name', 'Modpack')}")
        self.setMinimumWidth(460)
        self._setup_ui()
        self._load()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel(f"Modpack settings - {self.modpack.get('name', 'Modpack')}", self)
        title.setObjectName("DialogTitle")
        title.setWordWrap(True)
        layout.addWidget(title)

        self.enable_check = QCheckBox("Use custom settings for this modpack", self)
        self.enable_check.toggled.connect(self._set_enabled)
        layout.addWidget(self.enable_check)

        form = QFormLayout()
        form.setSpacing(12)

        self.java_path_input = QLineEdit(self)
        self.java_path_input.setPlaceholderText("Auto (global settings)")
        java_browse = QPushButton("Browse", self)
        java_browse.clicked.connect(self._browse_java)
        java_clear = QPushButton("Auto", self)
        java_clear.clicked.connect(lambda: self.java_path_input.clear())
        java_row = QHBoxLayout()
        java_row.addWidget(self.java_path_input)
        java_row.addWidget(java_browse)
        java_row.addWidget(java_clear)
        form.addRow("Java:", java_row)

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
        self.java_args.setPlaceholderText("e.g. -XX:+UseG1GC")
        form.addRow("JVM Args:", self.java_args)

        layout.addLayout(form)

        self._form_widgets = [
            self.java_path_input, java_browse, java_clear,
            self.min_mem, self.max_mem, self.java_args,
        ]

        layout.addStretch()

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save", self)
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _set_enabled(self, enabled: bool):
        for w in self._form_widgets:
            w.setEnabled(enabled)

    def _load(self):
        over = self._override
        has_override = bool(over)
        self.enable_check.setChecked(has_override)
        self.java_path_input.setText(over.get("java_path", ""))
        self.min_mem.setValue(over.get("min_memory") or self.modpack.get("min_memory") or self.config.min_memory)
        self.max_mem.setValue(over.get("max_memory") or self.modpack.get("max_memory") or self.config.max_memory)
        self.java_args.setText(over.get("java_args", ""))
        self._set_enabled(has_override)

    def _browse_java(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Java Executable", "",
            "Java (java* java.exe javaw.exe);;All Files (*)"
        )
        if path:
            self.java_path_input.setText(path)

    def _save(self):
        settings = dict(self.config.modpack_settings)
        if not self.enable_check.isChecked():
            settings.pop(self._key, None)
        else:
            over = {}
            java = self.java_path_input.text().strip()
            if java:
                over["java_path"] = java
            over["min_memory"] = self.min_mem.value()
            over["max_memory"] = self.max_mem.value()
            args = self.java_args.text().strip()
            if args:
                over["java_args"] = args
            settings[self._key] = over
        self.config.modpack_settings = settings
        self.config.save()
        self.accept()
