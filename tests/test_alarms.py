"""tests/test_alarms.py — Tests for alarm_tool and reminder system."""

import json
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_base(tmp_path, monkeypatch):
    """Redirect all paths to tmp so tests don't touch real data."""
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "data" / "reminders.json").write_text("[]")

    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "PATHS", {
        "reminders": "data/reminders.json",
        "backups":   "backups/",
    })
    monkeypatch.setattr(tools, "CFG", {"paths": {"backups": "backups/"}})
    yield tmp_path


def _reminders(tmp_path) -> list:
    return json.loads((tmp_path / "data" / "reminders.json").read_text())


# ---------------------------------------------------------------------------
# create_reminder
# ---------------------------------------------------------------------------

def test_create_reminder_saves_to_file(tmp_path):
    dt = datetime.now() + timedelta(minutes=30)
    tools.create_reminder("Check emails", dt)
    data = _reminders(tmp_path)
    assert len(data) == 1
    assert data[0]["message"] == "Check emails"
    assert data[0]["done"] is False


def test_create_reminder_id_format(tmp_path):
    dt = datetime.now() + timedelta(minutes=10)
    tools.create_reminder("Test", dt)
    data = _reminders(tmp_path)
    assert data[0]["id"].startswith("rem_")


def test_create_multiple_reminders_increment_ids(tmp_path):
    dt = datetime.now() + timedelta(minutes=10)
    tools.create_reminder("First",  dt)
    tools.create_reminder("Second", dt)
    tools.create_reminder("Third",  dt)
    data = _reminders(tmp_path)
    ids = [d["id"] for d in data]
    assert ids == ["rem_001", "rem_002", "rem_003"]


def test_create_alarm_kind(tmp_path):
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("Alarm", dt, kind="alarm")
    data = _reminders(tmp_path)
    assert data[0]["kind"] == "alarm"


def test_create_daily_reminder(tmp_path):
    dt = datetime.now() + timedelta(hours=8)
    tools.create_reminder("Exercise", dt, repeat="daily")
    data = _reminders(tmp_path)
    assert data[0]["repeat"] == "daily"


def test_create_reminder_returns_confirmation():
    dt = datetime.now() + timedelta(minutes=30)
    result = tools.create_reminder("check emails", dt)
    assert "check emails" in result.lower()
    assert "remind" in result.lower() or "alarm" in result.lower()


def test_backup_created_on_create(tmp_path):
    dt = datetime.now() + timedelta(minutes=5)
    tools.create_reminder("backup test", dt)
    bak = tmp_path / "data" / "reminders.bak"
    # After second write the .bak will exist (first write creates the file)
    tools.create_reminder("second", dt)
    assert bak.exists()


# ---------------------------------------------------------------------------
# list_reminders
# ---------------------------------------------------------------------------

def test_list_empty():
    result = tools.list_reminders()
    assert "no upcoming" in result.lower()


def test_list_shows_reminders(tmp_path):
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("Doctor appointment", dt)
    result = tools.list_reminders()
    assert "Doctor appointment" in result


def test_list_excludes_done(tmp_path):
    data = [{"id": "rem_001", "message": "done task", "trigger_at":
             (datetime.now() + timedelta(hours=1)).isoformat(),
             "repeat": None, "done": True, "kind": "reminder"}]
    (tmp_path / "data" / "reminders.json").write_text(json.dumps(data))
    result = tools.list_reminders()
    assert "done task" not in result


def test_list_sorted_by_time(tmp_path):
    dt1 = datetime.now() + timedelta(hours=2)
    dt2 = datetime.now() + timedelta(hours=1)
    tools.create_reminder("Later",  dt1)
    tools.create_reminder("Sooner", dt2)
    result = tools.list_reminders()
    assert result.index("Sooner") < result.index("Later")


# ---------------------------------------------------------------------------
# cancel_reminder
# ---------------------------------------------------------------------------

def test_cancel_existing(tmp_path):
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("Call dentist", dt)
    result = tools.cancel_reminder("dentist")
    assert "Cancelled" in result
    data = _reminders(tmp_path)
    assert data[0]["done"] is True


def test_cancel_not_found():
    result = tools.cancel_reminder("nonexistent reminder")
    assert "No active" in result


def test_cancel_partial_match(tmp_path):
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("submit assignment", dt)
    result = tools.cancel_reminder("assignment")
    assert "Cancelled" in result


# ---------------------------------------------------------------------------
# fire_reminder — marks done, reschedules repeat
# ---------------------------------------------------------------------------

def test_fire_marks_done(tmp_path):
    dt = datetime.now() + timedelta(minutes=1)
    tools.create_reminder("Test fire", dt)
    data = _reminders(tmp_path)
    tools.fire_reminder(data[0], speak_fn=lambda x: None)
    updated = _reminders(tmp_path)
    assert updated[0]["done"] is True


def test_fire_reschedules_daily(tmp_path):
    dt = datetime.now() + timedelta(minutes=1)
    tools.create_reminder("Daily reminder", dt, repeat="daily")
    data = _reminders(tmp_path)
    tools.fire_reminder(data[0], speak_fn=lambda x: None)
    updated = _reminders(tmp_path)
    assert updated[0]["done"] is False
    new_dt = datetime.fromisoformat(updated[0]["trigger_at"])
    assert new_dt > dt  # rescheduled forward


