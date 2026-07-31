import socket
import struct
import json
import time


def _pack_varint(value: int) -> bytes:
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _read_varint(sock: socket.socket) -> int:
    num = 0
    for i in range(5):
        data = sock.recv(1)
        if not data:
            raise EOFError("connection closed")
        val = data[0]
        num |= (val & 0x7F) << (7 * i)
        if not (val & 0x80):
            return num
    raise ValueError("varint too big")


def _read_fully(sock: socket.socket, length: int) -> bytes:
    data = b""
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise EOFError("connection closed")
        data += chunk
    return data


def probe(host: str, port: int, timeout: float = 3.0) -> dict:
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            host_b = host.encode("utf-8")
            handshake = bytearray()
            handshake += _pack_varint(0)
            handshake += _pack_varint(767)
            handshake += _pack_varint(len(host_b)) + host_b
            handshake += struct.pack(">H", port & 0xFFFF)
            handshake += b"\x01"
            sock.sendall(_pack_varint(len(handshake)) + bytes(handshake))
            sock.sendall(b"\x01\x00")
            _read_varint(sock)
            pid = _read_varint(sock)
            if pid != 0:
                return {"online": False, "error": "unexpected packet"}
            slen = _read_varint(sock)
            payload = _read_fully(sock, slen)
            latency = int((time.monotonic() - start) * 1000)
            status = json.loads(payload.decode("utf-8"))
            players = status.get("players", {}) or {}
            version = status.get("version", {}) or {}
            desc = status.get("description")
            if isinstance(desc, dict):
                motd = desc.get("text", "")
            else:
                motd = str(desc or "")
            return {
                "online": True,
                "latency_ms": latency,
                "players_online": int(players.get("online", 0) or 0),
                "players_max": int(players.get("max", 0) or 0),
                "version": version.get("name", "") or "",
                "description": motd,
            }
    except (OSError, EOFError, ValueError, json.JSONDecodeError):
        return {"online": False}
