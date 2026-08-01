import os
import shutil
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QProgressBar, QScrollArea, QWidget, QFrame,
)
from PyQt6.QtCore import Qt, QObject, pyqtSignal

from launcher.config import LauncherConfig
from launcher.game.java_manager import JavaManager, INSTALLABLE_VERSIONS
from launcher.utils.async_worker import run_async


class _JavaSignals(QObject):
    progress = pyqtSignal(object)


class JavaManagerDialog(QDialog):
    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.manager = JavaManager()
        self._cancel_requested = False
        self._installing = False
        self.setWindowTitle("Java Manager")
        self.setMinimumSize(700, 560)
        self._signals = _JavaSignals()
        self._signals.progress.connect(self._apply_progress)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Java Manager", self)
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        self.current_label = QLabel("", self)
        self.current_label.setObjectName("JavaPathLabel")
        self.current_label.setWordWrap(True)
        layout.addWidget(self.current_label)

        self.system_label = QLabel("", self)
        self.system_label.setObjectName("JavaPathLabel")
        self.system_label.setWordWrap(True)
        layout.addWidget(self.system_label)

        header_row = QHBoxLayout()
        header = QLabel("Found Java runtimes", self)
        header.setObjectName("SectionLabel")
        header_row.addWidget(header)
        header_row.addStretch()
        self.browse_btn = QPushButton("Browse...", self)
        self.browse_btn.setObjectName("SettingsButton")
        self.browse_btn.clicked.connect(self._browse)
        header_row.addWidget(self.browse_btn)
        layout.addLayout(header_row)

        scroll = QScrollArea(self)
        scroll.setObjectName("MainScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_widget = QWidget()
        self.rows_widget.setObjectName("MainContent")
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setSpacing(8)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(self.rows_widget)
        layout.addWidget(scroll, 1)

        install_header = QLabel("Install Java", self)
        install_header.setObjectName("SectionLabel")
        layout.addWidget(install_header)

        install_row = QHBoxLayout()
        install_row.setSpacing(8)
        self.version_combo = QComboBox(self)
        for v in INSTALLABLE_VERSIONS:
            self.version_combo.addItem(f"Java {v}", v)
        idx = self.version_combo.findData(21)
        if idx >= 0:
            self.version_combo.setCurrentIndex(idx)
        install_row.addWidget(self.version_combo, 1)
        self.install_btn = QPushButton("Install", self)
        self.install_btn.setObjectName("InstallJavaButton")
        self.install_btn.clicked.connect(self._install)
        install_row.addWidget(self.install_btn)
        self.cancel_btn = QPushButton("Cancel", self)
        self.cancel_btn.setObjectName("CancelButton")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_install)
        install_row.addWidget(self.cancel_btn)
        layout.addLayout(install_row)

        self.install_status = QLabel("", self)
        self.install_status.setObjectName("JavaPathLabel")
        self.install_status.setWordWrap(True)
        layout.addWidget(self.install_status)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close", self)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    def _clear_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _refresh(self):
        self.version_combo.setEnabled(not self._installing)
        self.install_btn.setEnabled(not self._installing)
        self._clear_rows()

        current = self.config.java_path
        if current and current.strip().lower() != "java":
            ver = self.manager.get_java_major_version(current)
            ver_text = f"Java {ver}" if ver else "unknown version"
            self.current_label.setText(f"Configured Java: {ver_text}   {current}")
        else:
            self.current_label.setText("Configured Java: Auto (best Java detected at launch)")

        sys_java = shutil.which("java")
        if sys_java:
            ver = self.manager.get_java_major_version(sys_java)
            ver_text = f"Java {ver}" if ver else "unknown version"
            self.system_label.setText(f"System Java: {ver_text}   {sys_java}")
        else:
            self.system_label.setText("System Java: not found on PATH")

        found = self.manager.list_all()
        if not found:
            empty = QLabel("No Java runtimes detected", self.rows_widget)
            empty.setObjectName("EmptyLabel")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.rows_layout.addWidget(empty)
            return

        current_path = ""
        if current and current.strip().lower() != "java":
            current_path = os.path.normcase(str(Path(current).resolve()))
        for entry in found:
            row = self._build_row(entry, os.path.normcase(str(Path(entry["path"]).resolve())) == current_path)
            self.rows_layout.addWidget(row)
        self.rows_layout.addStretch()

    def _build_row(self, entry: dict, is_current: bool) -> QFrame:
        row = QFrame(self.rows_widget)
        row.setObjectName("JavaRow")
        h = QHBoxLayout(row)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(12)

        ver = entry["version"]
        ver_label = QLabel(f"Java {ver}" if ver else "Unknown", row)
        ver_label.setObjectName("JavaVersionLabel")
        ver_label.setFixedWidth(96)
        h.addWidget(ver_label)

        path_label = QLabel(entry["path"], row)
        path_label.setObjectName("JavaPathLabel")
        path_label.setWordWrap(True)
        h.addWidget(path_label, 1)

        use_btn = QPushButton("Use" if not is_current else "In use", row)
        use_btn.setObjectName("UseButton")
        use_btn.setEnabled(not is_current)
        use_btn.clicked.connect(lambda checked=False, e=entry: self._use(e))
        h.addWidget(use_btn)

        if entry.get("managed"):
            delete_btn = QPushButton("Delete", row)
            delete_btn.setObjectName("DeleteButton")
            delete_btn.clicked.connect(lambda checked=False, e=entry: self._remove(e))
            h.addWidget(delete_btn)
        return row

    def _browse(self):
        from PyQt6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Java Executable", "",
            "Java (java* java.exe javaw.exe);;All Files (*)"
        )
        if path:
            self.config.java_path = path
            self.config.save()
            self._refresh()

    def _use(self, entry: dict):
        self.config.java_path = entry["path"]
        self.config.save()
        self._refresh()

    def _remove(self, entry: dict):
        self.manager.remove_managed(entry)
        if self.config.java_path and self.config.java_path.strip().lower() != "java":
            if os.path.normcase(str(Path(self.config.java_path).resolve())) == os.path.normcase(str(Path(entry["path"]).resolve())):
                self.config.java_path = "java"
                self.config.save()
        self._refresh()

    def _install(self):
        if self._installing:
            return
        version = self.version_combo.currentData()
        self._cancel_requested = False
        self._installing = True
        self.version_combo.setEnabled(False)
        self.install_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)
        self.install_status.setText(f"Preparing Java {version}...")

        def work():
            return self.manager.download_java(
                version,
                progress_callback=lambda info: self._signals.progress.emit(info),
                should_cancel=lambda: self._cancel_requested,
            )

        def on_done(path):
            self._finish_install(path)

        def on_error(err):
            self._finish_install(None, error=err)

        run_async(work, on_done=on_done, on_error=on_error)

    def _cancel_install(self):
        self._cancel_requested = True
        self.cancel_btn.setEnabled(False)
        self.install_status.setText("Cancelling...")

    def _finish_install(self, path, error=None):
        self._installing = False
        self.install_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self.progress_bar.setVisible(False)
        if self._cancel_requested:
            self.install_status.setText("Installation cancelled")
            self._cancel_requested = False
        elif error:
            self.install_status.setText(f"Install failed: {error}")
        elif path:
            self.install_status.setText("Java installed and set as default")
            self.config.java_path = path
            self.config.save()
        else:
            self.install_status.setText("No matching Java package found for this platform")
        self._refresh()

    def _apply_progress(self, info):
        if not isinstance(info, dict):
            return
        phase = info.get("phase", "")
        current = info.get("current", 0)
        total = info.get("total", 0)
        if phase == "java":
            self.progress_bar.setRange(0, 100)
            if total:
                self.progress_bar.setValue(max(0, min(100, int(current / total * 100))))
                self.install_status.setText(
                    f"Downloading Java... {current / 1048576:.1f} / {total / 1048576:.1f} MB")
            else:
                self.install_status.setText(f"Downloading Java... {current / 1048576:.1f} MB")
        elif phase == "java_extract":
            self.progress_bar.setRange(0, 0)
            self.install_status.setText("Extracting Java...")
