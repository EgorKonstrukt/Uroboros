from pathlib import Path
from typing import Any, Optional

import requests


REQUEST_TIMEOUT = 10


class APIManager:
    def __init__(self, base_url: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl

    def _get(self, endpoint: str, params: dict = None) -> Any:
        resp = requests.get(
            f"{self.base_url}/{endpoint}",
            params=params,
            timeout=REQUEST_TIMEOUT,
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, data: dict = None) -> Any:
        resp = requests.post(
            f"{self.base_url}/{endpoint}",
            json=data or {},
            timeout=REQUEST_TIMEOUT,
            verify=self.verify_ssl,
        )
        resp.raise_for_status()
        return resp.json()

    def get_project(self, project_id: str) -> dict:
        return self._get(f"launcher/sync/{project_id}")

    def get_modpack_files(self, project_id: str, modpack_id: str) -> list:
        result = self._get(f"launcher/projects/{project_id}/modpacks/{modpack_id}/files")
        return result.get("items", [])

    def get_servers(self, project_id: str) -> list:
        result = self._get(f"launcher/projects/{project_id}/servers")
        return result.get("items", [])

    def get_bans(self, uuid: str) -> dict:
        return self._get(f"launcher/bans/{uuid}")

    def download_modpack_file(self, project_id: str, modpack_id: str, filename: str, dest: Path):
        url = f"{self.base_url}/launcher/projects/{project_id}/modpacks/{modpack_id}/download/{filename}"
        resp = requests.get(url, timeout=REQUEST_TIMEOUT * 6, stream=True, verify=self.verify_ssl)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

    def ping_server(self, host: str, port: int = 25565) -> Optional[dict]:
        try:
            resp = requests.get(
                f"https://api.mcstatus.io/v2/java/{host}:{port}",
                timeout=REQUEST_TIMEOUT,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None
