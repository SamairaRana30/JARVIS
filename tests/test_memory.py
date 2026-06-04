"""tests/test_memory.py — Tests for memory extraction and long-term memory."""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


@pytest.fixture(autouse=True)
def patch_base(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "logs" / "conversations").mkdir(parents=True)

    def _write(name, content):
        (tmp_path / name).write_text(content, encoding="utf-8")

    _write("memory/long_term.json",    '{"preferences":[],"personal":[],"opinions":[],"context":[]}')
    _write("memory/sessions.json",     "[]")
    _write("memory/decisions.json",    "[]")
    _write("memory/followups.json",    "[]")
    _write("memory/wellbeing_log.json","[]")
    _write("memory/progress.json",     '{"goals":[{"goal":"Graduate","started":"2024-01-01","deadline":"2026-06","snapshots":[]}]}')
    _write("data/notes_index.json",    "[]")

    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "PATHS", {
        "lt_memory": "memory/long_term.json",
        "sessions":  "memory/sessions.json",
        "decisions": "memory/decisions.json",
        "followups": "memory/followups.json",
        "wellbeing": "memory/wellbeing_log.json",
        "progress":  "memory/progress.json",
        "convos":    "logs/conversations/",
        "backups":   "backups/",
        "notes_index": "data/notes_index.json",
    })
    monkeypatch.setattr(tools, "CFG", {
        "memory": {"max_long_term_facts": 20, "extract_after_session": True},
        "paths":  {"backups": "backups/"},
    })


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------

def test_transcript_written(tmp_path):
    convo_path = tmp_path / "logs" / "conversations" / f"{date.today().isoformat()}.md"
    convo_path.write_text("[10:00:00] YOU: Hello\n[10:00:02] JARVIS: Hi there.\n", encoding="utf-8")
    assert convo_path.exists()
    content = convo_path.read_text(encoding="utf-8")
    assert "YOU: Hello" in content
    assert "JARVIS: Hi there" in content


# ---------------------------------------------------------------------------
# Session summary saved
# ---------------------------------------------------------------------------

def test_session_summary_saved():
    conversation = [
        {"role": "user",      "content": "Add task finish report"},
        {"role": "assistant", "content": "Added task: finish report."},
    ]
    tools.extract_memory(conversation, llm_caller=None)
    sessions = tools._read_json(tools._p("sessions"))
    assert len(sessions) == 1
    assert sessions[0]["date"] == date.today().isoformat()


# ---------------------------------------------------------------------------
# Long-term memory
# ---------------------------------------------------------------------------

def test_long_term_fact_get_empty():
    result = tools.get_long_term_facts()
    assert "No long-term" in result


def test_long_term_fact_forget():
    lt = tools._read_json(tools._p("lt_memory"))
    lt["preferences"].append({"fact": "Prefers dark mode", "source": "2025-01-01"})
    tools._write_json(tools._p("lt_memory"), lt)

    result = tools.forget_fact("dark mode")
    assert "Removed 1" in result
    lt_after = tools._read_json(tools._p("lt_memory"))
    assert not any("dark mode" in f.get("fact", "") for f in lt_after["preferences"])


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def test_decisions_empty():
    result = tools.get_decisions()
    assert "No decisions" in result


def test_decisions_with_entry():
    decisions = tools._read_json(tools._p("decisions"))
    decisions.append({
        "date": "2025-06-01",
        "decision": "Use FastAPI for the backend",
        "context": "Needed async support",
        "alternatives_rejected": ["Flask"],
        "reason": "Better performance",
    })
    tools._write_json(tools._p("decisions"), decisions)

    result = tools.get_decisions("FastAPI")
    assert "FastAPI" in result


# ---------------------------------------------------------------------------
# Follow-ups
# ---------------------------------------------------------------------------

def test_followups_empty():
    result = tools.get_followups()
    assert "No open" in result


def test_followup_saved_and_surfaced():
    fups = tools._read_json(tools._p("followups"))
    fups.append({
        "id": "fu_001",
        "created": "2025-06-01T10:00:00",
        "topic": "StyleMate deadline",
        "note": "Check project board by Friday",
        "done": False,
        "done_date": None,
    })
    tools._write_json(tools._p("followups"), fups)

    result = tools.get_followups()
    assert "StyleMate" in result


# ---------------------------------------------------------------------------
# Wellbeing
# ---------------------------------------------------------------------------

def test_wellbeing_empty():
    result = tools.get_wellbeing()
    assert "No wellbeing" in result


def test_wellbeing_entry():
    wb = tools._read_json(tools._p("wellbeing"))
    wb.append({"date": "2025-06-01", "mood": "good", "energy": "high", "sleep": "7h", "notes": "", "source": "user-stated"})
    tools._write_json(tools._p("wellbeing"), wb)
    result = tools.get_wellbeing()
    assert "good" in result


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

def test_progress_snapshot_saved():
    result = tools.update_progress("Graduate", 65, "Passed exams")
    assert "65%" in result
    progress = tools._read_json(tools._p("progress"))
    goal = progress["goals"][0]
    assert goal["snapshots"][-1]["progress_percent"] == 65


def test_progress_delta():
    tools.update_progress("Graduate", 60)
    tools.update_progress("Graduate", 70)
    result = tools.get_progress("Graduate")
    assert "70%" in result


def test_progress_not_found():
    result = tools.update_progress("Nonexistent goal", 50)
    assert "No goal" in result


# ---------------------------------------------------------------------------
# Transcript search
# ---------------------------------------------------------------------------

def test_transcript_search(tmp_path):
    convo_dir = tmp_path / "logs" / "conversations"
    (convo_dir / "2025-06-01.md").write_text(
        "[10:00] YOU: Tell me about StyleMate\n[10:01] JARVIS: StyleMate is your project.\n",
        encoding="utf-8",
    )
    result = tools.search_transcripts("StyleMate")
    assert "StyleMate" in result


def test_transcript_search_no_match():
    result = tools.search_transcripts("quantum entanglement theory")
    assert "No conversations" in result


# ---------------------------------------------------------------------------
# Memory backup after extraction
# ---------------------------------------------------------------------------

def test_memory_files_backed_up(tmp_path):
    conversation = [{"role": "user", "content": "Hello"}, {"role": "assistant", "content": "Hi"}]
    tools.extract_memory(conversation, llm_caller=None)
    backup_dir = tmp_path / "backups"
    backed_up = list(backup_dir.glob("sessions.json"))
    assert len(backed_up) == 1
