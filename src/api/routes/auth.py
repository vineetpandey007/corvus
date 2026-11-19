"""
Auth routes: registration, login (username OR email), forgot/reset
password, and OTP login — all issuing the same JWT shape on success.

Registration is intentionally simple for now (no email verification) —
for production, gate POST /auth/register behind an existing admin account
or an invite-code system rather than leaving it open. See the TODO below.

Password reset and OTP codes are "sent" via src/utils/email_service.py,
which defaults to a dev-mode console/log backend — see that module's
docstring and docs/SETUP.md for switching to real SMTP.
"""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from src.db.database import get_db
from src.db.models import User, UserRole, PasswordResetToken, OtpCode
from src.api.auth import (
    hash_password,
    verify_password,
    create_access_token,
    generate_secure_token,
    generate_otp_code,
    hash_token,
    get_user_by_identifier,
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES,
    OTP_CODE_EXPIRE_MINUTES,
    OTP_MAX_ATTEMPTS,
)
from src.api.rate_limit import limiter
from src.utils.email_service import send_email
from src.utils.config import load_config

router = APIRouter(prefix="/auth", tags=["auth"])

# A deliberately simple, dependency-free email format check — good enough
# to catch typos and obviously-malformed input without pulling in the
# email-validator package for a single regex's worth of value.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

FRONTEND_BASE_URL = load_config().get("app", {}).get("frontend_base_url", "http://localhost:5173")


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes even though we store UTC ones; treat
    naive values as UTC so comparisons against timezone-aware 'now' don't
    raise TypeError. (Postgres returns aware datetimes and passes through.)"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: str
    password: str = Field(min_length=8)

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v.lower()


class LoginRequest(BaseModel):
    identifier: str  # username OR email
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ForgotPasswordRequest(BaseModel):
    identifier: str  # username or email


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8)


class OtpRequestRequest(BaseModel):
    identifier: str


class OtpVerifyRequest(BaseModel):
    identifier: str
    code: str


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def register(request: Request, req: RegisterRequest, db: Session = Depends(get_db)):
    # TODO(production): gate this behind an admin invite/approval flow
    # rather than open self-registration, given the sensitivity of case data.
    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")
    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=hash_password(req.password),
        role=UserRole.analyst,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = create_access_token(subject=user.username, role=user.role.value)
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, req: LoginRequest, db: Session = Depends(get_db)):
    user = get_user_by_identifier(db, req.identifier)
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = create_access_token(subject=user.username, role=user.role.value)
    return TokenResponse(access_token=token)


@router.post("/forgot-password")
@limiter.limit("5/minute")
def forgot_password(request: Request, req: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Always returns the same generic message whether or not the account
    exists — this prevents an attacker from using this endpoint to enumerate
    valid usernames/emails. The actual reset link only goes out (via
    send_email, dev-mode logs it) when the account is real.
    """
    generic_response = {
        "message": "If an account with that username or email exists, a password reset link has been sent."
    }

    user = get_user_by_identifier(db, req.identifier)
    if not user or not user.email:
        return generic_response

    raw_token = generate_secure_token()
    reset_token = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES),
    )
    db.add(reset_token)
    db.commit()

    reset_link = f"{FRONTEND_BASE_URL}/#/reset-password/{raw_token}"
    send_email(
        to=user.email,
        subject="Password Reset — Dark Web Identity Correlation Toolkit",
        body=(
            f"Hi {user.username},\n\n"
            f"A password reset was requested for your account. This link expires in "
            f"{PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes:\n\n{reset_link}\n\n"
            f"If you didn't request this, you can safely ignore this email."
        ),
    )
    return generic_response


@router.post("/reset-password")
@limiter.limit("10/minute")
def reset_password(request: Request, req: ResetPasswordRequest, db: Session = Depends(get_db)):
    token_hash = hash_token(req.token)
    reset_token = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used.is_(False))
        .first()
    )
    if not reset_token or _as_utc(reset_token.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")

    user.hashed_password = hash_password(req.new_password)
    reset_token.used = True
    db.commit()

    return {"message": "Password has been reset. You can now log in with your new password."}


@router.post("/otp/request")
@limiter.limit("5/minute")
def otp_request(request: Request, req: OtpRequestRequest, db: Session = Depends(get_db)):
    """Same generic-response pattern as forgot-password, for the same
    user-enumeration-prevention reason."""
    generic_response = {"message": "If an account with that username or email exists, an OTP code has been sent."}

    user = get_user_by_identifier(db, req.identifier)
    if not user or not user.email:
        return generic_response

    raw_code = generate_otp_code()
    otp = OtpCode(
        user_id=user.id,
        code_hash=hash_token(raw_code),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_CODE_EXPIRE_MINUTES),
    )
    db.add(otp)
    db.commit()

    send_email(
        to=user.email,
        subject="Your One-Time Login Code",
        body=(
            f"Hi {user.username},\n\nYour one-time login code is: {raw_code}\n\n"
            f"This code expires in {OTP_CODE_EXPIRE_MINUTES} minutes and can be used once."
        ),
    )
    return generic_response


@router.post("/otp/verify", response_model=TokenResponse)
@limiter.limit("10/minute")
def otp_verify(request: Request, req: OtpVerifyRequest, db: Session = Depends(get_db)):
    user = get_user_by_identifier(db, req.identifier)
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    otp = (
        db.query(OtpCode)
        .filter(OtpCode.user_id == user.id, OtpCode.used.is_(False))
        .order_by(OtpCode.created_at.desc())
        .first()
    )
    if not otp or _as_utc(otp.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    if otp.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many attempts — request a new code")

    if hash_token(req.code) != otp.code_hash:
        otp.attempts += 1
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    otp.used = True
    db.commit()

    token = create_access_token(subject=user.username, role=user.role.value)
    return TokenResponse(access_token=token)
