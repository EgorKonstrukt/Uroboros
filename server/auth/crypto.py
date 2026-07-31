import hashlib
import hmac
import secrets

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 32

_PREFIX = "scrypt"


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_LEN,
    )
    return f"{_PREFIX}${salt.hex()}${digest.hex()}"


def _is_legacy_sha256(password_hash: str) -> bool:
    if not password_hash:
        return False
    return "$" not in password_hash or not password_hash.startswith(_PREFIX)


def check_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    if _is_legacy_sha256(password_hash):
        return _check_legacy(password, password_hash)
    try:
        _, salt_hex, digest_hex = password_hash.split("$", 2)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    try:
        actual = hashlib.scrypt(
            password.encode("utf-8"), salt=salt,
            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
            dklen=SCRYPT_LEN,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _check_legacy(password: str, password_hash: str) -> bool:
    if "$" in password_hash:
        salt, hsh = password_hash.split("$", 1)
        expected = hashlib.sha256((salt + password).encode()).hexdigest()
    else:
        expected = hashlib.sha256(password.encode()).hexdigest()
    return hmac.compare_digest(hsh, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def check_token(token: str, token_hash: str) -> bool:
    if not token or not token_hash:
        return False
    return hmac.compare_digest(hash_token(token), token_hash)


def new_uuid() -> str:
    return secrets.token_hex(16)


def new_token() -> str:
    return secrets.token_urlsafe(32)
