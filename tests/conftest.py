"""
Pytest configuration — sets safe, throwaway secrets and an isolated test
database BEFORE any application module is imported, so test runs never
touch real .env secrets or the real data/processed/ directory.
"""

import os
import tempfile

# Must happen before any `src.*` import anywhere in the test session.
os.environ.setdefault("JWT_SECRET_KEY", "pytest-only-not-a-real-secret")
os.environ.setdefault("ENCRYPTION_KEY", "36hU3RsDyWKriDuUcaF8bKL5G8sxRiSWzwzl9D8S6Jk=")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("EMAIL_BACKEND", "dev")

_test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_test_db_path}")

# Isolates get_app_data_dir() (audit log, blockchain cache, and the dev
# email outbox that test_api.py reads reset tokens/OTP codes from) into a
# throwaway directory — otherwise it would default to the real project's
# data/processed/, polluting it across test runs.
_test_app_data_dir = tempfile.mkdtemp(prefix="dwta_test_appdata_")
os.environ.setdefault("APP_DATA_DIR", _test_app_data_dir)
