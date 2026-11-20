"""
Field-level encryption at rest with MultiFernet key rotation and SHA-256
evidence hashing for forensic chain-of-custody.

Supports zero-downtime key rotation: set ENCRYPTION_KEY to a comma-separated
list of Fernet keys (newest first), e.g.:
    ENCRYPTION_KEY=<new_key>,<old_key>
New data is encrypted with <new_key>, while existing records encrypted with
<old_key> continue to decrypt cleanly.
"""

import hashlib
import os
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

_ENV_VAR = "ENCRYPTION_KEY"


def generate_key() -> str:
    """Generate a new Fernet key (run once, store the output in .env)."""
    return Fernet.generate_key().decode()


@lru_cache(maxsize=4)
def _build_cipher(raw_keys: str) -> MultiFernet:
    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if not keys:
        raise RuntimeError(f"{_ENV_VAR} is empty.")
    try:
        fernets = [Fernet(k.encode()) for k in keys]
    except Exception as exc:
        raise RuntimeError(
            f"{_ENV_VAR} contains an invalid Fernet key. Generate a valid key with "
            f"`python -c \"from src.utils.encryption import generate_key; print(generate_key())\"`."
        ) from exc
    return MultiFernet(fernets)


def _get_cipher() -> MultiFernet:
    raw = os.environ.get(_ENV_VAR, "").strip()
    if not raw:
        raise RuntimeError(
            f"{_ENV_VAR} is not set in the environment. Generate one with "
            f"`python -c \"from src.utils.encryption import generate_key; "
            f"print(generate_key())\"` and add it to your .env file."
        )
    return _build_cipher(raw)


def validate_encryption_config() -> None:
    """Fail-fast startup check to verify ENCRYPTION_KEY is present and valid."""
    _get_cipher()


def encrypt_text(plaintext: str) -> str:
    """Encrypt a UTF-8 string, returning a base64 token safe to store as text."""
    cipher = _get_cipher()
    return cipher.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_text(token: str) -> str:
    """Decrypt a token produced by encrypt_text(). Raises ValueError on tampering/bad key."""
    cipher = _get_cipher()
    try:
        return cipher.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError(
            "Failed to decrypt — wrong ENCRYPTION_KEY or the data was tampered with."
        ) from e


def rotate_token(token: str) -> str:
    """Re-encrypt an existing ciphertext token under the primary (newest) key."""
    cipher = _get_cipher()
    try:
        return cipher.rotate(token.encode("ascii")).decode("ascii")
    except InvalidToken as e:
        raise ValueError("Cannot rotate token — invalid key or tampered ciphertext.") from e


def hash_evidence(plaintext: str) -> str:
    """Compute a deterministic SHA-256 hex digest of raw evidence text."""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


if __name__ == "__main__":
    print("New ENCRYPTION_KEY (add this to your .env):")
    print(generate_key())