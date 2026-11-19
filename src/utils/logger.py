"""
Application logging + chain-of-custody audit logging.

Two separate concerns, intentionally kept apart:
- `get_logger()` -> normal application/debug logs (console).
- `audit_log()`  -> append-only, timestamped record of every investigative
  action (ingestion, correlation run, export) for chain-of-custody purposes.
  See docs/ETHICS_AND_LEGAL.md.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from src.utils.config import load_config, get_app_data_dir

logger.remove()
logger.add(sys.stderr, level=load_config().get("app", {}).get("log_level", "INFO"))


def get_logger():
    return logger


def audit_log(action: str, actor: str, details: dict) -> None:
    """
    Append a chain-of-custody record. Every ingestion / correlation /
    export action performed by the toolkit should call this.

    Args:
        action: short action name, e.g. "ingest", "stylometry_match",
            "wallet_trace", "export_graph".
        actor: identifier of the analyst/system performing the action.
        details: arbitrary JSON-serializable metadata about the action.
    """
    cfg = load_config()
    audit_cfg = cfg.get("audit", {})
    if not audit_cfg.get("enabled", True):
        return

    log_path = get_app_data_dir() / audit_cfg.get("log_path", "audit_log.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "actor": actor,
        "details": details,
    }

    with open(log_path, "a") as f:
        f.write(json.dumps(record) + "\n")

    logger.debug(f"[audit] {action} by {actor}: {details}")
