"""
SQLAlchemy models: analyst users, investigation cases, and the posts/
aliases ingested into each case. The identity graph itself (nodes/edges)
lives in the graph backend (NetworkX in-memory or Neo4j) — these tables
are the persistent, relational side: who did what, and which case it
belongs to.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Enum, Boolean
from sqlalchemy.orm import relationship

from src.db.database import Base


class UserRole(str, enum.Enum):
    analyst = "analyst"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(64), unique=True, index=True, nullable=False)
    # Nullable at the DB level for backward compatibility with accounts
    # created before email support was added (see
    # database.py::_run_lightweight_migrations, which ALTERs existing
    # SQLite databases to add this column). New registrations always
    # provide one — enforced in the /auth/register request schema, not
    # here, since SQLite can't easily add a NOT NULL column without a
    # default to an existing table with existing rows.
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=False)
    # Set only for accounts created/linked via Google or GitHub login.
    # oauth_subject is "{provider}:{provider's user id}" (e.g.
    # "google:10987654321") — one column, globally unique, rather than a
    # composite (provider, id) key, to keep the lightweight SQLite
    # migration in database.py a plain ADD COLUMN. An OAuth-only account
    # still gets a random, never-told-to-the-user password hash (see
    # routes/oauth.py) rather than a nullable hashed_password, so the
    # existing NOT NULL column never needs a schema change.
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
    legal_basis = Column(Text, nullable=True)  # e.g. warrant/order reference — see ETHICS_AND_LEGAL.md
    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    owner = relationship("User", back_populates="cases")
    posts = relationship("CasePost", back_populates="case", cascade="all, delete-orphan")


class CasePost(Base):
    """
    A single ingested post/alias record tied to a case. `text_encrypted`
    stores the post text encrypted at rest — see src/utils/encryption.py.
    """
    __tablename__ = "case_posts"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    alias = Column(String(128), nullable=False, index=True)
    source = Column(String(255), nullable=True)
    text_encrypted = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    case = relationship("Case", back_populates="posts")


class PasswordResetToken(Base):
    """
    A single-use password-reset token. Only `token_hash` (SHA-256 of the
    real token) is stored — never the token itself — so a database leak
    doesn't hand over valid reset tokens the way storing them in plaintext
    would. The real token only ever exists in the emailed link and in
    memory for the length of one request; see src/api/auth.py's
    generate_secure_token()/hash_token().
    """
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token_hash = Column(String(64), unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User")


class OtpCode(Base):
    """
    A single-use one-time-passcode for OTP-based login. Like
    PasswordResetToken, only a hash of the code is stored. `attempts`
    tracks failed verification attempts against this specific code so a
    brute-force guess of the 6-digit code can be capped independently of
    the API's general rate limiting.
    """
    __tablename__ = "otp_codes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    code_hash = Column(String(64), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    user = relationship("User")
