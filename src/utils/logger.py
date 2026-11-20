"""
Application logging + tamper-evident, hash-chained chain-of-custody audit log.

- `get_logger()`         -> structured application logs (stderr)
- `audit_log()`          -> thread-safe, SHA-256 hash-chained investigative
                            audit trail (persisted to JSONL + relational AuditLog)
- `verify_audit_chain()` -> cryptographic verification of the JSONL audit chain
"""

import hashlib
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

from src.utils.config import get_app_data_dir, load_config

logger.remove()
logger.add(sys.stderr, level=load_config().get("app", {}).get("log_level", "INFO"))

_GENESIS_HASH = "0" * 64
_audit_lock = threading.Lock()


def get_logger():
    return logger


def _compute_entry_hash(prev_hash: str, payload: Dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest_input = f"{prev_hash}:{canonical}".encode("utf-8")
    return hashlib.sha256(digest_input).hexdigest()


def _read_last_hash(log_path: Path) -> str:
    if not log_path.exists() or log_path.stat().st_size == 0:
        return _GENESIS_HASH
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            last_line = ""
            for line in f:
                stripped = line.strip()
                if stripped:
                    last_line = stripped
        if not last_line:
            return _GENESIS_HASH
        parsed = json.loads(last_line)
        return parsed.get("entry_hash", _GENESIS_HASH)
    except Exception:
        return _GENESIS_HASH


def _mirror_audit_to_db(
    ts: datetime,
    actor: str,
    action: str,
    case_id: Optional[str],
    details: Dict[str, Any],
    prev_hash: str,
    entry_hash: str,
) -> None:
    """Best-effort persistence to the relational AuditLog table."""
    try:
        from src.db.database import SessionLocal
        from src.db.models import AuditLog

        db = SessionLocal()
        try:
            db.add(
                AuditLog(
                    timestamp=ts,
                    actor=actor,
                    action=action,
                    case_id=case_id,
                    details_json=json.dumps(details, default=str),
                    prev_hash=prev_hash,
                    entry_hash=entry_hash,
                )
            )
            db.commit()
        finally:
            db.close()
    except Exception as exc:
        logger.debug(f"Relational audit mirror skipped: {exc}")


def audit_log(
    action: str,
    actor: str,
    details: Dict[str, Any],
    case_id: Optional[str] = None,
) -> None:
    """
    Append a cryptographically hash-chained chain-of-custody record.
    Each entry binds `prev_hash` + canonical JSON into `entry_hash` (SHA-256).
    """
    cfg = load_config()
    audit_cfg = cfg.get("audit", {})
    if not audit_cfg.get("enabled", True):
        return

    resolved_case_id = case_id or (details.get("case_id") if isinstance(details, dict) else None)
    log_path = get_app_data_dir() / audit_cfg.get("log_path", "audit_log.jsonl")
    log_path.parent.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    base_payload = {
        "timestamp": now.isoformat(),
        "action": action,
        "actor": actor,
        "case_id": resolved_case_id,
        "details": details,
    }

    with _audit_lock:
        prev_hash = _read_last_hash(log_path)
        entry_hash = _compute_entry_hash(prev_hash, base_payload)
        record = {
            **base_payload,
            "prev_hash": prev_hash,
            "entry_hash": entry_hash,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")

    _mirror_audit_to_db(
        ts=now,
        actor=actor,
        action=action,
        case_id=resolved_case_id,
        details=details,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
    )
    logger.debug(f"[audit] {action} by {actor}: {details}")


def verify_audit_chain(log_path: Optional[Path] = None) -> Dict[str, Any]:
    """
    Verify the cryptographic integrity of the JSONL audit log chain.
    Returns {"valid": bool, "entries": int, "broken_at_line": int | None}.
    """
    if log_path is None:
        cfg = load_config()
        audit_cfg = cfg.get("audit", {})
        log_path = get_app_data_dir() / audit_cfg.get("log_path", "audit_log.jsonl")

    if not log_path.exists():
        return {"valid": True, "entries": 0, "broken_at_line": None}

    expected_prev = _GENESIS_HASH
    count = 0
    with open(log_path, "r", encoding="utf-8") as f:
        for line_num, raw in enumerate(f, start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            count += 1
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                return {"valid": False, "entries": count, "broken_at_line": line_num}

            if entry.get("prev_hash") != expected_prev:
                return {"valid": False, "entries": count, "broken_at_line": line_num}

            payload = {
                "timestamp": entry.get("timestamp"),
                "action": entry.get("action"),
                "actor": entry.get("actor"),
                "case_id": entry.get("case_id"),
                "details": entry.get("details"),
            }
            recomputed = _compute_entry_hash(expected_prev, payload)
            if entry.get("entry_hash") != recomputed:
                return {"valid": False, "entries": count, "broken_at_line": line_num}

            expected_prev = recomputed

    return {"valid": True, "entries": count, "broken_at_line": None}