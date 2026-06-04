"""tests/test_pomodoro.py — Tests for the Pomodoro timer."""

import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAST = 0.02   # 0.02 minutes = 1.2 seconds — short enough for tests


@pytest.fixture(autouse=True)
def reset_pom(monkeypatch):
    """Reset all Pomodoro state before every test."""
    # Stop any running timer
    tools._pom_stop_event.set()
    if tools._pom_thread and tools._pom_thread.is_alive():
        tools._pom_thread.join(timeout=2)

    tools._pom_state         = "idle"
    tools._pom_cycle_in_set  = 0
    tools._pom_total_today   = 0
    tools._pom_end_time      = None
    tools._pom_thread        = None
    tools._pom_stop_event    = threading.Event()
    tools._pom_skip_event    = threading.Event()

    # Override config with fast durations
    monkeypatch.setattr(tools, "CFG", {
        "pomodoro": {
            "work_minutes":           FAST,
            "break_minutes":          FAST,
            "long_break_minutes":     FAST,
            "cycles_before_long_break": 2,
            "sound_on_end":           True,
        }
    })

    # Capture spoken phrases instead of actually speaking
    spoken: list[str] = []
    tools.set_pomodoro_speak(spoken.append)

    yield spoken

    # Teardown
    tools._pom_stop_event.set()
    if tools._pom_thread and tools._pom_thread.is_alive():
        tools._pom_thread.join(timeout=2)
    tools.set_pomodoro_speak(None)


# ---------------------------------------------------------------------------
# start_pomodoro
# ---------------------------------------------------------------------------

def test_start_returns_message():
    result = tools.start_pomodoro()
    assert "Pomodoro started" in result
    assert "focus" in result.lower()


def test_start_sets_work_state():
    tools.start_pomodoro()
    time.sleep(0.1)
    assert tools._pom_state == "work"


def test_start_custom_duration():
    result = tools.start_pomodoro(work_minutes=45)
    assert "45" in result


def test_start_restarts_running_timer():
    tools.start_pomodoro()
    time.sleep(0.1)
    result = tools.start_pomodoro()   # restart
    assert "Pomodoro started" in result


# ---------------------------------------------------------------------------
# stop_pomodoro
# ---------------------------------------------------------------------------

def test_stop_idle():
    result = tools.stop_pomodoro()
    assert "stopped" in result.lower()


def test_stop_running_timer():
    tools.start_pomodoro()
    time.sleep(0.1)
    result = tools.stop_pomodoro()
    assert "stopped" in result.lower()
    time.sleep(0.1)
    assert tools._pom_state == "idle"


def test_stop_clears_end_time():
    tools.start_pomodoro()
    time.sleep(0.1)
    tools.stop_pomodoro()
    assert tools._pom_end_time is None


# ---------------------------------------------------------------------------
# pomodoro_time_left
# ---------------------------------------------------------------------------

def test_time_left_when_idle():
    result = tools.pomodoro_time_left()
    assert "No Pomodoro" in result


def test_time_left_during_work():
    tools.start_pomodoro()
    time.sleep(0.1)
    result = tools.pomodoro_time_left()
    assert "Work" in result
    assert "remaining" in result


def test_time_left_format():
    tools.start_pomodoro()
    time.sleep(0.1)
    result = tools.pomodoro_time_left()
    # Must contain MM:SS pattern
    import re
    assert re.search(r"\d+:\d{2}", result)


# ---------------------------------------------------------------------------
# pomodoro_skip_break
# ---------------------------------------------------------------------------

def test_skip_when_no_break():
    result = tools.pomodoro_skip_break()
    assert "No break" in result


def test_skip_transitions_to_work(reset_pom):
    spoken = reset_pom
    tools.start_pomodoro()
    # Wait for work phase to finish and break to start
    time.sleep(FAST * 60 + 0.4)
    assert tools._pom_state in ("break", "long_break", "work", "idle")

    if tools._pom_state in ("break", "long_break"):
        result = tools.pomodoro_skip_break()
        assert "Skip" in result or "skip" in result
        time.sleep(0.3)
        assert tools._pom_state == "work"


# ---------------------------------------------------------------------------
# pomodoro_count
# ---------------------------------------------------------------------------

def test_count_zero_at_start():
    result = tools.pomodoro_count()
    assert "0" in result


def test_count_increments_after_cycle(reset_pom):
    spoken = reset_pom
    tools.start_pomodoro()
    # Wait for one full work+break cycle (2 × FAST minutes + buffer)
    time.sleep(FAST * 60 * 2 + 1.0)
    count = tools._pom_total_today
    assert count >= 1
    result = tools.pomodoro_count()
    assert str(count) in result


# ---------------------------------------------------------------------------
# get_pomodoro_status (tray UI string)
# ---------------------------------------------------------------------------

def test_status_idle():
    result = tools.get_pomodoro_status()
    assert "idle" in result.lower()


def test_status_work():
    tools.start_pomodoro()
    time.sleep(0.1)
    result = tools.get_pomodoro_status()
    assert "Work" in result
    assert "left" in result


def test_status_shows_done_count():
    result = tools.get_pomodoro_status()
    assert "done" in result


# ---------------------------------------------------------------------------
# TTS notifications spoken at correct moments
# ---------------------------------------------------------------------------

def test_work_end_announcement(reset_pom):
    spoken = reset_pom
    tools.start_pomodoro()
    # Wait past work phase
    time.sleep(FAST * 60 + 0.5)
    assert any("minutes up" in s or "cycles done" in s for s in spoken), spoken


def test_break_end_announcement(reset_pom):
    spoken = reset_pom
    tools.start_pomodoro()
    # Wait past work + break
    time.sleep(FAST * 60 * 2 + 1.0)
    assert any("Back to work" in s for s in spoken), spoken


# ---------------------------------------------------------------------------
# Intent router
# ---------------------------------------------------------------------------

def test_router_start_pomodoro():
    import intent_router
    r = intent_router.route("start pomodoro")
    assert r is not None
    assert "Pomodoro" in r


def test_router_custom_duration():
    import intent_router
    r = intent_router.route("start a 45 minute timer")
    assert r is not None
    assert "45" in r


def test_router_how_long_left():
    import intent_router
    r = intent_router.route("how long left")
    assert r is not None


def test_router_skip_break():
    import intent_router
    r = intent_router.route("skip this break")
    assert r is not None


def test_router_stop_pomodoro():
    import intent_router
    tools.start_pomodoro()
    time.sleep(0.1)
    r = intent_router.route("stop pomodoro")
    assert r is not None
    assert "stopped" in r.lower()


def test_router_how_many_today():
    import intent_router
    r = intent_router.route("how many pomodoros today")
    assert r is not None
    assert "today" in r.lower() or "Pomodoro" in r
