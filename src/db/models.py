"""
SQLAlchemy models: analyst users, investigation cases, encrypted posts with
SHA-256 evidence digests, auth tokens, and hash-chained forensic audit logs.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from src.db.database import Base


class UserRole(str, enum.Enum):
    analyst = "analyst"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    oauth_provider = Column(String(32), nullable=True)
    oauth_subject = Column(String(255), unique=True, index=True, nullable=True)
    role = Column(Enum(UserRole), default=UserRole.analyst, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    cases = relationship("Case", back_populates="owner")


class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(String(64), unique=True, index=True, nullable=False)
    title = Column(String(255), nullable=False)
    legal_basis = Column(Text, nullable=True)
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="cases")
    posts = relationship("CasePost", back_populates="case", cascade="all, delete-orphan")


class CasePost(Base):
    """
    A single ingested post/alias record tied to a case. `text_encrypted`
    stores the post text encrypted at rest; `evidence_sha256` records the
    SHA-256 digest of the original plaintext at ingestion time.
    """
    __tablename__ = "case_posts"
    __table_args__ = (
        Index("ix_case_posts_case_alias", "case_id", "alias"),
    )

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False)
    alias = Column(String(128), nullable=False, index=True)
    source = Column(String(255), nullable=True)
    text_encrypted = Column(Text, nullable=False)
    evidence_sha256 = Column(String(64), nullable=True, index=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    case = relationship("Case", back_populates="posts")


class PasswordResetToken(Base):
    """Single-use password-reset token (only SHA-256 token_hash is persisted)."""
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User")


class OtpCode(Base):
    """Single-use one-time passcode with per-code brute-force attempt counter."""
    __tablename__ = "otp_codes"
    __table_args__ = (
        Index("ix_otp_codes_user_used", "user_id", "used"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User")


class AuditLog(Base):
    """
    Append-only, hash-chained forensic audit trail. Each row links to the
    previous row via `prev_hash` -> `entry_hash` (SHA-256) so tampering or
    row deletion can be detected programmatically.
    """
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False, index=True)
    actor = Column(String(128), nullable=False, index=True)
    action = Column(String(64), nullable=False, index=True)
    case_id = Column(String(64), nullable=True, index=True)
    details_json = Column(Text, nullable=True)
    prev_hash = Column(String(64), nullable=False)
    entry_hash = Column(String(64), unique=True, nullable=False)