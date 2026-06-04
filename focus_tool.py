"""
focus_tool.py — Track foreground app time via psutil + win32.
Logs which app is in focus every 30s, reports daily summary.
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

_focus_log: dict[str, float] = defaultdict(float)  # {app_name: seconds}
_focus_date: str = date.today().isoformat()
_focus_thread: threading.Thread | None = None
_focus_stop = threading.Event()
_focus_lock = threading.Lock()
_POLL_INTERVAL = 30   # seconds


def _get_foreground_app() -> str:
    """Return the name of the currently focused process (Windows)."""
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        pid  = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = psutil.Process(pid.value)
        return proc.name().replace(".exe", "")
    except Exception:
        return "unknown"


_last_mouse_pos: tuple = (0, 0)
_last_activity:  datetime = datetime.now()
_IDLE_THRESHOLD_MINUTES = 5


def _is_idle() -> bool:
    """Return True if mouse hasn't moved for _IDLE_THRESHOLD_MINUTES minutes."""
    global _last_mouse_pos, _last_activity
    try:
        import pyautogui  # type: ignore
        pos = pyautogui.position()
        current = (pos.x, pos.y)
        if current != _last_mouse_pos:
            _last_mouse_pos = current
            _last_activity  = datetime.now()
        idle_min = (datetime.now() - _last_activity).total_seconds() / 60
        return idle_min >= _IDLE_THRESHOLD_MINUTES
    except Exception:
        return False


def _focus_loop() -> None:
    global _focus_date, _focus_log
    logger.info("Focus tracking started.")
    while not _focus_stop.is_set():
        today = date.today().isoformat()
        if today != _focus_date:
            with _focus_lock:
                _focus_log = defaultdict(float)
                _focus_date = today

        if not _is_idle():
            app = _get_foreground_app()
            with _focus_lock:
                _focus_log[app] += _POLL_INTERVAL
        else:
            logger.debug("Focus tracker: idle, skipping.")

        _focus_stop.wait(timeout=_POLL_INTERVAL)


def start_focus_tracking() -> None:
    global _focus_thread
    if _focus_thread and _focus_thread.is_alive():
        return
    _focus_stop.clear()
    _focus_thread = threading.Thread(target=_focus_loop, daemon=True, name="FocusTracker")
    _focus_thread.start()


def stop_focus_tracking() -> None:
    _focus_stop.set()


def get_focus_report() -> str:
    """Return a spoken summary of today's app focus time."""
    with _focus_lock:
        if not _focus_log:
            return "No focus data recorded yet today."
        sorted_apps = sorted(_focus_log.items(), key=lambda x: x[1], reverse=True)

    lines = ["Here's how you've spent your time today."]
    total = sum(s for _, s in sorted_apps)
    for app, secs in sorted_apps[:5]:
        mins = int(secs // 60)
        pct  = int(secs / total * 100) if total else 0
        if mins >= 1:
            lines.append(f"{app}: {mins} minute{'s' if mins != 1 else ''} ({pct}%).")
    return " ".join(lines)


def get_top_app() -> str:
    """Return the app used most today."""
    with _focus_lock:
        if not _focus_log:
            return "No focus data yet."
        top = max(_focus_log, key=_focus_log.get)
        mins = int(_focus_log[top] // 60)
    return f"You've spent the most time in {top} today — {mins} minutes."


# ---------------------------------------------------------------------------
# Subject-based study tracking
# ---------------------------------------------------------------------------

# Map app/window keywords → study subject
_SUBJECT_MAP = {
    "code":           "programming",
    "vscode":         "programming",
    "visual studio":  "programming",
    "pycharm":        "programming",
    "jupyter":        "programming",
    "chrome":         "research",
    "firefox":        "research",
    "edge":           "research",
    "word":           "writing",
    "docs":           "writing",
    "notion":         "notes",
    "obsidian":       "notes",
    "excel":          "data",
    "matlab":         "data",
    "overleaf":       "writing",
    "slack":          "communication",
    "teams":          "communication",
    "zoom":           "meetings",
}


def get_study_breakdown() -> str:
    """Break down today's focus time by subject instead of raw app names."""
    with _focus_lock:
        if not _focus_log:
            return "No focus data recorded today yet."
        subjects: dict[str, float] = {}
        for app, secs in _focus_log.items():
            app_l   = app.lower()
            subject = next((s for kw, s in _SUBJECT_MAP.items() if kw in app_l), "other")
            subjects[subject] = subjects.get(subject, 0) + secs

    total = sum(subjects.values())
    if not total:
        return "No study time recorded today."

    sorted_subjects = sorted(subjects.items(), key=lambda x: x[1], reverse=True)
    lines = [f"Today's focus time ({int(total // 60)} minutes total):"]
    for subject, secs in sorted_subjects:
        mins = int(secs // 60)
        pct  = int(secs / total * 100)
        if mins >= 1:
            lines.append(f"  {subject.title()}: {mins} minutes ({pct}%)")
    return "\n".join(lines)


def get_weekly_study_summary() -> str:
    """Return this week's study time (uses today's log only — persistent log is future work)."""
    total_mins = sum(_focus_log.values()) // 60 if _focus_log else 0
    if not total_mins:
        return "No study time data available."
    return f"Today you've focused for {int(total_mins)} minutes across {len(_focus_log)} apps."
