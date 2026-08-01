import sys
from pathlib import Path

_THEME_DIR = Path(__file__).parent
_THEMES = {
    "dark": _THEME_DIR / "theme.qss",
    "light": _THEME_DIR / "theme_light.qss",
}


def detect_system_theme() -> str:
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if value else "dark"
        except OSError:
            pass
    return "dark"


def resolve_theme(mode: str) -> str:
    if mode == "light":
        return "light"
    if mode == "dark":
        return "dark"
    return detect_system_theme()


def load_theme(mode: str) -> str:
    path = _THEMES.get(resolve_theme(mode))
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return ""
