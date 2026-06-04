"""
notification_tool.py — Push notifications to your phone via ntfy.sh.
Free, no account needed for public topics.
Private topics (your own ntfy server or ntfy.sh with token) also supported.

Setup:
  1. Install ntfy app on your phone (Android/iOS — free)
  2. Subscribe to your topic e.g. "jarvis-samaira-abc123"
  3. Add to config.yaml:
       ntfy:
         topic: "jarvis-samaira-abc123"   # unique name
         server: "https://ntfy.sh"        # or your own server
         token:  ""                        # optional: ntfy.sh account token
"""

import logging
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _ntfy_cfg() -> dict:
    return _load_cfg().get("ntfy", {})


def send_notification(message: str, title: str = "Jarvis",
                      priority: str = "default", tags: list | None = None) -> str:
    """
    Send a push notification to your phone via ntfy.sh.

    priority: min / low / default / high / urgent
    tags: emoji shortcodes e.g. ["alarm_clock", "white_check_mark"]
    """
    cfg    = _ntfy_cfg()
    topic  = cfg.get("topic", "").strip()
    server = cfg.get("server", "https://ntfy.sh").rstrip("/")
    token  = cfg.get("token", "").strip()

    if not topic:
        return (
            "ntfy not configured. Add ntfy.topic to config.yaml and "
            "subscribe to that topic in the ntfy app on your phone."
        )

    headers = {
        "Title":    title,
        "Priority": priority,
    }
    if tags:
        headers["Tags"] = ",".join(tags)
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        resp = requests.post(
            f"{server}/{topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=6,
        )
        resp.raise_for_status()
        logger.info("ntfy notification sent: %s", title)
        return f"Notification sent to your phone: {title}."
    except Exception as e:
        logger.error("ntfy failed: %s", e)
        return f"Couldn't send notification: {e}"


def ntfy_status() -> str:
    cfg = _ntfy_cfg()
    if not cfg.get("topic"):
        return (
            "ntfy is not configured. Add ntfy.topic to config.yaml and "
            "install the ntfy app on your phone."
        )
    server = cfg.get("server", "https://ntfy.sh")
    topic  = cfg.get("topic")
    return f"ntfy is configured. Topic: {topic} on {server}."


def send_reminder_notification(message: str) -> None:
    """Called by scheduler when a reminder fires — silent fail if ntfy not set up."""
    try:
        send_notification(message, title="Jarvis Reminder",
                          priority="high", tags=["bell"])
    except Exception:
        pass
