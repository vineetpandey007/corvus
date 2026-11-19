"""
Create an admin analyst account directly in the database — for the very
first account, since /auth/register always creates a regular "analyst"
role (see the TODO in src/api/routes/auth.py about gating self-registration
behind an admin invite flow in production).

Usage:
    python scripts/create_admin.py --username admin --password "change-me-now" --email admin@example.com
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.db.database import SessionLocal, init_db
from src.db.models import User, UserRole
from src.api.auth import hash_password


def main():
    parser = argparse.ArgumentParser(description="Create an admin analyst account.")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True, help="Min 8 characters")
    parser.add_argument(
        "--email", default=None,
        help="Optional, but required for this account to use forgot-password/OTP login later",
    )
    args = parser.parse_args()

    if len(args.password) < 8:
        print("Error: password must be at least 8 characters.")
        sys.exit(1)

    init_db()
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == args.username).first()
        if existing:
            print(f"User '{args.username}' already exists (role={existing.role.value}).")
            sys.exit(1)

        user = User(
            username=args.username,
            email=args.email,
            hashed_password=hash_password(args.password),
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        print(f"Admin user '{args.username}' created successfully.")
        if not args.email:
            print("Note: no --email given — this account can't use forgot-password/OTP login yet.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
