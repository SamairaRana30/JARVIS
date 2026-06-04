"""
journal_tool.py — Private voice journal for Jarvis.

"Dear Jarvis, today I..." → saves timestamped entry with mood extraction.
Entries stored in notes/journal/ as markdown files.
Weekly summary available: "Read me my journal this week."
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR   = Path(__file__).parent.resolve()
JOURNAL_DIR = BASE_DIR / "notes" / "journal"


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


def _today_file() -> Path:
    JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
    return JOURNAL_DIR / f"{date.today().isoformat()}.md"


def _extract_mood(text: str) -> str:
    """Fast keyword-based mood extraction."""
    text_l = text.lower()
    if any(w in text_l for w in ("stressed", "anxious", "overwhelmed", "worried")):
        return "stressed"
    if any(w in text_l for w in ("tired", "exhausted", "drained", "sleepy")):
        return "tired"
    if any(w in text_l for w in ("sad", "down", "depressed", "low", "awful")):
        return "sad"
    if any(w in text_l for w in ("happy", "great", "amazing", "excited", "proud", "good")):
        return "happy"
    if any(w in text_l for w in ("productive", "focused", "accomplished", "motivated")):
        return "productive"
    if any(w in text_l for w in ("okay", "fine", "alright", "normal")):
        return "neutral"
    return ""


def add_entry(text: str, llm_caller=None) -> str:
    """
    Add a journal entry for today.
    Appends to today's file. Extracts mood automatically.
    """
    now  = datetime.now()
    mood = _extract_mood(text)

    # Optional: richer mood/summary via LLM
    summary = ""
    if llm_caller:
        try:
            summary = llm_caller(
                f"In one sentence, summarise what this journal entry is about "
                f"(focus, emotion, key event):\n{text}"
            ).strip()
        except Exception:
            pass

    file = _today_file()
    if not file.exists():
        # Create file with date header
        file.write_text(
            f"# Journal — {now.strftime('%A, %d %B %Y')}\n\n",
            encoding="utf-8"
        )

    # Append entry
    entry = (
        f"\n## {now.strftime('%H:%M')}"
        + (f" — {mood.upper()}" if mood else "")
        + "\n\n"
        + text.strip()
        + "\n"
        + (f"\n*{summary}*\n" if summary else "")
    )
    with open(file, "a", encoding="utf-8") as f:
        f.write(entry)

    # Log mood to wellbeing if detected
    if mood:
        try:
            cfg     = _load_cfg()
            wb_path = BASE_DIR / cfg["paths"]["wellbeing"]
            wb      = json.loads(wb_path.read_text(encoding="utf-8"))
            today   = date.today().isoformat()
            found   = False
            for e in wb:
                if e.get("date") == today:
                    if not e.get("mood"):
                        e["mood"] = mood
                        e["source"] = "journal"
                    found = True
                    break
            if not found:
                wb.append({"date": today, "mood": mood, "energy": "", "sleep": "",
                            "exercise": "", "hydration_L": 0, "notes": text[:100],
                            "source": "journal"})
            import shutil
            bak = wb_path.with_suffix(".bak")
            if wb_path.exists():
                shutil.copy(wb_path, bak)
            wb_path.write_text(json.dumps(wb, indent=2, ensure_ascii=False),
                                encoding="utf-8")
        except Exception as e:
            logger.warning("Could not log mood from journal: %s", e)

    # Auto-index into RAG
    try:
        from rag_tool import index_file
        index_file(file)
    except Exception:
        pass

    mood_note = f" I noted your mood as {mood}." if mood else ""
    return f"Journal entry saved.{mood_note}"


def read_today() -> str:
    """Read today's journal entries."""
    file = _today_file()
    if not file.exists():
        return "No journal entries today yet."
    text = file.read_text(encoding="utf-8").strip()
    if len(text) < 20:
        return "No journal entries today yet."
    return text[:800]


def read_week(llm_caller=None) -> str:
    """Summarise this week's journal entries."""
    entries = []
    today   = date.today()
    for i in range(7):
        d    = today - timedelta(days=i)
        file = JOURNAL_DIR / f"{d.isoformat()}.md"
        if file.exists():
            text = file.read_text(encoding="utf-8").strip()
            if len(text) > 20:
                entries.append(f"**{d.strftime('%A')}:**\n{text[:400]}")

    if not entries:
        return "No journal entries this week."

    combined = "\n\n".join(entries)
    if llm_caller:
        return llm_caller(
            f"Summarise these journal entries in 3-4 sentences. "
            f"Note emotional themes, key events, and any patterns:\n\n{combined[:3000]}"
        )
    return f"You wrote {len(entries)} journal entries this week.\n\n" + combined[:600]


def get_recent_mood_trend() -> str:
    """Return a brief mood summary from the last 5 journal entries."""
    moods = []
    today = date.today()
    for i in range(7):
        d    = today - timedelta(days=i)
        file = JOURNAL_DIR / f"{d.isoformat()}.md"
        if file.exists():
            text = file.read_text(encoding="utf-8")
            mood = _extract_mood(text)
            if mood:
                moods.append(mood)

    if not moods:
        return ""
    from collections import Counter
    top = Counter(moods).most_common(1)[0][0]
    return f"Your journal suggests you've mostly been feeling {top} this week."
