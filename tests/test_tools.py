"""tests/test_tools.py — Tests for core tool helpers and data file operations."""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

# Ensure Jarvis root is on sys.path
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_base(tmp_path, monkeypatch):
    """Redirect all file I/O to a temp directory."""
    # Create required dirs
    (tmp_path / "data").mkdir()
    (tmp_path / "memory").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "logs" / "conversations").mkdir(parents=True)
    (tmp_path / "notes" / "quick").mkdir(parents=True)
    (tmp_path / "notes" / "study").mkdir(parents=True)
    (tmp_path / "notes" / "projects").mkdir(parents=True)
    (tmp_path / "notes" / "ideas").mkdir(parents=True)

    # Write minimal data files
    (tmp_path / "data" / "tasks.json").write_text("[]", encoding="utf-8")
    (tmp_path / "data" / "fridge.json").write_text(
        '{"items":[],"grocery_list":[],"last_updated":"2025-01-01"}', encoding="utf-8"
    )
    (tmp_path / "data" / "sites.json").write_text(
        '{"distracting":[],"study":[],"quick_links":{}}', encoding="utf-8"
    )
    (tmp_path / "data" / "memory.json").write_text(
        '{"name":"Test","location":"Berlin","uni":"TU","projects":[],'
        '"preferences":{},"study_apps":[],"quick_links":{},"notes":[]}',
        encoding="utf-8",
    )
    (tmp_path / "data" / "goals.json").write_text(
        '{"long_term":[],"short_term":[],"weekly":[]}', encoding="utf-8"
    )
    (tmp_path / "data" / "routines.json").write_text(
        '{"habits":[],"wellbeing":{}}', encoding="utf-8"
    )
    (tmp_path / "data" / "notes_index.json").write_text("[]", encoding="utf-8")
    (tmp_path / "memory" / "long_term.json").write_text(
        '{"preferences":[],"personal":[],"opinions":[],"context":[]}', encoding="utf-8"
    )
    (tmp_path / "memory" / "sessions.json").write_text("[]", encoding="utf-8")
    (tmp_path / "memory" / "decisions.json").write_text("[]", encoding="utf-8")
    (tmp_path / "memory" / "followups.json").write_text("[]", encoding="utf-8")
    (tmp_path / "memory" / "wellbeing_log.json").write_text("[]", encoding="utf-8")
    (tmp_path / "memory" / "progress.json").write_text('{"goals":[]}', encoding="utf-8")

    # Patch config paths
    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "PATHS", {
        "memory":    "data/memory.json",
        "tasks":     "data/tasks.json",
        "goals":     "data/goals.json",
        "fridge":    "data/fridge.json",
        "routines":  "data/routines.json",
        "sites":     "data/sites.json",
        "logs":      "logs/jarvis.log",
        "convos":    "logs/conversations/",
        "backups":   "backups/",
        "prompts":   "prompts/system.txt",
        "notes":     "notes/",
        "lt_memory": "memory/long_term.json",
        "sessions":  "memory/sessions.json",
        "decisions": "memory/decisions.json",
        "followups": "memory/followups.json",
        "wellbeing": "memory/wellbeing_log.json",
        "progress":  "memory/progress.json",
        "notes_index": "data/notes_index.json",
    })
    monkeypatch.setattr(tools, "CFG", {
        "expiry_warning_days": 2,
        "low_power_mode": False,
        "notes": {"max_read_length": 500},
        "memory": {"max_long_term_facts": 20, "extract_after_session": True},
        "paths": {
            "backups": "backups/",
            "notes_index": "data/notes_index.json",
            "notes": "notes/",
        },
    })


# ---------------------------------------------------------------------------
# JSON read/write
# ---------------------------------------------------------------------------

def test_read_write_json(tmp_path):
    path = tmp_path / "test.json"
    tools._write_json(path, {"hello": "world"})
    data = tools._read_json(path)
    assert data["hello"] == "world"


def test_backup_created_on_write(tmp_path):
    path = tmp_path / "data" / "tasks.json"
    tools._write_json(path, [])
    tools._write_json(path, [{"id": "1"}])
    assert path.with_suffix(".bak").exists()


def test_auto_restore_from_bak(tmp_path):
    path = tmp_path / "corrupt.json"
    bak  = path.with_suffix(".bak")
    path.write_text("{invalid json{{", encoding="utf-8")
    bak.write_text('{"ok": true}', encoding="utf-8")
    data = tools._read_json(path)
    assert data["ok"] is True


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

def test_add_task():
    result = tools.add_task("Write report")
    assert "Write report" in result


def test_list_tasks_empty():
    result = tools.list_tasks()
    assert "No pending" in result


def test_add_then_list():
    tools.add_task("Task A")
    result = tools.list_tasks()
    assert "Task A" in result


def test_mark_task_done():
    tools.add_task("Task B")
    result = tools.mark_task_done("Task B")
    assert "done" in result.lower()
    remaining = tools.list_tasks()
    assert "Task B" not in remaining


def test_mark_task_not_found():
    result = tools.mark_task_done("Nonexistent Task")
    assert "No pending" in result


def test_hours_until_deadline():
    future = (date.today() + timedelta(days=1)).isoformat() + "T00:00:00"
    tools.add_task("Deadline task", deadline=future)
    result = tools.hours_until_deadline("Deadline task")
    assert "h" in result


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

def test_calculate_basic():
    assert tools.calculate("2 + 2") == "4"


def test_calculate_percentage():
    assert tools.calculate("20% of 100") == "20.0"


def test_calculate_days_until():
    future = (date.today() + timedelta(days=5)).isoformat()
    result = tools.calculate(f"days until {future}")
    assert "5 days" in result


def test_calculate_currency():
    result = tools.calculate("100 usd to eur")
    assert "EUR" in result


def test_calculate_bad_expr():
    result = tools.calculate("not a number !!!")
    assert "couldn't" in result.lower()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def test_config_load():
    cfg_path = ROOT / "config.yaml"
    import yaml
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    required = ["version", "model", "max_turns", "paths", "voice"]
    for key in required:
        assert key in cfg, f"Missing config key: {key}"


# ---------------------------------------------------------------------------
# Intent router
# ---------------------------------------------------------------------------

def test_router_datetime():
    import intent_router
    r = intent_router.route("what time is it")
    assert r is not None and (":" in r or "time" in r.lower())


def test_router_task_add():
    import intent_router
    r = intent_router.route("add task finish homework")
    assert r is not None and "finish homework" in r.lower()


def test_router_fallthrough():
    import intent_router
    r = intent_router.route("tell me a joke")
    assert r is None  # should fall through to LLM
