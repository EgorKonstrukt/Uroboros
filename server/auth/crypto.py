import hashlib
import os
import uuid


def hash_password(password: str, salt: str = "") -> str:
    if salt:
        return f"{salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"
    salt = os.urandom(16).hex()
    return f"{salt}${hashlib.sha256((salt + password).encode()).hexdigest()}"


def check_password(password: str, password_hash: str) -> bool:
    if "$" in password_hash:
        salt, hsh = password_hash.split("$", 1)
        return hsh == hashlib.sha256((salt + password).encode()).hexdigest()
    return password_hash == hashlib.sha256(password.encode()).hexdigest()


def new_uuid() -> str:
    return str(uuid.uuid4()).replace("-", "")


def new_token() -> str:
    return str(uuid.uuid4()).replace("-", "")
