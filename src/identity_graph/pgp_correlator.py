"""
PGP Correlator — pure-Python OpenPGP public-key metadata parser (RFC 4880 v4 & RFC 9580 v6).

Zero external `gpg` binary dependency, zero temp files, thread-safe.
Extracts primary key fingerprints, subkey fingerprints, creation timestamps,
and User IDs (UIDs) from publicly posted ASCII-armored PGP public key blocks.
"""

import base64
import hashlib
import re
from typing import Any, Dict, List, Optional

from src.blockchain.wallet_tracer import extract_wallet_addresses  # backward-compatible re-export

PGP_BLOCK_RE = re.compile(
    r"-----BEGIN PGP PUBLIC KEY BLOCK-----.*?-----END PGP PUBLIC KEY BLOCK-----",
    re.DOTALL,
)


def extract_pgp_block(text: str) -> Optional[str]:
    """Extract the first PGP public key block from raw text, if present."""
    match = PGP_BLOCK_RE.search(text)
    return match.group(0) if match else None


def extract_all_pgp_blocks(text: str) -> List[str]:
    """Extract all PGP public key blocks from raw text."""
    return PGP_BLOCK_RE.findall(text)


def _decode_armor(pgp_block: str) -> Optional[bytes]:
    """Strip ASCII armor headers and CRC24 checksum, returning raw packet bytes."""
    lines = [line.strip() for line in pgp_block.strip().splitlines()]
    if not lines or "BEGIN PGP PUBLIC KEY BLOCK" not in lines[0]:
        return None

    # Skip header lines up to the first blank line (or first non-header base64 line)
    idx = 1
    while idx < len(lines):
        line = lines[idx]
        if line == "":
            idx += 1
            break
        if ":" not in line:
            # Handle malformed pastes missing the blank separator line
            break
        idx += 1

    b64_lines: List[str] = []
    for line in lines[idx:]:
        if line.startswith("-----END PGP"):
            break
        if line.startswith("="):  # CRC24 checksum line
            continue
        if line:
            b64_lines.append(line)

    if not b64_lines:
        return None

    try:
        return base64.b64decode("".join(b64_lines), validate=False)
    except Exception:
        return None


def _compute_key_fingerprint(body: bytes) -> Optional[Dict[str, Any]]:
    """Compute RFC 4880 v4 (SHA-1) or RFC 9580 v6 (SHA-256) key fingerprint."""
    if len(body) < 6:
        return None
    version = body[0]
    created_ts = int.from_bytes(body[1:5], "big")
    algorithm_id = body[5]

    if version == 4:
        digest_input = b"\x99" + len(body).to_bytes(2, "big") + body
        fp = hashlib.sha1(digest_input).hexdigest().upper()
    elif version == 6:
        digest_input = b"\x9b" + len(body).to_bytes(4, "big") + body
        fp = hashlib.sha256(digest_input).hexdigest().upper()
    else:
        return None

    return {
        "fingerprint": fp,
        "version": version,
        "created_timestamp": created_ts,
        "algorithm_id": algorithm_id,
    }


