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
    user_properties: dict = field(default_factory=dict)


class YggdrasilAuth:
    def __init__(self, auth_url: str):
        self.auth_url = auth_url.rstrip("/")
        self.session = YggdrasilSession()

    def _make_request(self, endpoint: str, payload: dict) -> dict:
        resp = requests.post(
            f"{self.auth_url}/{endpoint}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    def register(self, username: str, password: str, email: str = "") -> YggdrasilSession:
        payload = {
            "username": username,
            "password": password,
            "email": email,
        }
        data = self._make_request("register", payload)
        self.session.access_token = data.get("accessToken", "")
        self.session.client_token = data.get("clientToken", "")
        sel = data.get("selectedProfile", {})
        self.session.selected_profile = sel
        if sel:
            self.session.uuid = sel.get("id", "")
            self.session.display_name = sel.get("name", "")
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
        avail = data.get("availableProfiles", [])
        self.session.available_profiles = avail
        sel = data.get("selectedProfile", {})
        self.session.selected_profile = sel
        if sel:
            self.session.uuid = sel.get("id", "")
            self.session.display_name = sel.get("name", "")
        elif avail:
            p = avail[0]
            self.session.uuid = p.get("id", "")
            self.session.display_name = p.get("name", "")
        self.session.username = username
        self.session.user_properties = data.get("user", {}).get("properties", {})
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
        sel = data.get("selectedProfile", {})
        self.session.selected_profile = sel
        if sel:
            self.session.uuid = sel.get("id", "")
            self.session.display_name = sel.get("name", "")
        return self.session

    def validate(self, access_token: str) -> bool:
        try:
            self._make_request("validate", {"accessToken": access_token})
            return True
        except requests.RequestException:
            return False

    def signout(self, username: str, password: str):
        self._make_request("signout", {"username": username, "password": password})

    def invalidate(self, access_token: str):
        self._make_request("invalidate", {"accessToken": access_token})

    def join_server(self, access_token: str, profile_id: str, server_id: str):
        self._make_request("join", {
            "accessToken": access_token,
            "selectedProfile": profile_id,
            "serverId": server_id,
        })

    def has_joined(self, username: str, server_id: str) -> Optional[dict]:
        try:
            resp = requests.get(
                f"{self.auth_url}/hasJoined",
                params={"username": username, "serverId": server_id},
                timeout=REQUEST_TIMEOUT,
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
