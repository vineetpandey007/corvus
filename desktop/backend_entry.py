"""
PyInstaller entry point for the bundled desktop backend.

This is NOT the same as running `uvicorn src.api.main:app` directly — it
does one critical extra thing first: bootstrapping JWT_SECRET_KEY and
ENCRYPTION_KEY into the environment automatically if they're missing,
persisted in the OS-appropriate per-user app-data directory that Electron
passes in via APP_DATA_DIR.

This MUST happen before `src.api.main` (or anything importing
src.api.auth / src.utils.encryption) is imported, since both of those
modules read their required secrets from os.environ at import time, not
lazily. Get the import order here wrong and the packaged app fails
immediately on startup with a "JWT_SECRET_KEY is not set" error.

Normal (non-desktop) use of this codebase — `uvicorn src.api.main:app`
directly, or Docker — is completely unaffected by this file; it's only
ever invoked as the desktop app's bundled executable entry point.
"""

import os
import sys
from pathlib import Path

# Ensure the project root (parent of desktop/) is importable as `src.*`,
# both when run directly from source and when PyInstaller has frozen this
# into an executable (PyInstaller bundles the whole `src` package alongside
# this entry point — see desktop/backend.spec's `datas`/hidden imports).
if getattr(sys, "frozen", False):
    # sys._MEIPASS is PyInstaller's temp extraction directory at runtime.
    sys.path.insert(0, sys._MEIPASS)
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _bootstrap_desktop_secrets() -> None:
    """
    If APP_DATA_DIR is set (Electron sets this before spawning us), ensure
    JWT_SECRET_KEY and ENCRYPTION_KEY exist in a secrets.env file there,
    generating them on first run, then load them into os.environ.

    If APP_DATA_DIR is NOT set, this is a no-op — the app relies on a real
    .env file or externally-set environment variables instead, exactly as
    it does for server/Docker deployments.
    """
    app_data_dir = os.environ.get("APP_DATA_DIR")
    if not app_data_dir:
        return

    os.makedirs(app_data_dir, exist_ok=True)
    secrets_path = os.path.join(app_data_dir, "secrets.env")

    from dotenv import dotenv_values

    existing = dict(dotenv_values(secrets_path)) if os.path.exists(secrets_path) else {}

    changed = False
    if not existing.get("JWT_SECRET_KEY"):
        import secrets as pysecrets
        existing["JWT_SECRET_KEY"] = pysecrets.token_urlsafe(32)
        changed = True

    if not existing.get("ENCRYPTION_KEY"):
        from cryptography.fernet import Fernet
        existing["ENCRYPTION_KEY"] = Fernet.generate_key().decode()
        changed = True

    if changed:
        # Restrictive permissions where the OS supports it (no-op on Windows,
        # which doesn't use POSIX permission bits the same way).
        with open(secrets_path, "w") as f:
            for k, v in existing.items():
                f.write(f"{k}={v}\n")
        try:
            os.chmod(secrets_path, 0o600)
        except (OSError, NotImplementedError):
            pass

    for k, v in existing.items():
        os.environ.setdefault(k, v)

    # Route the SQLite DB into the same per-user app-data directory rather
    # than wherever the frozen executable happens to be running from.
    os.environ.setdefault(
        "DATABASE_URL", f"sqlite:///{os.path.join(app_data_dir, 'app.db')}"
    )


# Runs at import time, before the `import uvicorn` / app import below —
# order here is deliberate, see the module docstring.
_bootstrap_desktop_secrets()

import uvicorn  # noqa: E402


def main() -> None:
    # Imported here, after secrets are guaranteed to be in os.environ.
    from src.api.main import app

    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))

    # reload=False is required — PyInstaller's frozen executable has no
    # source files on disk for uvicorn's reloader to watch, and enabling
    # it would crash the bundled app on startup.
    uvicorn.run(app, host=host, port=port, log_level="info", reload=False)


if __name__ == "__main__":
    # PyInstaller freezes sys.frozen = True; multiprocessing support isn't
    # needed here since we run uvicorn in single-process mode, but this
    # guard is cheap insurance against duplicate process spawning on
    # Windows if that ever changes.
    if getattr(sys, "frozen", False):
        import multiprocessing
        multiprocessing.freeze_support()
    main()
