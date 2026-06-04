"""
whatsapp_tool.py — Read WhatsApp messages from two bridges:
  Personal WhatsApp → http://localhost:5765 (whatsapp_bridge/)
  Uni WhatsApp      → http://localhost:5766 (whatsapp_bridge_uni/)

Voice commands:
  "Any WhatsApp messages?"      → reads both accounts
  "Personal WhatsApp"           → reads personal only
  "Uni WhatsApp"                → reads uni only
  "WhatsApp from [name]"        → filters by contact across both
"""

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)
BASE_DIR   = Path(__file__).parent.resolve()
BRIDGES = {
    "personal": {"url": "http://localhost:5765", "dir": BASE_DIR / "whatsapp_bridge"},
    "uni":      {"url": "http://localhost:5766", "dir": BASE_DIR / "whatsapp_bridge_uni"},
}
BRIDGE_URL = BRIDGES["personal"]["url"]   # default for legacy calls
BRIDGE_DIR = BRIDGES["personal"]["dir"]

_bridge_proc: subprocess.Popen | None = None


def _cfg() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Bridge management
# ---------------------------------------------------------------------------

def start_bridge() -> bool:
    """Launch the Node.js bridge process if not already running."""
    global _bridge_proc
    if is_bridge_running():
        return True

    pkg = BRIDGE_DIR / "package.json"
    if not pkg.exists():
        logger.error("WhatsApp bridge not found at %s", BRIDGE_DIR)
        return False

    node_modules = BRIDGE_DIR / "node_modules"
    if not node_modules.exists():
        logger.info("Installing WhatsApp bridge dependencies...")
        subprocess.run(["npm", "install"], cwd=str(BRIDGE_DIR),
                       capture_output=True, timeout=120)

    _bridge_proc = subprocess.Popen(
        ["node", "server.js"],
        cwd=str(BRIDGE_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Give it 3 seconds to start
    time.sleep(3)
    running = is_bridge_running()
    logger.info("WhatsApp bridge started: %s", running)
    return running


def stop_bridge() -> None:
    global _bridge_proc
    if _bridge_proc:
        _bridge_proc.terminate()
        _bridge_proc = None


def is_bridge_running() -> bool:
    try:
        r = requests.get(f"{BRIDGE_URL}/status", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def is_whatsapp_connected() -> bool:
    try:
        r = requests.get(f"{BRIDGE_URL}/status", timeout=2)
        return r.json().get("connected", False)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Reading messages
# ---------------------------------------------------------------------------

def get_unread_count() -> int:
    try:
        r = requests.get(f"{BRIDGE_URL}/unread_count", timeout=3)
        return r.json().get("count", 0)
    except Exception:
        return 0


def get_unread_messages(n: int = 10) -> list[dict]:
    try:
        r = requests.get(f"{BRIDGE_URL}/messages", params={"n": n, "unread": "true"}, timeout=5)
        return r.json()
    except Exception:
        return []


def get_messages(n: int = 10) -> list[dict]:
    try:
        r = requests.get(f"{BRIDGE_URL}/messages", params={"n": n}, timeout=5)
        return r.json()
    except Exception:
        return []


def mark_all_read() -> None:
    try:
        requests.post(f"{BRIDGE_URL}/mark_read", json={}, timeout=3)
    except Exception:
        pass


def _fmt_message(msg: dict) -> str:
    name    = msg.get("name", "Unknown")
    text    = msg.get("text", "")
    ts      = msg.get("timestamp", 0)
    try:
        from datetime import datetime
        dt  = datetime.fromtimestamp(ts)
        time_str = dt.strftime("%H:%M")
    except Exception:
        time_str = ""
    return f"{name} at {time_str}: {text[:100]}"


# ---------------------------------------------------------------------------
# Voice interface functions
# ---------------------------------------------------------------------------

def read_unread(filter_name: str | None = None) -> str:
    """Read unread WhatsApp messages aloud."""
    if not is_bridge_running():
        if not start_bridge():
            return (
                "The WhatsApp bridge isn't running. "
                "Open a terminal, navigate to whatsapp_bridge/, "
                "run 'npm install' then 'node server.js', "
                "and scan the QR code with your phone."
            )

    if not is_whatsapp_connected():
        return (
            "WhatsApp is not connected. "
            "Check the bridge terminal and scan the QR code."
        )

    msgs = get_unread_messages(n=15)
    if filter_name:
        msgs = [m for m in msgs if filter_name.lower() in m.get("name", "").lower()]

    if not msgs:
        return "No unread WhatsApp messages."

    count = len(msgs)
    mark_all_read()

    if count == 1:
        return f"One WhatsApp message. {_fmt_message(msgs[0])}."

    lines = [f"You have {count} unread WhatsApp messages."]
    for msg in msgs[:5]:
        lines.append(_fmt_message(msg))
    if count > 5:
        lines.append(f"And {count - 5} more.")
    return " ".join(lines)


def whatsapp_status() -> str:
    """Check WhatsApp connection status."""
    if not is_bridge_running():
        return (
            "WhatsApp bridge is not running. "
            "Run 'node server.js' in the whatsapp_bridge folder."
        )
    if not is_whatsapp_connected():
        return "Bridge is running but WhatsApp is not connected. Scan the QR code."
    count = get_unread_count()
    return f"WhatsApp connected. {count} unread message{'s' if count != 1 else ''}."


def check_whatsapp_for_briefing() -> str:
    """Used in morning briefing — brief summary of unread count across both accounts."""
    lines = []
    for account, cfg in BRIDGES.items():
        try:
            r = requests.get(f"{cfg['url']}/unread_count", timeout=2)
            count = r.json().get("count", 0)
            if count:
                lines.append(f"{count} {account}")
        except Exception:
            pass
    if not lines:
        return ""
    return f"Unread WhatsApp: {', '.join(lines)}."


# ---------------------------------------------------------------------------
# Dual-bridge functions
# ---------------------------------------------------------------------------

def _bridge_unread(bridge_url: str, n: int = 10) -> list[dict]:
    try:
        r = requests.get(f"{bridge_url}/messages",
                         params={"n": n, "unread": "true"}, timeout=5)
        return r.json()
    except Exception:
        return []


def _bridge_connected(bridge_url: str) -> bool:
    try:
        r = requests.get(f"{bridge_url}/status", timeout=2)
        return r.json().get("connected", False)
    except Exception:
        return False


def read_all_unread(filter_name: str | None = None) -> str:
    """Read unread messages from both personal and uni accounts."""
    all_msgs = []
    for account, cfg in BRIDGES.items():
        if not _bridge_connected(cfg["url"]):
            continue
        msgs = _bridge_unread(cfg["url"])
        for m in msgs:
            m["_account"] = account
            all_msgs.append(m)
        # Mark as read
        try:
            requests.post(f"{cfg['url']}/mark_read", json={}, timeout=3)
        except Exception:
            pass

    if filter_name:
        all_msgs = [m for m in all_msgs
                    if filter_name.lower() in m.get("name", "").lower()]

    if not all_msgs:
        return "No unread WhatsApp messages on either account."

    all_msgs.sort(key=lambda m: m.get("timestamp", 0), reverse=True)
    count = len(all_msgs)

    if count == 1:
        m = all_msgs[0]
        return f"One message [{m['_account']}]. {_fmt_message(m)}."

    lines = [f"You have {count} unread WhatsApp messages."]
    for m in all_msgs[:6]:
        lines.append(f"[{m['_account'].upper()}] {_fmt_message(m)}")
    if count > 6:
        lines.append(f"And {count - 6} more.")
    return " ".join(lines)


def read_account(account: str = "personal", filter_name: str | None = None) -> str:
    """Read messages from a specific account."""
    cfg = BRIDGES.get(account.lower(), BRIDGES["personal"])
    if not _bridge_connected(cfg["url"]):
        return f"Your {account} WhatsApp is not connected."
    msgs = _bridge_unread(cfg["url"])
    if filter_name:
        msgs = [m for m in msgs if filter_name.lower() in m.get("name","").lower()]
    if not msgs:
        return f"No unread messages on your {account} WhatsApp."
    try:
        requests.post(f"{cfg['url']}/mark_read", json={}, timeout=3)
    except Exception:
        pass
    lines = [f"{len(msgs)} unread on {account} WhatsApp."]
    for m in msgs[:5]:
        lines.append(_fmt_message(m))
    return " ".join(lines)


def dual_status() -> str:
    """Status of both WhatsApp accounts."""
    parts = []
    for account, cfg in BRIDGES.items():
        try:
            r = requests.get(f"{cfg['url']}/status", timeout=2).json()
            if r.get("connected"):
                count = requests.get(f"{cfg['url']}/unread_count", timeout=2).json().get("count", 0)
                parts.append(f"{account.title()}: connected, {count} unread")
            else:
                parts.append(f"{account.title()}: bridge running but not connected")
        except Exception:
            parts.append(f"{account.title()}: bridge not running")
    return ". ".join(parts) + "."
