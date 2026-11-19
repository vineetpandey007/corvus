"""
Field-level encryption at rest for sensitive case data (post text, aliases
in exports, etc.), using Fernet (AES-128-CBC + HMAC, via `cryptography`).

This protects data stored in the application DB/files. It is a
*complement* to, not a replacement for, full-disk encryption (LUKS/BitLocker)
and a properly access-controlled production database — see
docs/ETHICS_AND_LEGAL.md and docs/DEPLOYMENT.md.

Generate a key once and store it in .env as ENCRYPTION_KEY — never commit
it, and back it up somewhere separate from the database (losing the key
means losing access to all encrypted data).
"""

import os

from cryptography.fernet import Fernet, InvalidToken

_ENV_VAR = "ENCRYPTION_KEY"


def generate_key() -> str:
    """Generate a new Fernet key (run once, store the output in .env)."""
    return Fernet.generate_key().decode()


def _get_fernet() -> Fernet:
    key = os.environ.get(_ENV_VAR)
    if not key:
        raise RuntimeError(
            f"{_ENV_VAR} is not set in the environment. Generate one with "
            f"`python -c \"from src.utils.encryption import generate_key; "
            f"print(generate_key())\"` and add it to your .env file."
        )
    return Fernet(key.encode())


def encrypt_text(plaintext: str) -> str:
    """Encrypt a string, returning a base64 token safe to store as text."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_text(token: str) -> str:
    """Decrypt a token produced by encrypt_text(). Raises on tampering/bad key."""
    f = _get_fernet()
    try:
        return f.decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise ValueError(
            "Failed to decrypt — wrong ENCRYPTION_KEY or the data was tampered with."
        ) from e


if __name__ == "__main__":
    print("New ENCRYPTION_KEY (add this to your .env):")
    print(generate_key())
