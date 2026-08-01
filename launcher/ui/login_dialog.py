from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QLineEdit, QPushButton,
)

from launcher.config import LauncherConfig
from launcher.api.auth import YggdrasilAuth
from launcher.utils.async_worker import run_async


class LoginDialog(QDialog):
    def __init__(self, config: LauncherConfig, parent=None):
        super().__init__(parent)
        self.config = config
        self.session = None
        self.auth = YggdrasilAuth(f"{config.api_url}/auth", verify_ssl=config.verify_ssl)
        self.setWindowTitle("Account login")
        self.setMinimumWidth(400)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        title = QLabel("Log in to your account", self)
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        form.setSpacing(10)
        self.username_input = QLineEdit(self)
        self.username_input.setPlaceholderText("username")
        form.addRow("Username:", self.username_input)

        self.password_input = QLineEdit(self)
        self.password_input.setPlaceholderText("password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password:", self.password_input)
        layout.addLayout(form)

        self.error_label = QLabel("", self)
        self.error_label.setObjectName("DialogError")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        self.login_btn = QPushButton("Log in", self)
        self.login_btn.clicked.connect(self._do_login)
        self.register_btn = QPushButton("Create account", self)
        self.register_btn.clicked.connect(self._do_register)
        cancel_btn = QPushButton("Cancel", self)
        cancel_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addWidget(self.login_btn)
        btn_row.addWidget(self.register_btn)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self.password_input.returnPressed.connect(self._do_login)

    def _set_busy(self, busy: bool):
        self.login_btn.setEnabled(not busy)
        self.register_btn.setEnabled(not busy)

    def _do_login(self):
        self._authenticate(False)

    def _do_register(self):
        self._authenticate(True)

    def _authenticate(self, register: bool):
        username = self.username_input.text().strip()
        password = self.password_input.text()
        if not username or not password:
            self.error_label.setText("Enter username and password")
            return
        self.error_label.setText("")
        self._set_busy(True)

        def work():
            if register:
                return self.auth.register(username, password)
            return self.auth.authenticate(username, password)

        def on_done(session):
            self._set_busy(False)
            self.session = session
            self.accept()

        def on_error(err):
            self._set_busy(False)
            self.error_label.setText(str(err))

        run_async(work, on_done=on_done, on_error=on_error)
