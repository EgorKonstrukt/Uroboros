import requests
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QComboBox,
)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt

from launcher.api.auth import YggdrasilAuth
from launcher.utils.async_worker import run_async


class SkinDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.auth = YggdrasilAuth(f"{config.api_url}/auth", verify_ssl=config.verify_ssl)
        self._pending_path = ""
        self.setWindowTitle("Change skin")
        self.setMinimumWidth(380)
        self._setup_ui()
        self._load_current()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Change skin", self)
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        self.preview = QLabel("No skin", self)
        self.preview.setObjectName("SkinPreview")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedSize(128, 192)
        layout.addWidget(self.preview, alignment=Qt.AlignmentFlag.AlignCenter)

        row = QHBoxLayout()
        self.file_btn = QPushButton("Choose file...", self)
        self.file_btn.clicked.connect(self._choose_file)
        self.model_combo = QComboBox(self)
        self.model_combo.addItem("Classic (Steve)", "classic")
        self.model_combo.addItem("Slim (Alex)", "slim")
        row.addWidget(self.file_btn, 1)
        row.addWidget(self.model_combo)
        layout.addLayout(row)

        self.file_label = QLabel("", self)
        self.file_label.setObjectName("SkinFileLabel")
        self.file_label.setWordWrap(True)
        layout.addWidget(self.file_label)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.upload_btn = QPushButton("Upload", self)
        self.upload_btn.clicked.connect(self._upload)
        self.remove_btn = QPushButton("Remove skin", self)
        self.remove_btn.clicked.connect(self._remove)
        cancel_btn = QPushButton("Close", self)
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self.remove_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(self.upload_btn)
        layout.addLayout(btn_row)

    def _load_current(self):
        uid = self.config.account_uuid
        if not uid:
            return

        def work():
            try:
                resp = requests.get(
                    f"{self.config.api_url}/auth/skin/{uid}",
                    timeout=10,
                    verify=self.config.verify_ssl,
                )
                if resp.status_code == 200:
                    return resp.content
            except requests.RequestException:
                pass
            return None

        def on_done(data):
            if data:
                pixmap = QPixmap()
                if pixmap.loadFromData(data):
                    self.preview.setPixmap(pixmap.scaled(
                        self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation))
                    self.remove_btn.setEnabled(True)
                    self.remove_btn.setText("Remove skin")

        run_async(work, on_done=on_done, on_error=lambda err: None)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select skin", "", "Images (*.png *.jpg *.jpeg)"
        )
        if not path:
            return
        if path.lower().endswith((".jpg", ".jpeg")):
            if not self._is_jpeg_png(path):
                self.error_label.setText("Invalid image file")
                return
        else:
            self.error_label.setText("")
        self._pending_path = path
        self.file_label.setText(path)
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def _is_jpeg_png(self, path):
        try:
            with open(path, "rb") as f:
                head = f.read(12)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                return True
            if head.startswith(b"\xff\xd8\xff"):
                return True
        except OSError:
            return False
        return False

    def _set_busy(self, busy: bool):
        self.upload_btn.setEnabled(not busy)
        self.remove_btn.setEnabled(not busy)
        self.file_btn.setEnabled(not busy)

    def _require_token(self) -> bool:
        if not (self.config.access_token and self.config.account_uuid):
            self.error_label.setText("Not logged in")
            return False
        return True

    def _upload(self):
        if not self._require_token():
            return
        if not self._pending_path:
            self.error_label.setText("Select a skin file first")
            return
        path = self._pending_path
        model = self.model_combo.currentData() or "classic"

        def work():
            return self.auth.upload_skin(self.config.access_token, path, model)

        def on_done(data):
            self._set_busy(False)
            self._pending_path = ""
            self.file_label.setText("Skin uploaded")
            self.error_label.setText("")
            self._load_current()

        def on_error(err):
            self._set_busy(False)
            self.error_label.setText(str(err))

        self._set_busy(True)
        self.error_label.setText("Uploading...")
        run_async(work, on_done=on_done, on_error=on_error)

    def _remove(self):
        if not self._require_token():
            return

        def work():
            return self.auth.remove_skin(self.config.access_token)

        def on_done(data):
            self._set_busy(False)
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No skin")
            self.remove_btn.setText("Remove skin")
            self.error_label.setText("")

        def on_error(err):
            self._set_busy(False)
            self.error_label.setText(str(err))

        self._set_busy(True)
        self.error_label.setText("Removing...")
        run_async(work, on_done=on_done, on_error=on_error)
