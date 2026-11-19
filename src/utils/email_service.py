"""
Pluggable email sending abstraction.

Dev mode (default, EMAIL_BACKEND unset or "dev"): doesn't send anything
over the network — logs the email and appends it to a local JSONL outbox
file, so password-reset links and OTP codes are easy to find and use
during local development/testing without needing a real mail server.

Production (EMAIL_BACKEND=smtp): sends via a real SMTP server. Set
SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM in .env.
send_email()'s signature is identical either way, so nothing calling it
needs to change when you switch backends — see docs/SETUP.md.
"""

import json
import os
from datetime import datetime, timezone

from src.utils.config import get_app_data_dir
from src.utils.logger import get_logger

logger = get_logger()


def send_email(to: str, subject: str, body: str) -> None:
    backend = os.environ.get("EMAIL_BACKEND", "dev").lower()
    if backend == "smtp":
        _send_via_smtp(to, subject, body)
    else:
        _send_dev(to, subject, body)


def _send_dev(to: str, subject: str, body: str) -> None:
    logger.info(f"[DEV EMAIL] To: {to} | Subject: {subject}\n{body}\n{'-' * 60}")

    outbox_path = get_app_data_dir() / "dev_email_outbox.jsonl"
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "to": to,
        "subject": subject,
        "body": body,
    }
    with open(outbox_path, "a") as f:
        f.write(json.dumps(record) + "\n")


def _send_via_smtp(to: str, subject: str, body: str) -> None:
    import smtplib
    from email.mime.text import MIMEText

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")
    from_addr = os.environ.get("SMTP_FROM", username)

    if not all([host, username, password]):
        raise RuntimeError(
            "EMAIL_BACKEND=smtp requires SMTP_HOST, SMTP_USERNAME, and "
            "SMTP_PASSWORD to be set in .env."
        )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to

    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(username, password)
        server.sendmail(from_addr, [to], msg.as_string())

    logger.info(f"Sent email via SMTP to {to}: {subject}")
