from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Optional


class ServerAuthPlugin(ABC):
    @abstractmethod
    def name(self) -> str:
        ...

    @abstractmethod
    def apply(self, java_command: List[str], api_url: str, server_dir: str) -> List[str]:
        ...


class InjectorPlugin(ServerAuthPlugin):
    def __init__(self, injector_filename: str = "authlib-injector.jar"):
        self.injector_filename = injector_filename or "authlib-injector.jar"

    def name(self) -> str:
        return "authlib-injector"

    def apply(self, java_command: List[str], api_url: str, server_dir: str) -> List[str]:
        if not api_url:
            return java_command
        filename = self.injector_filename or "authlib-injector.jar"
        injector_path = Path(server_dir) / filename
        if injector_path.exists():
            java_command.insert(1, f"-javaagent:{injector_path}={api_url}")
        return java_command


PLUGIN_REGISTRY: dict[str, type[ServerAuthPlugin]] = {
    "injector": InjectorPlugin,
    "": InjectorPlugin,
}


def create_server_auth_plugin(name: str = "", **kwargs) -> ServerAuthPlugin:
    cls = PLUGIN_REGISTRY.get(name) or InjectorPlugin
    valid_params = {}
    import inspect
    sig = inspect.signature(cls.__init__)
    for param_name in sig.parameters:
        if param_name != "self" and param_name in kwargs:
            valid_params[param_name] = kwargs[param_name]
    return cls(**valid_params)
