from pathlib import Path
from typing import Optional

from server.models import InstanceModel


def instance_model_to_dict(inst: InstanceModel) -> dict:
    return {
        "id": inst.id,
        "name": inst.name,
        "project_id": inst.project_id or "",
        "modpack_id": inst.modpack_id or "",
        "enabled": inst.enabled,
        "server_dir": inst.server_dir or str(Path.cwd()),
        "server_filename": inst.server_filename,
        "java_executable_path": inst.java_executable_path,
        "max_memory": inst.max_memory,
        "min_memory": inst.min_memory,
        "additional_flags": inst.additional_flags,
        "arguments": inst.arguments,
        "api_url": inst.api_url,
        "auth_plugin": inst.auth_plugin,
        "injector_filename": inst.injector_filename,
        "auto_restart": inst.auto_restart,
        "auto_accept_eula": inst.auto_accept_eula,
        "version": inst.version or "",
        "jar_url": inst.jar_url or "",
        "created_at": str(inst.created_at) if inst.created_at else "",
    }


def dict_to_instance_model(data: dict, instance: Optional[InstanceModel] = None) -> InstanceModel:
    if instance is None:
        instance = InstanceModel()
    for key in ("id", "name", "project_id", "modpack_id", "enabled",
                "server_dir", "server_filename", "java_executable_path",
                "max_memory", "min_memory", "additional_flags", "arguments",
                "api_url", "auth_plugin", "injector_filename",
                "auto_restart", "auto_accept_eula", "version", "jar_url"):
        if key in data:
            setattr(instance, key, data[key])
    if not instance.server_dir:
        instance.server_dir = str(Path.cwd())
    return instance
