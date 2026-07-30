import sys
import platform


class System:
    WINDOWS = "windows"
    LINUX = "linux"
    OSX = "osx"

    @staticmethod
    def current() -> str:
        if sys.platform == "win32":
            return System.WINDOWS
        if sys.platform == "darwin":
            return System.OSX
        return System.LINUX

    @staticmethod
    def arch() -> str:
        machine = platform.machine().lower()
        if machine in ("amd64", "x86_64"):
            return "x64"
        if machine in ("aarch64", "arm64"):
            return "arm64"
        if machine in ("i386", "i686", "x86"):
            return "x86"
        return machine

    @staticmethod
    def is_64bit() -> bool:
        return sys.maxsize > 2**32
