"""
Authentication: password hashing (bcrypt, called directly), JWT issuing/
verification (python-jose), and FastAPI dependencies to protect routes.

Two ways to authenticate against the API:
1. JWT bearer token — obtained via POST /auth/login, used by the frontend
   dashboard for analyst sessions.
2. Static API key (X-API-Key header) — for service-to-service/automation
   use. Configure via API_SERVICE_KEY in .env.

Analysts are stored in the `users` table (src/db/models.py) with bcrypt-
hashed passwords — plaintext passwords are never stored or logged.
"""

import hashlib
import os
import secrets as pysecrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status, Header
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
import bcrypt
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

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _require_secret_key():
    if not SECRET_KEY:
        raise RuntimeError(
            "JWT_SECRET_KEY is not set. Generate one with "
            "`python -c \"import secrets; print(secrets.token_urlsafe(32))\"` "
            "and add it to your .env file."
        )


def hash_password(password: str) -> str:
    # bcrypt has a hard 72-byte input limit — truncate defensively so a very
    # long passphrase doesn't raise instead of just being capped, matching
    # common bcrypt-based auth implementations.
    pw_bytes = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    pw_bytes = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))


def create_access_token(subject: str, role: str) -> str:
    _require_secret_key()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    _require_secret_key()
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
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
    """
    FastAPI dependency that authenticates a request via either a JWT bearer
    token or a static service API key. Raises 401 if neither is valid.
    """
    # Service-to-service auth via API key bypasses per-user lookup.
    if x_api_key and API_SERVICE_KEY and x_api_key == API_SERVICE_KEY:
        # Return a lightweight pseudo-user for service calls.
        return User(id=0, username="service-account", role="admin")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated — provide a Bearer token or X-API-Key header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_access_token(token)
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# --- Password reset / OTP helpers -------------------------------------
# Shared by src/api/routes/auth.py. Kept here alongside the rest of the
# auth primitives rather than duplicated in the routes module.

def generate_secure_token(nbytes: int = 32) -> str:
    """A cryptographically random, URL-safe token for password-reset links."""
    return pysecrets.token_urlsafe(nbytes)


def generate_otp_code() -> str:
    """A random 6-digit numeric OTP code, zero-padded (e.g. '004821')."""
    return f"{pysecrets.randbelow(1_000_000):06d}"


def hash_token(token: str) -> str:
    """
    SHA-256 hash for reset tokens / OTP codes before storing them.

    Deliberately NOT bcrypt: bcrypt's slow, salted hashing exists to resist
    brute-forcing a *low-entropy, user-chosen* password. A reset token is a
    256-bit random value and an OTP is validated with its own expiry +
    attempt-count limit (see OTP_MAX_ATTEMPTS) — a fast, unsalted SHA-256
    lookup hash is the right tool here, the same way session/API tokens
    are commonly hashed.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_user_by_identifier(db: Session, identifier: str) -> Optional[User]:
    """Look up a user by username OR email — used by /auth/login,
    /auth/forgot-password, and /auth/otp/request so an analyst can use
    whichever they remember."""
    return (
        db.query(User)
        .filter((User.username == identifier) | (User.email == identifier))
        .first()
    )
