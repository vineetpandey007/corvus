"""
Loads settings from config/config.yaml, with .env overrides for secrets.
"""

import os
import sys
from pathlib import Path
from functools import lru_cache

import yaml
from dotenv import load_dotenv

load_dotenv()

if getattr(sys, "frozen", False):
    # Running as a PyInstaller-frozen executable: __file__-relative paths
    # no longer point at real files on disk (the package lives inside the
    # bundle), so resolve against sys._MEIPASS instead — the extraction
    # directory PyInstaller sets at runtime, into which backend.spec
    # explicitly bundles config/config.yaml (see its `datas` list).
    PROJECT_ROOT = Path(sys._MEIPASS)
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = PROJECT_ROOT / "config" / "config.yaml"


@lru_cache()
def load_config() -> dict:
    """Load and cache the YAML config file."""
    with open(CONFIG_PATH, "r") as f:
        cfg = yaml.safe_load(f)
    return cfg


def get_app_data_dir() -> Path:
    """
    Directory where persistent runtime data (SQLite DB, audit log, caches)
    should live.

    When running as a packaged desktop app, the Electron shell sets
    APP_DATA_DIR to a proper per-OS user-data directory before spawning
    the backend — this matters because (a) a PyInstaller-frozen build's
    own directory may not be writable once installed, and (b) its working
    directory can be a temporary extraction folder that's wiped after the
    process exits, which would silently lose the audit trail and database
    on every restart if paths were computed relative to it.

    Falls back to <repo>/data/processed for normal server/dev use, and
    also doubles as a convenient override for container deployments that
    mount a data volume at a non-default path.
    """
    env_dir = os.environ.get("APP_DATA_DIR")
    path = Path(env_dir) if env_dir else (PROJECT_ROOT / "data" / "processed")
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_env(key: str, default: str | None = None) -> str | None:
    """Convenience wrapper around os.environ for secrets/overrides."""
    return os.environ.get(key, default)


if __name__ == "__main__":
    import json
    print(json.dumps(load_config(), indent=2))
