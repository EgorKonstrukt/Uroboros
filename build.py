import os
import subprocess
import platform

APP_NAME = "UroborosLauncher"
SERVER_NAME = "UroborosServer"
MAIN_SCRIPT = "launcher/main.py"
SERVER_SCRIPT = "server/__main__.py"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "dist")

NUITKA_OPTIONS = [
    "--standalone",
    "--enable-plugins=pyqt6",
    "--remove-output",
    "--include-package=PyQt6",
    "--include-package=PyQt6.QtCore",
    "--include-package=PyQt6.QtGui",
    "--include-package=PyQt6.QtWidgets",
    "--include-package=qfluentwidgets",
    "--include-package=requests",
    "--include-package=psutil",
]

NUITKA_SERVER_OPTIONS = [
    "--standalone",
    "--remove-output",
    "--include-package=fastapi",
    "--include-package=uvicorn",
    "--include-package=sqlalchemy",
    "--include-package=aiosqlite",
    "--include-package=requests",
    "--include-package=pydantic",
    "--include-package=starlette",
]

PLUGIN_DIRS = []


def find_qfluent_plugins():
    try:
        import qfluentwidgets
        qf_dir = os.path.dirname(qfluentwidgets.__file__)
        plugins = os.path.join(qf_dir, "common", "style_sheet")
        if os.path.isdir(plugins):
            PLUGIN_DIRS.append(plugins)
    except ImportError:
        pass


def build_launcher():
    cmd = ["nuitka"] + NUITKA_OPTIONS
    if platform.system() == "Windows":
        cmd += ["--msvc=latest", "--disable-console"]
    elif platform.system() == "Darwin":
        cmd += ["--macos-create-app-bundle"]
    cmd += [
        f"--output-dir={OUTPUT_DIR}",
        f"--output-filename={APP_NAME}",
        MAIN_SCRIPT,
    ]
    print(f"Building launcher for {platform.system()}...")
    subprocess.check_call(cmd)


def build_server():
    cmd = ["nuitka"] + NUITKA_OPTIONS + NUITKA_SERVER_OPTIONS
    if platform.system() == "Windows":
        cmd += ["--msvc=latest"]
    elif platform.system() == "Darwin":
        cmd += ["--macos-create-app-bundle"]
    cmd += [
        f"--output-dir={OUTPUT_DIR}",
        f"--output-filename={SERVER_NAME}",
        SERVER_SCRIPT,
    ]
    print(f"Building server for {platform.system()}...")
    subprocess.check_call(cmd)


def build_all():
    find_qfluent_plugins()
    build_launcher()
    build_server()


if __name__ == "__main__":
    build_all()