def test_fire_reschedules_weekly(tmp_path):
    dt = datetime.now() + timedelta(minutes=1)
    tools.create_reminder("Weekly reminder", dt, repeat="weekly")
    data = _reminders(tmp_path)
    tools.fire_reminder(data[0], speak_fn=lambda x: None)
    updated = _reminders(tmp_path)
    assert updated[0]["done"] is False
    new_dt = datetime.fromisoformat(updated[0]["trigger_at"])
    expected = dt + timedelta(weeks=1)
    assert abs((new_dt - expected).total_seconds()) < 5


def test_fire_calls_speak(tmp_path):
    spoken = []
    dt = datetime.now() + timedelta(minutes=1)
    tools.create_reminder("Buy milk", dt)
    data = _reminders(tmp_path)
    tools.fire_reminder(data[0], speak_fn=spoken.append)
    assert any("Buy milk" in s for s in spoken)


# ---------------------------------------------------------------------------
# parse_reminder_time
# ---------------------------------------------------------------------------

def test_parse_in_minutes():
    dt = tools.parse_reminder_time("in 30 minutes")
    assert dt is not None
    diff = (dt - datetime.now()).total_seconds()
    assert 28 * 60 < diff < 32 * 60


def test_parse_in_hours():
    dt = tools.parse_reminder_time("in 2 hours")
    assert dt is not None
    diff = (dt - datetime.now()).total_seconds()
    assert 1.9 * 3600 < diff < 2.1 * 3600


def test_parse_at_time():
    dt = tools.parse_reminder_time("at 3pm")
    assert dt is not None
    assert dt > datetime.now()


def test_parse_invalid_returns_none():
    dt = tools.parse_reminder_time("purple elephant")
    assert dt is None


def test_parse_at_15_30():
    dt = tools.parse_reminder_time("at 15:30")
    assert dt is not None
    assert dt.hour == 15
    assert dt.minute == 30


# ---------------------------------------------------------------------------
# Intent router
# ---------------------------------------------------------------------------

def test_router_remind_in_minutes(tmp_path):
    import intent_router
    result = intent_router.route("remind me in 10 minutes to take medicine")
    assert result is not None
    assert "remind" in result.lower() or "medicine" in result.lower()


def test_router_set_alarm(tmp_path):
    import intent_router
    result = intent_router.route("set an alarm for 7:30am")
    assert result is not None


def test_router_list_reminders():
    import intent_router
    result = intent_router.route("what reminders do I have")
    assert result is not None
    assert "reminder" in result.lower() or "alarm" in result.lower()


def test_router_cancel_reminder(tmp_path):
    import intent_router
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("dentist appointment", dt)
    result = intent_router.route("cancel my dentist reminder")
    assert result is not None
    assert "Cancelled" in result or "dentist" in result


def test_router_daily_reminder(tmp_path):
    import intent_router
    result = intent_router.route("remind me every day at 8am to exercise")
    assert result is not None
    data = _reminders(tmp_path)
    assert any(r.get("repeat") == "daily" for r in data)


# ---------------------------------------------------------------------------
# edit_reminder
# ---------------------------------------------------------------------------

def test_edit_reminder_updates_time(tmp_path):
    original_dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("dentist appointment", original_dt)

    new_dt = datetime.now() + timedelta(hours=5)
    # patch parse_reminder_time to return a known future time
    import unittest.mock as mock
    with mock.patch("tools.parse_reminder_time", return_value=new_dt):
        result = tools.edit_reminder("dentist", "Thursday at 3pm")

    assert "Updated" in result
    data = _reminders(tmp_path)
    saved_dt = datetime.fromisoformat(data[0]["trigger_at"])
    assert abs((saved_dt - new_dt).total_seconds()) < 2


def test_edit_reminder_not_found():
    result = tools.edit_reminder("nonexistent reminder", "tomorrow")
    assert "No reminder" in result or "not found" in result.lower()


def test_edit_reminder_bad_time(tmp_path):
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("call dentist", dt)
    result = tools.edit_reminder("dentist", "purple elephant")
    assert "couldn't understand" in result.lower()


def test_edit_reminder_reactivates_done(tmp_path):
    """edit_reminder should reactivate a done reminder."""
    data = [{
        "id": "rem_001", "message": "old reminder",
        "trigger_at": (datetime.now() - timedelta(hours=1)).isoformat(),
        "repeat": None, "done": True, "kind": "reminder", "created": datetime.now().isoformat()
    }]
    (tmp_path / "data" / "reminders.json").write_text(json.dumps(data))

    new_dt = datetime.now() + timedelta(hours=2)
    import unittest.mock as mock
    with mock.patch("tools.parse_reminder_time", return_value=new_dt):
        result = tools.edit_reminder("old reminder", "in 2 hours")

    assert "Updated" in result
    updated = _reminders(tmp_path)
    assert updated[0]["done"] is False


def test_router_edit_reminder(tmp_path):
    import intent_router
    dt = datetime.now() + timedelta(hours=1)
    tools.create_reminder("dentist appointment", dt)

    import unittest.mock as mock
    new_dt = datetime.now() + timedelta(days=3)
    with mock.patch("tools.parse_reminder_time", return_value=new_dt):
        result = intent_router.route("reschedule my dentist reminder to Thursday")

    assert result is not None
    assert "Updated" in result or "dentist" in result.lower()
