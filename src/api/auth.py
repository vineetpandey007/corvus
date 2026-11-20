"""
Authentication primitives: bcrypt password hashing, JWT issuing/verification
with standard claims (sub, role, iat, exp, jti), constant-time API key
validation, and secure token/OTP helpers.
"""

import hashlib
import hmac
import os
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User

SECRET_KEY = os.environ.get("JWT_SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
API_SERVICE_KEY = os.environ.get("API_SERVICE_KEY")

PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 30
OTP_CODE_EXPIRE_MINUTES = 10
OTP_MAX_ATTEMPTS = 5

# Pre-computed dummy hash so non-existent user logins incur equivalent bcrypt CPU work
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(b"corvus-constant-time-dummy", bcrypt.gensalt()).decode("utf-8")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _get_secret_key() -> str:
    key = os.environ.get("JWT_SECRET_KEY") or SECRET_KEY
    if not key:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"` "
            "and add it to your .env file."
        )
    return key


def hash_password(password: str) -> str:
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pw_bytes = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))


def verify_password_constant_time(plain_password: str, hashed_password: Optional[str]) -> bool:
    """
    Run bcrypt verification even when `hashed_password` is None (unknown user)
    to prevent account enumeration via response-latency timing attacks.
    """
    target_hash = hashed_password or _DUMMY_BCRYPT_HASH
    valid = verify_password(plain_password, target_hash)
    return bool(hashed_password) and valid


def create_access_token(subject: str, role: str) -> str:
    secret = _get_secret_key()
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": subject,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": expire,
        "jti": pysecrets.token_hex(16),
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    secret = _get_secret_key()
    try:
        return jwt.decode(token, secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    x_api_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate via JWT Bearer token or constant-time X-API-Key header."""
    configured_api_key = os.environ.get("API_SERVICE_KEY") or API_SERVICE_KEY
    if x_api_key and configured_api_key and hmac.compare_digest(x_api_key, configured_api_key):
        return User(id=0, username="service-account", role="admin")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide a Bearer token or X-API-Key header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    username = payload.get("sub")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")

    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def generate_secure_token(nbytes: int = 32) -> str:
    """Cryptographically random URL-safe token for password-reset links."""
    return pysecrets.token_urlsafe(nbytes)


def generate_otp_code() -> str:
    """Random 6-digit numeric OTP code, zero-padded."""
    return f"{pysecrets.randbelow(1_000_000):06d}"


def hash_token(token: str) -> str:
    """SHA-256 lookup digest for high-entropy reset tokens and rate-limited OTPs."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """Look up a user by exact username or case-insensitive email."""
    cleaned = identifier.strip()
    if not cleaned:
        return None
    return (
        db.query(User)
        .filter((User.username == cleaned) | (func.lower(User.email) == cleaned.lower()))
        .first()
    )