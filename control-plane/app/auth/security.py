"""Password hashing and token primitives. No database access here."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings

_hasher = PasswordHasher()  # Argon2id with library defaults (OWASP-aligned)
# Used when the email is unknown, so a failed login takes the same time either way.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def create_access_token(user_id: uuid.UUID, now: datetime | None = None) -> tuple[str, int]:
    """Signed JWT carrying only the user's identity. Returns (token, lifetime in seconds)."""
    s = get_settings()
    issued = now or datetime.now(UTC)
    lifetime = timedelta(minutes=s.access_token_minutes)
    claims = {
        "sub": str(user_id),
        "iss": s.jwt_issuer,
        "aud": s.jwt_audience,
        "iat": issued,
        "exp": issued + lifetime,
        "jti": uuid.uuid4().hex,
        "typ": "access",
    }
    token = jwt.encode(claims, s.jwt_secret.get_secret_value(), algorithm=ALGORITHM)
    return token, int(lifetime.total_seconds())


class InvalidTokenError(Exception):
    pass


def decode_access_token(token: str) -> uuid.UUID:
    """Verify signature, issuer, audience and expiry; return the user ID."""
    s = get_settings()
    try:
        claims: dict[str, Any] = jwt.decode(
            token,
            s.jwt_secret.get_secret_value(),
            algorithms=[ALGORITHM],
            issuer=s.jwt_issuer,
            audience=s.jwt_audience,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
        if claims.get("typ") != "access":
            raise InvalidTokenError("wrong token type")
        return uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, ValueError) as exc:
        raise InvalidTokenError(str(exc)) from exc


def new_refresh_token() -> tuple[str, str]:
    """Random opaque refresh token. Returns (raw token for the cookie, hash for the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()