"""
proactive_engine.py — Jarvis initiates conversation based on patterns.

Runs every 30 minutes via scheduler.
Only fires when Jarvis hasn't spoken in 15+ minutes.
Respects sleep and meeting mode.
One suggestion at a time — never nags.
"""

import json
import logging
import threading
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()

_last_suggestion_time: datetime = datetime.min
_MIN_SILENCE_MINUTES   = 15    # don't suggest if Jarvis spoke recently
_SUGGESTION_COOLDOWN   = 25    # min minutes between suggestions

_speak_fn  = None
_llm_fn    = None

_last_jarvis_speak: datetime = datetime.min


def set_speak(fn) -> None:
    global _speak_fn
    _speak_fn = fn


def set_llm(fn) -> None:
    global _llm_fn
    _llm_fn = fn


def record_jarvis_spoke() -> None:
    global _last_jarvis_speak
    _last_jarvis_speak = datetime.now()


def _cfg() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


def _data(rel_path: str):
    try:
        return json.loads((BASE_DIR / rel_path).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_suppressed() -> bool:
    """Don't suggest if sleeping, in meeting, or recently spoken."""
    try:
        import jarvis as _j
        if _j.is_sleeping():
            return True
    except Exception:
        pass
    try:
        from meeting_mode import is_in_meeting
        if is_in_meeting():
            return True
    except Exception:
        pass
    silence = (datetime.now() - _last_jarvis_speak).total_seconds() / 60
    return silence < _MIN_SILENCE_MINUTES


# ---------------------------------------------------------------------------
# Suggestion generators — each returns (text, priority) or None
# ---------------------------------------------------------------------------

def _suggest_upcoming_deadline() -> tuple[str, int] | None:
    """Warn about tasks due within 2 hours."""
    try:
        cfg   = _cfg()
        tasks = json.loads((BASE_DIR / cfg["paths"]["tasks"]).read_text())
        now   = datetime.now()
        for task in tasks:
            if task.get("done"):
                continue
            dl = task.get("deadline")
            if not dl:
                continue
            try:
                dt   = datetime.fromisoformat(dl)
                hrs  = (dt - now).total_seconds() / 3600
                if 0 < hrs <= 2:
                    mins = int(hrs * 60)
                    return (
                        f"Heads up, Samaira — your task '{task['title']}' "
                        f"is due in {mins} minutes.",
                        10,   # high priority
                    )
            except Exception:
                pass
    except Exception:
        pass
    return None


def _suggest_hydration() -> tuple[str, int] | None:
    """Nudge if no water logged in 3+ hours."""
    try:
        cfg = _cfg()
        wb  = json.loads((BASE_DIR / cfg["paths"]["wellbeing"]).read_text())
        today = date.today().isoformat()
        entry = next((e for e in wb if e.get("date") == today), {})
        hydration = float(entry.get("hydration_L", 0) or 0)
        if hydration < 0.5:
            hour = datetime.now().hour
            if 9 <= hour <= 21:   # only during the day
                return ("Don't forget to drink some water, Samaira.", 3)
    except Exception:
        pass
    return None


def _suggest_study_time() -> tuple[str, int] | None:
    """Suggest study mode at typical study hours if no schedule today."""
    try:
        now  = datetime.now()
        hour = now.hour
        dow  = now.strftime("%A").lower()
        if hour not in range(14, 18):   # afternoon study window
            return None
        cfg   = _cfg()
        tasks = json.loads((BASE_DIR / cfg["paths"]["tasks"]).read_text())
        pending = [t for t in tasks if not t.get("done") and t.get("priority") == "high"]
        if not pending:
            return None
        top = pending[0]["title"]
        return (
            f"It's {now.strftime('%H:%M')}. Your top priority is '{top}'. "
            f"Want me to start study mode?",
            5,
        )
    except Exception:
        pass
    return None


def _suggest_exercise() -> tuple[str, int] | None:
    """Nudge if no exercise logged in 3+ days."""
    try:
        cfg  = _cfg()
        wb   = json.loads((BASE_DIR / cfg["paths"]["wellbeing"]).read_text())
        three_days_ago = (date.today() - timedelta(days=3)).isoformat()
        recent_exercise = any(
            e.get("exercise", "").strip()
            for e in wb
            if e.get("date", "") >= three_days_ago
        )
        if not recent_exercise:
            hour = datetime.now().hour
            if 8 <= hour <= 20:
                return (
                    "You haven't logged any exercise in 3 days. "
                    "Even a short walk would be great.",
                    2,
                )
    except Exception:
        pass
    return None


def _suggest_goal_check() -> tuple[str, int] | None:
    """Weekly check-in on goal progress on Mondays."""
    now = datetime.now()
    if now.weekday() != 0 or now.hour != 9:   # Monday 9am only
        return None
    try:
        cfg      = _cfg()
        progress = json.loads((BASE_DIR / cfg["paths"]["progress"]).read_text())
        goals    = progress.get("goals", [])
        if not goals:
            return None
        g    = goals[0]
        snaps = g.get("snapshots", [])
        pct  = snaps[-1]["progress_percent"] if snaps else 0
        return (
            f"Good morning, Samaira. Weekly check-in: "
            f"{g['goal']} is at {pct}%. "
            f"Want to review your goals?",
            4,
        )
    except Exception:
        pass
    return None


def _suggest_upcoming_class() -> tuple[str, int] | None:
    """Warn 15 minutes before a class starts."""
    try:
        sched = json.loads((BASE_DIR / "data/schedule.json").read_text())
        now   = datetime.now()
        today = now.strftime("%A").lower()
        for cls in sched.get("classes", []):
            if today not in [d.lower() for d in cls.get("days", [])]:
                continue
            cls_time = datetime.strptime(cls["time"], "%H:%M").replace(
                year=now.year, month=now.month, day=now.day
            )
            diff_min = (cls_time - now).total_seconds() / 60
            if 13 <= diff_min <= 17:   # ~15 min window
                return (
                    f"{cls['name']} starts in 15 minutes, Samaira. "
                    f"Room {cls.get('room', 'check your schedule')}.",
                    8,
                )
    except Exception:
        pass
    return None


def _suggest_unread_followups() -> tuple[str, int] | None:
    """Morning reminder about open follow-ups."""
    try:
        now  = datetime.now()
        if now.hour != 9 or now.minute > 30:   # only ~9am
            return None
        cfg  = _cfg()
        fups = json.loads((BASE_DIR / cfg["paths"]["followups"]).read_text())
        open_fups = [f for f in fups if not f.get("done")]
        if len(open_fups) >= 2:
            return (
                f"Good morning. You have {len(open_fups)} open follow-ups "
                f"from previous conversations.",
                3,
            )
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_GENERATORS = [
    _suggest_upcoming_deadline,   # highest priority first
    _suggest_upcoming_class,
    _suggest_study_time,
    _suggest_goal_check,
    _suggest_unread_followups,
    _suggest_exercise,
    _suggest_hydration,
]


def run_proactive_check() -> None:
    """
    Called by the scheduler every 30 minutes.
    Picks the highest-priority applicable suggestion and speaks it once.
    """
    global _last_suggestion_time

    if _is_suppressed():
        return

    # Enforce cooldown between suggestions
    minutes_since = (datetime.now() - _last_suggestion_time).total_seconds() / 60
    if minutes_since < _SUGGESTION_COOLDOWN:
        return

    # Collect all applicable suggestions and pick the one with highest priority
    candidates = []
    for gen in _GENERATORS:
        try:
            result = gen()
            if result:
                candidates.append(result)
        except Exception as e:
            logger.debug("Proactive generator error: %s", e)

    if not candidates:
        return

    # Sort by priority (higher = more urgent)
    candidates.sort(key=lambda x: x[1], reverse=True)
    text, priority = candidates[0]

    logger.info("Proactive suggestion (priority %d): %s", priority, text[:60])
    _last_suggestion_time = datetime.now()

    if _speak_fn:
        _speak_fn(text)
