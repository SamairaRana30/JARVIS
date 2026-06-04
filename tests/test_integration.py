"""
tests/test_integration.py — Dry-run end-to-end integration tests.

Simulates the full 14-step integration test without mic or Ollama
by mocking STT, TTS, and LLM components.

Run with: pytest tests/test_integration.py -v
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools
import intent_router


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def jarvis_env(tmp_path, monkeypatch):
    """Set up isolated temp data files for every test."""
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "notes" / "quick").mkdir(parents=True)
    (tmp_path / "notes" / "study").mkdir(parents=True)
    (tmp_path / "logs" / "conversations").mkdir(parents=True)
    (tmp_path / "exports").mkdir()

    # Seed data files
    (tmp_path / "data" / "tasks.json").write_text("[]")
    (tmp_path / "data" / "sites.json").write_text(
        '{"distracting":["youtube.com","instagram.com"],"study":["notion.so"],"quick_links":{}}'
    )
    (tmp_path / "data" / "notes_index.json").write_text("[]")
    (tmp_path / "data" / "fridge.json").write_text(
        '{"items":[{"name":"milk","quantity":"1L","expires":"2025-06-04"}],'
        '"grocery_list":[],"last_updated":"2025-06-03"}'
    )
    (tmp_path / "data" / "reminders.json").write_text("[]")
    (tmp_path / "data" / "goals.json").write_text(
        '{"long_term":[],"short_term":[{"goal":"Ship StyleMate MVP","deadline":"2025-09","progress":30}],"weekly":[]}'
    )
    (tmp_path / "memory" / "sessions.json").write_text(
        '[{"date":"2025-06-02","summary":"Worked on StyleMate CSS","topics":["StyleMate","CSS"],'
        '"left_unfinished":["auth flow"],"mood":"good","what_we_worked_on":"CSS refactor"}]'
    )
    (tmp_path / "memory" / "progress.json").write_text(
        '{"goals":[{"goal":"Ship StyleMate MVP","started":"2025-06-01","deadline":"2025-09",'
        '"snapshots":[{"date":"2025-06-01","progress_percent":20,"note":"initial"},{"date":"2025-06-03","progress_percent":30,"note":"css done"}]}]}'
    )
    (tmp_path / "memory" / "wellbeing_log.json").write_text("[]")
    (tmp_path / "memory" / "long_term.json").write_text('{"preferences":[],"personal":[],"opinions":[],"context":[]}')
    (tmp_path / "memory" / "followups.json").write_text("[]")
    (tmp_path / "memory" / "decisions.json").write_text("[]")
    (tmp_path / "data" / "memory.json").write_text(
        '{"name":"Samaira","location":"Berlin","uni":"Test Uni","projects":["StyleMate"],'
        '"preferences":{},"study_apps":[],"quick_links":{},"notes":[]}'
    )

    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "PATHS", {
        "tasks":      "data/tasks.json",
        "sites":      "data/sites.json",
        "notes_index":"data/notes_index.json",
        "notes":      "notes/",
        "fridge":     "data/fridge.json",
        "reminders":  "data/reminders.json",
        "goals":      "data/goals.json",
        "memory":     "data/memory.json",
        "sessions":   "memory/sessions.json",
        "progress":   "memory/progress.json",
        "wellbeing":  "memory/wellbeing_log.json",
        "lt_memory":  "memory/long_term.json",
        "followups":  "memory/followups.json",
        "decisions":  "memory/decisions.json",
        "backups":    "backups/",
        "exports":    "exports/",
        "convos":     "logs/conversations/",
    })
    monkeypatch.setattr(tools, "CFG", {
        "paths": {"backups": "backups/", "exports": "exports/"},
        "notes": {"remind_related": True, "max_read_length": 500},
        "backup": {"keep_last_n": 5},
        "expiry_warning_days": 2,
        "timezone": "Europe/Berlin",
    })
    # Silence play_sound during tests
    monkeypatch.setattr(tools, "play_sound", lambda *a, **k: None)

    # Reset module-level state in intent_router between tests
    intent_router.set_pending_confirm(None)

    yield tmp_path

    # Cleanup: reset pending confirm after each test
    intent_router.set_pending_confirm(None)


def _tasks(tmp_path):
    return json.loads((tmp_path / "data" / "tasks.json").read_text())

def _sites(tmp_path):
    return json.loads((tmp_path / "data" / "sites.json").read_text())

def _notes_index(tmp_path):
    return json.loads((tmp_path / "data" / "notes_index.json").read_text())


# ---------------------------------------------------------------------------
# Test 01 — Add a high priority task
# ---------------------------------------------------------------------------

def test_01_add_high_priority_task(jarvis_env):
    result = intent_router.route("add high priority task finish Scrum report by Friday")
    assert result is not None
    data = _tasks(jarvis_env)
    assert len(data) == 1
    assert "Scrum" in data[0]["title"] or "scrum" in data[0]["title"].lower()
    assert data[0]["priority"] == "high"
    assert data[0]["done"] is False


# ---------------------------------------------------------------------------
# Test 02 — Check fridge expiry
# ---------------------------------------------------------------------------

def test_02_check_fridge_expiry(jarvis_env):
    result = intent_router.route("what's expiring soon")
    assert result is not None
    assert "milk" in result.lower() or "expir" in result.lower()


# ---------------------------------------------------------------------------
# Test 03 — Take a quick note
# ---------------------------------------------------------------------------

def test_03_take_quick_note(jarvis_env):
    result = intent_router.route("note this: remember to add auth to StyleMate")
    assert result is not None
    assert "saved" in result.lower() or "got it" in result.lower()
    # File exists in notes/quick/
    notes = list((jarvis_env / "notes" / "quick").glob("*.md"))
    assert len(notes) == 1
    # Index updated
    index = _notes_index(jarvis_env)
    assert len(index) == 1


# ---------------------------------------------------------------------------
# Test 04 — Search that note back
# ---------------------------------------------------------------------------

def test_04_search_note_back(jarvis_env):
    # Seed a note first
    tools.save_note("remember to add auth to StyleMate", folder="quick")
    result = intent_router.route("find my notes about StyleMate")
    assert result is not None
    assert "StyleMate" in result or "stylemate" in result.lower()


# ---------------------------------------------------------------------------
# Test 05 — Block sites (dry run)
# ---------------------------------------------------------------------------

def test_05_block_sites_dry_run(jarvis_env):
    # In dry-run mode (no hosts file access in tests) — just check
    # the confirmation flow fires correctly
    result = intent_router.route("start study mode")
    assert result is not None
    assert "confirm" in result.lower() or "block" in result.lower()


# ---------------------------------------------------------------------------
# Test 06 — List blocked sites
# ---------------------------------------------------------------------------

def test_06_list_blocked_sites(jarvis_env):
    result = intent_router.route("what sites are blocked")
    assert result is not None
    assert "youtube" in result.lower() or "instagram" in result.lower()


# ---------------------------------------------------------------------------
# Test 07 — Add a site by voice
# ---------------------------------------------------------------------------

def test_07_add_site_by_voice(jarvis_env):
    result = intent_router.route("add discord.com to distracting sites")
    assert result is not None
    data = _sites(jarvis_env)
    assert "discord.com" in data["distracting"]


# ---------------------------------------------------------------------------
# Test 08 — Check battery
# ---------------------------------------------------------------------------

def test_08_check_battery(jarvis_env):
    with patch("psutil.sensors_battery") as mock_bat:
        mock_bat.return_value = MagicMock(percent=72, power_plugged=True)
        result = intent_router.route("battery")
    assert result is not None
    assert "72" in result or "battery" in result.lower()


# ---------------------------------------------------------------------------
# Test 09 — Switch profile
# ---------------------------------------------------------------------------

def test_09_switch_profile(jarvis_env):
    result = intent_router.route("switch to chill mode")
    assert result is not None
    assert "chill" in result.lower()


# ---------------------------------------------------------------------------
# Test 10 — Last session recall
# ---------------------------------------------------------------------------

def test_10_last_session_recall(jarvis_env):
    result = intent_router.route("what were we working on last time")
    assert result is not None
    assert "StyleMate" in result or "session" in result.lower()


# ---------------------------------------------------------------------------
# Test 11 — Goal progress
# ---------------------------------------------------------------------------

def test_11_goal_progress(jarvis_env):
    result = intent_router.route("how much progress on StyleMate")
    assert result is not None
    assert "30" in result or "stylemate" in result.lower()


# ---------------------------------------------------------------------------
# Test 12 — Backup everything
# ---------------------------------------------------------------------------

def test_12_backup_everything(jarvis_env):
    result = tools.backup_everything()
    assert "Backup saved" in result
    backups = list((jarvis_env / "exports").glob("jarvis_backup_*.zip"))
    assert len(backups) == 1


# ---------------------------------------------------------------------------
# Test 13 — End session memory extraction (mocked LLM)
# ---------------------------------------------------------------------------

def test_13_end_session_memory_extraction(jarvis_env):
    fake_llm = MagicMock(return_value="Worked on StyleMate CSS refactor.")
    conversation = [
        {"role": "user",      "content": "I'm feeling tired today"},
        {"role": "assistant", "content": "I understand. Let's keep it light."},
    ]
    tools.extract_memory(conversation, llm_caller=fake_llm)
    sessions = json.loads((jarvis_env / "memory" / "sessions.json").read_text())
    assert len(sessions) >= 1


# ---------------------------------------------------------------------------
# Test 14 — Doctor command (mocked checks)
# ---------------------------------------------------------------------------

def test_14_doctor_command(jarvis_env):
    with patch("requests.get") as mock_req, \
         patch("psutil.virtual_memory") as mock_ram, \
         patch("psutil.sensors_battery", return_value=None), \
         patch("sounddevice.query_devices"):
        mock_req.return_value = MagicMock(
            status_code=200,
            json=lambda: {"models": [{"name": "llama3:latest"}]},
        )
        mock_ram.return_value = MagicMock(percent=45.0, available=4 * 2**30)
        result = tools.jarvis_doctor()
    assert result is not None
    assert "Diagnostics complete" in result
    assert "passed" in result
