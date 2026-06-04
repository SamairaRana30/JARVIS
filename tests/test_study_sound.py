"""tests/test_study_sound.py — Tests for background sound in study mode."""

import sys
import threading
import time
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent_wav(path: Path, duration_s: float = 0.1) -> None:
    """Write a minimal valid WAV file (silent) for testing."""
    sample_rate = 44100
    n_channels  = 2
    sampwidth   = 2
    n_frames    = int(sample_rate * duration_s)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(n_channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00" * sampwidth * n_channels * n_frames)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_sound(tmp_path, monkeypatch):
    """Redirect sound paths to tmp and reset global sound state."""
    sounds_dir = tmp_path / "assets" / "sounds"
    _make_silent_wav(sounds_dir / "lofi.mp3")
    _make_silent_wav(sounds_dir / "rain.mp3")
    _make_silent_wav(sounds_dir / "white_noise.mp3")

    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "CFG", {
        "study_mode": {
            "background_sound": "lofi",
            "sound_path": "assets/sounds/",
            "volume": 0.0,  # silent in tests
        }
    })

    # Reset sound state before each test
    tools._current_sound = None
    tools._sound_stop_event = threading.Event()
    tools._sound_thread = None

    yield

    # Teardown: stop any playing sound
    tools.stop_background_sound()


# ---------------------------------------------------------------------------
# _resolve_sound_path
# ---------------------------------------------------------------------------

def test_resolve_sound_path_lofi(tmp_path):
    path = tools._resolve_sound_path("lofi")
    assert path is not None
    assert path.exists()


def test_resolve_sound_path_rain(tmp_path):
    path = tools._resolve_sound_path("rain")
    assert path is not None


def test_resolve_sound_path_missing():
    # Point BASE_DIR somewhere without any sound files
    import tools as t2
    orig = t2.BASE_DIR
    t2.BASE_DIR = Path("/nonexistent_dir_xyz")
    path = t2._resolve_sound_path("lofi")
    t2.BASE_DIR = orig
    assert path is None


# ---------------------------------------------------------------------------
# start_background_sound
# ---------------------------------------------------------------------------

def test_start_sound_sets_current_sound(monkeypatch):
    # Mock pygame so the test doesn't need the library
    monkeypatch.setattr(tools, "_pygame_play_loop", lambda *a, **k: None)
    tools.start_background_sound("rain")
    time.sleep(0.05)
    assert tools._current_sound == "rain"


def test_start_sound_invalid_name():
    result = tools.start_background_sound("dubstep")
    assert "Unknown sound" in result


def test_start_sound_none_stops():
    result = tools.start_background_sound("none")
    assert "stopped" in result.lower()


def test_start_sound_missing_file(tmp_path, monkeypatch):
    # Remove the sound file
    (tmp_path / "assets" / "sounds" / "lofi.mp3").unlink()
    result = tools.start_background_sound("lofi")
    assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# stop_background_sound
# ---------------------------------------------------------------------------

def test_stop_sound_when_nothing_playing():
    result = tools.stop_background_sound()
    assert "stopped" in result.lower()
    assert tools._current_sound is None


def test_stop_clears_current_sound(monkeypatch):
    monkeypatch.setattr(tools, "_pygame_play_loop", lambda *a, **k: None)
    tools.start_background_sound("lofi")
    time.sleep(0.05)
    tools.stop_background_sound()
    assert tools._current_sound is None


# ---------------------------------------------------------------------------
# switch_sound
# ---------------------------------------------------------------------------

def test_switch_sound(monkeypatch):
    monkeypatch.setattr(tools, "_pygame_play_loop", lambda *a, **k: None)
    tools.start_background_sound("lofi")
    time.sleep(0.05)
    tools.switch_sound("rain")
    time.sleep(0.05)
    assert tools._current_sound == "rain"


# ---------------------------------------------------------------------------
# get_current_sound
# ---------------------------------------------------------------------------

def test_get_current_sound_none():
    result = tools.get_current_sound()
    assert "No background" in result


def test_get_current_sound_playing(monkeypatch):
    played = []

    def _fake_play(path, volume, stop_event):
        played.append(path.name)
        stop_event.wait()  # block until stopped

    monkeypatch.setattr(tools, "_pygame_play_loop", _fake_play)
    tools.start_background_sound("lofi")
    time.sleep(0.1)
    result = tools.get_current_sound()
    assert "lofi" in result.lower()
    tools.stop_background_sound()


# ---------------------------------------------------------------------------
# Intent router — voice commands
# ---------------------------------------------------------------------------

def test_router_switch_to_rain(monkeypatch):
    import intent_router
    monkeypatch.setattr(tools, "_pygame_play_loop", lambda *a, **k: None)
    result = intent_router.route("switch to rain sounds")
    assert result is not None
    assert "rain" in result.lower()


def test_router_switch_to_lofi(monkeypatch):
    import intent_router
    monkeypatch.setattr(tools, "_pygame_play_loop", lambda *a, **k: None)
    result = intent_router.route("switch to lofi")
    assert result is not None
    assert "lofi" in result.lower()


def test_router_switch_to_white_noise(monkeypatch):
    import intent_router
    monkeypatch.setattr(tools, "_pygame_play_loop", lambda *a, **k: None)
    result = intent_router.route("put on white noise sounds")
    assert result is not None
    assert "white" in result.lower()


def test_router_turn_off_sound():
    import intent_router
    result = intent_router.route("turn off background sound")
    assert result is not None
    assert "stopped" in result.lower()


def test_router_stop_music():
    import intent_router
    result = intent_router.route("stop the music")
    assert result is not None
    assert "stopped" in result.lower()


def test_router_what_sound_playing():
    import intent_router
    result = intent_router.route("what sound is playing")
    assert result is not None