def parse_pgp_public_key(pgp_block: str) -> Optional[Dict[str, Any]]:
    """
    Parse an ASCII-armored PGP public key block into primary fingerprint,
    subkey fingerprints, and User IDs without invoking system `gpg`.
    """
    data = _decode_armor(pgp_block)
    if not data:
        return None

    pos = 0
    total = len(data)
    primary_key: Optional[Dict[str, Any]] = None
    subkeys: List[Dict[str, Any]] = []
    user_ids: List[str] = []

    while pos < total:
        ptag = data[pos]
        if (ptag & 0x80) == 0:
            break  # Invalid packet header
        pos += 1

        if ptag & 0x40:
            # New packet format (RFC 4880 §4.2.2)
            tag = ptag & 0x3F
            if pos >= total:
                break
            l1 = data[pos]
            pos += 1
            if l1 < 192:
                body_len = l1
            elif l1 <= 223:
                if pos >= total:
                    break
                body_len = ((l1 - 192) << 8) + data[pos] + 192
                pos += 1
            elif l1 == 255:
                if pos + 4 > total:
                    break
                body_len = int.from_bytes(data[pos:pos + 4], "big")
                pos += 4
            else:
                break  # Partial body lengths are not used for key packets
        else:
            # Old packet format (RFC 4880 §4.2.1)
            tag = (ptag >> 2) & 0x0F
            len_type = ptag & 0x03
            if len_type == 0:
                if pos >= total:
                    break
                body_len = data[pos]
                pos += 1
            elif len_type == 1:
                if pos + 2 > total:
                    break
                body_len = int.from_bytes(data[pos:pos + 2], "big")
                pos += 2
            elif len_type == 2:
                if pos + 4 > total:
                    break
                body_len = int.from_bytes(data[pos:pos + 4], "big")
                pos += 4
            else:
                body_len = total - pos

        if pos + body_len > total:
            break
        body = data[pos:pos + body_len]
        pos += body_len

        if tag == 6 and primary_key is None:  # Public-Key Packet
            primary_key = _compute_key_fingerprint(body)
        elif tag == 14:  # Public-Subkey Packet
            sub = _compute_key_fingerprint(body)
            if sub:
                subkeys.append(sub)
        elif tag == 13:  # User ID Packet
            uid = body.decode("utf-8", errors="replace").strip()
            if uid:
                user_ids.append(uid)

    if not primary_key:
        return None

    return {
        "fingerprint": primary_key["fingerprint"],
        "version": primary_key["version"],
        "created_timestamp": primary_key["created_timestamp"],
        "subkey_fingerprints": [s["fingerprint"] for s in subkeys],
        "user_ids": user_ids,
    }


def get_fingerprint(pgp_block: str, gpg_home: Optional[str] = None) -> Optional[str]:
    """Return the primary PGP key fingerprint (gpg_home retained for API compatibility)."""
    parsed = parse_pgp_public_key(pgp_block)
    return parsed["fingerprint"] if parsed else None


def correlate(text_a: str, text_b: str) -> Dict[str, Any]:
    """
    Check whether text_a and text_b share a PGP primary/subkey fingerprint or UID.
    """
    blocks_a = extract_all_pgp_blocks(text_a)
    blocks_b = extract_all_pgp_blocks(text_b)

    if not blocks_a or not blocks_b:
        return {"match": False, "fingerprint": None, "confidence": 0.0}

    parsed_a = [p for p in (parse_pgp_public_key(b) for b in blocks_a) if p]
    parsed_b = [p for p in (parse_pgp_public_key(b) for b in blocks_b) if p]

    fps_a = {
        fp for p in parsed_a for fp in ([p["fingerprint"]] + p["subkey_fingerprints"])
    }
    fps_b = {
        fp for p in parsed_b for fp in ([p["fingerprint"]] + p["subkey_fingerprints"])
    }

    shared_fps = sorted(fps_a & fps_b)
    if shared_fps:
        return {
            "match": True,
            "fingerprint": shared_fps[0],
            "shared_fingerprints": shared_fps,
            "match_reason": "exact_pgp_key_reuse",
            "confidence": 0.98,
        }

    # Secondary forensic signal: shared User ID email/identity across distinct keys
    uids_a = {u.lower() for p in parsed_a for u in p["user_ids"]}
    uids_b = {u.lower() for p in parsed_b for u in p["user_ids"]}
    shared_uids = sorted(uids_a & uids_b)
    if shared_uids:
        return {
            "match": True,
            "fingerprint": None,
            "shared_user_ids": shared_uids,
            "match_reason": "shared_pgp_user_id",
            "confidence": 0.80,
        }

    return {"match": False, "fingerprint": None, "confidence": 0.0}