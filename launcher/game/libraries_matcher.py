import sys
import platform


class LibrariesMatcher:
    @staticmethod
    def get_current_os() -> str:
        if sys.platform == "win32":
            return "windows"
        if sys.platform == "darwin":
            return "osx"
        return "linux"

    @staticmethod
    def get_current_arch() -> str:
        machine = platform.machine().lower()
        if machine in ("amd64", "x86_64"):
            return "x86_64"
        if machine in ("aarch64", "arm64"):
            return "arm64"
        if machine in ("i386", "i686", "x86"):
            return "x86"
        return machine

    @staticmethod
    def match_library(lib: dict) -> bool:
        rules = lib.get("rules", [])
        if not rules:
            return True

        allowed = False
        for rule in rules:
            action = rule.get("action", "")
            os_rule = rule.get("os", {})

            if not os_rule:
                if action == "allow":
                    allowed = True
                elif action == "disallow":
                    allowed = False
                continue

            os_name = os_rule.get("name", "")
            os_version = os_rule.get("version", "")
            arch = os_rule.get("arch", "")

            current_os = LibrariesMatcher.get_current_os()
            current_arch = LibrariesMatcher.get_current_arch()

            matches_os = not os_name or os_name == current_os
            matches_arch = not arch or arch == current_arch
            matches_version = True
            if os_version:
                import re
                matches_version = bool(re.search(os_version, sys.platform))

            matches = matches_os and matches_arch and matches_version
            if matches:
                if action == "allow":
                    allowed = True
                elif action == "disallow":
                    return False

        return allowed

    @staticmethod
    def filter_libraries(libraries: list) -> list:
        result = []
        for lib in libraries:
            if LibrariesMatcher.match_library(lib):
                dl = lib.get("downloads", {})
                artifact = dl.get("artifact", {})
                result.append(artifact)
        return result


def get_native_classifier_key(classifiers: dict) -> str:
    os_name = LibrariesMatcher.get_current_os()
    arch = LibrariesMatcher.get_current_arch()
    if os_name == "windows":
        candidates = ["natives-windows-arm64"] if arch == "arm64" else []
        candidates += ["natives-windows", "natives-windows-64", "natives-windows-x86_64"]
    elif os_name == "osx":
        candidates = ["natives-osx-arm64"] if arch == "arm64" else []
        candidates += ["natives-osx", "natives-osx-x86_64"]
    else:
        candidates = ["natives-linux-arm64"] if arch == "arm64" else []
        candidates += ["natives-linux", "natives-linux-x86_64"]
    for key in candidates:
        if key in classifiers:
            return key
    return ""
