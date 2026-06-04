"""
study_tracker.py -- Subject-based study session tracker.
Logs study time per subject. Works with study mode and manual logging.
"""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR   = Path(__file__).parent.resolve()
SESSIONS_PATH = BASE_DIR / "data" / "study_sessions.json"

_current_session: dict | None = None


def _load_sessions() -> list:
    try:
        return json.loads(SESSIONS_PATH.read_text(encoding="utf-8")).get("sessions", [])
    except Exception:
        return []


def _save_sessions(sessions: list) -> None:
    SESSIONS_PATH.write_text(
        json.dumps({"sessions": sessions}, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_session(subject: str) -> str:
    global _current_session
    _current_session = {
        "date":     date.today().isoformat(),
        "subject":  subject.strip().title(),
        "start":    datetime.now().isoformat(),
        "end":      None,
        "duration_minutes": 0,
        "source":   "study_mode",
        "notes_created": 0,
    }
    logger.info("Study session started: %s", subject)
    return f"Studying {subject.title()}. I'll track your time."


def end_session() -> str:
    global _current_session
    if not _current_session:
        return ""
    end    = datetime.now()
    start  = datetime.fromisoformat(_current_session["start"])
    mins   = int((end - start).total_seconds() / 60)
    _current_session["end"]              = end.isoformat()
    _current_session["duration_minutes"] = mins

    sessions = _load_sessions()
    sessions.append(_current_session)
    _save_sessions(sessions)
    subject = _current_session["subject"]
    _current_session = None
    logger.info("Study session ended: %s (%d min)", subject, mins)
    return f"Study session saved: {mins} minutes of {subject}."


def log_session_manual(subject: str, duration_minutes: int) -> str:
    """Log a study session manually by voice."""
    sessions = _load_sessions()
    sessions.append({
        "date":             date.today().isoformat(),
        "subject":          subject.strip().title(),
        "start":            None,
        "end":              None,
        "duration_minutes": duration_minutes,
        "source":           "manual",
        "notes_created":    0,
    })
    _save_sessions(sessions)
    return f"Logged {duration_minutes} minutes of {subject.title()}."


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _period_start(period: str) -> str:
    today = date.today()
    if period == "today":   return today.isoformat()
    if period == "week":    return (today - timedelta(days=today.weekday())).isoformat()
    if period == "month":   return today.replace(day=1).isoformat()
    return (today - timedelta(days=7)).isoformat()


def subject_stats(subject: str | None = None, period: str = "week") -> str:
    sessions = _load_sessions()
    cutoff   = _period_start(period)
    filtered = [s for s in sessions if s.get("date", "") >= cutoff]

    if subject:
        filtered = [s for s in filtered
                    if subject.lower() in s.get("subject", "").lower()]

    if not filtered:
        return (f"No study sessions for {subject or 'any subject'} "
                f"in the last {period}.")

    total_mins = sum(s.get("duration_minutes", 0) for s in filtered)
    hours = total_mins // 60
    mins  = total_mins % 60

    if subject:
        return (f"You studied {subject.title()} for "
                f"{hours}h {mins}min this {period}.")

    # Break down by subject
    by_subject: dict[str, int] = {}
    for s in filtered:
        subj = s.get("subject", "Other")
        by_subject[subj] = by_subject.get(subj, 0) + s.get("duration_minutes", 0)

    top = sorted(by_subject.items(), key=lambda x: x[1], reverse=True)
    lines = [f"Study time this {period} ({hours}h {mins}min total):"]
    for subj, mins_val in top[:5]:
        h = mins_val // 60
        m = mins_val % 60
        lines.append(f"  {subj}: {h}h {m}min")
    return "\n".join(lines)


def gaps_analysis() -> str:
    """Which subject hasn't been studied recently?"""
    sessions  = _load_sessions()
    week_ago  = (date.today() - timedelta(days=7)).isoformat()
    recent    = [s for s in sessions if s.get("date", "") >= week_ago]

    studied   = {s.get("subject", "").lower() for s in recent}

    # Check against memory.json projects
    try:
        import json as _json
        mem = _json.loads((BASE_DIR / "data" / "memory.json").read_text())
        projects = mem.get("projects", [])
        project_names = [
            (p if isinstance(p, str) else p.get("name", "")).lower()
            for p in projects
        ]
        missing = [p for p in project_names if p and p not in studied]
        if missing:
            return (f"You haven't studied "
                    f"{', '.join(t.title() for t in missing)} this week.")
    except Exception:
        pass

    if not studied:
        return "No study sessions logged this week."

    return f"This week you studied: {', '.join(s.title() for s in studied)}."


def get_current_subject() -> str | None:
    return _current_session["subject"] if _current_session else None
