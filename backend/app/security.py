"""Password hashing, caregiver tokens and device keys.

Passwords use PBKDF2-SHA256 from the standard library, so there is no native
bcrypt build to fight with on Windows. Device keys are random, shown once at
creation, and stored only as a SHA-256 hash.
"""
import datetime as dt
import hashlib
import hmac
import os
import secrets

import jwt

from .config import settings

_ITERATIONS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$")
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return hmac.compare_digest(digest.hex(), digest_hex)


def new_device_key() -> str:
    return "sv_" + secrets.token_urlsafe(32)


def hash_device_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def make_token(caregiver_id: int) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    claims = {
        "sub": str(caregiver_id),
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_minutes),
    }
    return jwt.encode(claims, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> int:
    """Return the caregiver id, or raise jwt.PyJWTError."""
    claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    return int(claims["sub"])
