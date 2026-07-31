import json
import uuid
import hashlib
from dataclasses import dataclass, field
from typing import Optional

import requests


REQUEST_TIMEOUT = 10


@dataclass
class YggdrasilSession:
    access_token: str = ""
    client_token: str = ""
    uuid: str = ""
    username: str = ""
    display_name: str = ""
    selected_profile: dict = field(default_factory=dict)
    available_profiles: list = field(default_factory=list)
    user_properties: list = field(default_factory=list)


class YggdrasilAuth:
    def __init__(self, auth_url: str, verify_ssl: bool = True):
        self.auth_url = auth_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.session = YggdrasilSession()

    def _make_request(self, endpoint: str, payload: dict) -> dict:
        try:
            resp = requests.post(
                f"{self.auth_url}/{endpoint}",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=REQUEST_TIMEOUT,
                verify=self.verify_ssl,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            try:
                data = e.response.json()
                msg = data.get("errorMessage") or data.get("error") or str(e)
            except ValueError:
                msg = str(e)
            raise RuntimeError(msg) from e

    def _apply_user_properties(self, data: dict):
        user = data.get("user") or {}
        props = user.get("properties") or []
        self.session.user_properties = props if isinstance(props, list) else []

    def _apply_profile(self, data: dict):
        sel = data.get("selectedProfile", {})
        self.session.selected_profile = sel
        if sel:
            self.session.uuid = sel.get("id", "")
            self.session.display_name = sel.get("name", "")
            return
        avail = data.get("availableProfiles", [])
        self.session.available_profiles = avail
        if avail:
            p = avail[0]
            self.session.uuid = p.get("id", "")
            self.session.display_name = p.get("name", "")

    def register(self, username: str, password: str, email: str = "") -> YggdrasilSession:
        payload = {
            "username": username,
            "password": password,
            "email": email,
        }
        data = self._make_request("register", payload)
        self.session.access_token = data.get("accessToken", "")
        self.session.client_token = data.get("clientToken", "")
        self._apply_profile(data)
        self._apply_user_properties(data)
        self.session.username = username
        return self.session

    def authenticate(self, username: str, password: str, client_token: str = "") -> YggdrasilSession:
        if not client_token:
            client_token = str(uuid.uuid4())
        payload = {
            "agent": {"name": "Minecraft", "version": 1},
            "username": username,
            "password": password,
            "clientToken": client_token,
            "requestUser": True,
        }
        data = self._make_request("authenticate", payload)
        self.session.access_token = data.get("accessToken", "")
        self.session.client_token = data.get("clientToken", client_token)
        self._apply_profile(data)
        self._apply_user_properties(data)
        self.session.username = username
        return self.session

    def refresh(self, access_token: str, client_token: str) -> YggdrasilSession:
        payload = {
            "accessToken": access_token,
            "clientToken": client_token,
            "requestUser": True,
        }
        data = self._make_request("refresh", payload)
        self.session.access_token = data.get("accessToken", "")
        self.session.client_token = data.get("clientToken", client_token)
        self._apply_profile(data)
        self._apply_user_properties(data)
        return self.session

    def validate(self, access_token: str, client_token: str = "") -> bool:
        try:
            payload = {"accessToken": access_token}
            if client_token:
                payload["clientToken"] = client_token
            self._make_request("validate", payload)
            return True
        except (requests.RequestException, RuntimeError):
            return False

    def signout(self, username: str, password: str):
        self._make_request("signout", {"username": username, "password": password})

    def invalidate(self, access_token: str, client_token: str = ""):
        payload = {"accessToken": access_token}
        if client_token:
            payload["clientToken"] = client_token
        self._make_request("invalidate", payload)

    def join_server(self, access_token: str, profile_id: str, server_id: str):
        self._make_request("join", {
            "accessToken": access_token,
            "selectedProfile": profile_id,
            "serverId": server_id,
        })

    def upload_skin(self, access_token: str, file_path, model: str = "classic") -> dict:
        if model not in ("classic", "slim"):
            model = "classic"
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{self.auth_url}/skin",
                headers={"Authorization": f"Bearer {access_token}"},
                files={"file": f},
                data={"model": model},
                timeout=REQUEST_TIMEOUT * 4,
                verify=self.verify_ssl,
            )
        if resp.status_code != 200:
            try:
                data = resp.json()
                msg = data.get("errorMessage") or data.get("error") or str(resp.status_code)
            except ValueError:
                msg = f"HTTP {resp.status_code}"
            raise RuntimeError(msg)
        return resp.json()

    def remove_skin(self, access_token: str) -> dict:
        resp = requests.post(
            f"{self.auth_url}/skin/remove",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=REQUEST_TIMEOUT,
            verify=self.verify_ssl,
        )
        if resp.status_code != 200:
            try:
                data = resp.json()
                msg = data.get("errorMessage") or data.get("error") or str(resp.status_code)
            except ValueError:
                msg = f"HTTP {resp.status_code}"
            raise RuntimeError(msg)
        return resp.json()

    def has_joined(self, username: str, server_id: str) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{self.auth_url}/hasJoined",
                params={"username": username, "serverId": server_id},
                timeout=REQUEST_TIMEOUT,
                verify=self.verify_ssl,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    def profile(self, profile_id: str) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{self.auth_url}/profile/{profile_id}",
                timeout=REQUEST_TIMEOUT,
                verify=self.verify_ssl,
            )
            if resp.status_code == 200:
                return resp.json()
        except requests.RequestException:
            pass
        return None

    @staticmethod
    def generate_server_id(shared_secret: bytes, server_public_key: bytes) -> str:
        digest = hashlib.sha256()
        digest.update(shared_secret)
        digest.update(server_public_key)
        return digest.hexdigest()
