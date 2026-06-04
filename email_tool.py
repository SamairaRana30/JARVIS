"""
email_tool.py — Read Gmail via IMAP.
Reuses the App Password already set up for Google Calendar.

No extra setup needed — just uses google_calendar.email and app_password
from config.yaml.
"""

import email as _email_lib
import email.header
import imaplib
import logging
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _imap_connect():
    cfg = _load_cfg()
    cal = cfg.get("google_calendar", {})
    email_addr = cal.get("email", "").strip()
    password   = cal.get("app_password", "").replace(" ", "").strip()

    if not email_addr or not password:
        raise RuntimeError(
            "Gmail not configured. Add email and app_password under "
            "google_calendar in config.yaml."
        )

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(email_addr, password)
    return mail


def _decode_header(value: str) -> str:
    parts = _email_lib.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(str(part))
    return " ".join(decoded)


def _get_text(msg) -> str:
    """Extract plain-text body from an email.Message."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode(part.get_content_charset() or "utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode(msg.get_content_charset() or "utf-8", errors="replace")
    return ""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------

def get_unread_emails(max_results: int = 5) -> str:
    """Return a spoken summary of unread Gmail messages."""
    try:
        mail = _imap_connect()
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        ids = data[0].split()
        if not ids:
            mail.logout()
            return "Your inbox is clear — no unread emails."

        total = len(ids)
        recent_ids = ids[-max_results:]   # newest first (IMAP returns oldest→newest)
        lines = [f"You have {total} unread email{'s' if total != 1 else ''}."]

        for uid in reversed(recent_ids):
            _, msg_data = mail.fetch(uid, "(RFC822)")
            raw = msg_data[0][1]
            msg = _email_lib.message_from_bytes(raw)
            subject = _decode_header(msg.get("Subject", "(no subject)"))
            sender  = _decode_header(msg.get("From", "unknown"))
            # Strip email address, keep display name
            if "<" in sender:
                sender = sender.split("<")[0].strip().strip('"')
            lines.append(f"• From {sender}: {subject}.")

        mail.logout()
        return "\n".join(lines)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.error("Email fetch error: %s", e)
        return f"Couldn't read email: {e}"


def get_email_count() -> str:
    """Return just the unread count."""
    try:
        mail = _imap_connect()
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        count = len(data[0].split()) if data[0] else 0
        mail.logout()
        return f"You have {count} unread email{'s' if count != 1 else ''}."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't check email: {e}"


def read_latest_email(llm_caller=None) -> str:
    """Read and optionally summarise the latest unread email."""
    try:
        mail = _imap_connect()
        mail.select("INBOX")
        _, data = mail.search(None, "UNSEEN")
        ids = data[0].split()
        if not ids:
            mail.logout()
            return "No unread emails."

        uid = ids[-1]
        _, msg_data = mail.fetch(uid, "(RFC822)")
        raw = msg_data[0][1]
        msg = _email_lib.message_from_bytes(raw)
        subject = _decode_header(msg.get("Subject", "(no subject)"))
        sender  = _decode_header(msg.get("From", "unknown"))
        if "<" in sender:
            sender = sender.split("<")[0].strip().strip('"')
        body = _get_text(msg).strip()[:1000]
        mail.logout()

        header = f"Email from {sender}. Subject: {subject}."
        if llm_caller and body:
            summary = llm_caller(
                f"Summarise this email in 2 sentences:\n\nSubject: {subject}\n\n{body}"
            )
            return f"{header} {summary}"
        return f"{header} {body[:300]}" if body else header
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't read email: {e}"


def email_status() -> str:
    try:
        mail = _imap_connect()
        mail.logout()
        return "Gmail is connected."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Gmail connection failed: {e}"
