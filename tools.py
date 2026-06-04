"""
tools.py — All 14 Jarvis tools.

Tools:
 1. PC Control
 2. Study Mode
 3. Task List
 4. PDF Reader
 5. System Info
 6. Calculator
 7. Clipboard Explainer
 8. Briefing Engine
 9. Fridge Manager
10. Recipes
11. Sites Manager
12. Routine Launcher
13. Notes Manager
14. Long-Term Memory
"""

import json
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import winreg

import requests
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import psutil
import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base paths
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CFG = _load_cfg()
PATHS = CFG.get("paths", {})


def _p(key: str) -> Path:
    """Return absolute Path for a config paths key."""
    return BASE_DIR / PATHS[key]


def _now() -> datetime:
    """Return current datetime in the configured timezone (naive-compatible)."""
    tz_name = CFG.get("timezone", "Europe/Berlin")
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(tz_name)).replace(tzinfo=None)
    except Exception:
        return _now()


# ---------------------------------------------------------------------------
# Audio feedback
# ---------------------------------------------------------------------------

_sound_channel: "pygame.mixer.Channel | None" = None   # type: ignore


def _parse_pct(s: str) -> int:
    """Parse '+10%' / '-5%' / '0%' to integer."""
    import re as _re
    m = _re.match(r"([+-]?\d+)%", str(s).strip())
    return int(m.group(1)) if m else 0


def _save_voice_setting(key: str, value: str) -> None:
    """Persist a top-level voice key to config.yaml."""
    cfg_path = BASE_DIR / "config.yaml"
    try:
        text = cfg_path.read_text(encoding="utf-8")
        import re as _re
        # Replace the value on the matching key line
        pattern = rf'^({re.escape(key)}:\s*)["\']?[^#\n]*["\']?'
        replacement = rf'\g<1>"{value}"'
        new_text = _re.sub(pattern, replacement, text, flags=_re.MULTILINE)
        if new_text != text:
            cfg_path.write_text(new_text, encoding="utf-8")
    except Exception as e:
        logger.warning("Could not persist voice setting %s=%s: %s", key, value, e)


def voice_settings_tool(action: str) -> str:
    """
    Adjust edge-tts speaking_rate and speaking_volume.
    Updates in-memory tts.py globals AND persists to config.yaml.

    Actions: louder / quieter / faster / slower / reset / status
    """
    import tts as _tts
    import re as _re

    action = action.lower().strip()
    STEP = 10   # percent points per adjustment
    MAX  = 50
    MIN  = -50

    if action == "reset":
        _tts._RATE   = "+0%"
        _tts._VOL_DB = "+0%"
        _save_voice_setting("speaking_rate",   "+0%")
        _save_voice_setting("speaking_volume", "+0%")
        return "Done, speaking at normal speed and volume now."

    if action == "status":
        rate_val = _parse_pct(_tts._RATE)
        vol_val  = _parse_pct(_tts._VOL_DB)
        rate_str = f"{rate_val:+d}% speed" if rate_val != 0 else "normal speed"
        vol_str  = f"{vol_val:+d}% volume" if vol_val != 0 else "normal volume"
        return f"Currently at {rate_str} and {vol_str}."

    if action in ("louder", "quieter"):
        delta    = STEP if action == "louder" else -STEP
        current  = _parse_pct(_tts._VOL_DB)
        new_val  = max(MIN, min(MAX, current + delta))
        new_str  = f"{new_val:+d}%"
        _tts._VOL_DB = new_str
        _save_voice_setting("speaking_volume", new_str)
        return "Done, speaking at this volume now."

    if action in ("faster", "slower"):
        delta    = STEP if action == "faster" else -STEP
        current  = _parse_pct(_tts._RATE)
        new_val  = max(MIN, min(MAX, current + delta))
        new_str  = f"{new_val:+d}%"
        _tts._RATE = new_str
        _save_voice_setting("speaking_rate", new_str)
        return "Done, speaking at this speed now."

    return f"Unknown action '{action}'. Try: louder, quieter, faster, slower, reset."


def play_sound(sound_name: str) -> None:
    """
    Play a named sound from config.yaml → sounds section.
    Uses pygame.mixer.Sound on a dedicated channel so it overlays
    background music without interrupting it.
    Graceful: logs a warning and returns silently if the file is missing.
    """
    global _sound_channel
    try:
        snd_cfg  = CFG.get("sounds", {})
        rel_path = snd_cfg.get(sound_name, "")
        if not rel_path:
            return
        abs_path = BASE_DIR / rel_path
        if not abs_path.exists():
            logger.warning("Sound file not found: %s (key: %s)", abs_path, sound_name)
            return

        volume = float(snd_cfg.get("volume", 0.7))

        import pygame  # type: ignore
        if not pygame.mixer.get_init():
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.init()

        # Reserve channel 1 exclusively for feedback sounds
        pygame.mixer.set_num_channels(max(8, pygame.mixer.get_num_channels()))
        _sound_channel = pygame.mixer.Channel(1)

        sound = pygame.mixer.Sound(str(abs_path))
        sound.set_volume(max(0.0, min(1.0, volume)))
        _sound_channel.play(sound)

        logger.debug("Playing sound: %s (%.0f%% volume)", sound_name, volume * 100)
    except Exception as e:
        logger.warning("play_sound(%s) failed: %s", sound_name, e)


# ---------------------------------------------------------------------------
# Safe JSON helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Any:
    """Read JSON, auto-restoring from .bak on corruption."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, ValueError):
        bak = path.with_suffix(".bak")
        if bak.exists():
            logger.warning("JSON corrupt at %s — restoring from backup.", path)
            shutil.copy(bak, path)
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        raise


def _write_json(path: Path, data: Any) -> None:
    """Write JSON safely: backup first, then write atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    bak = path.with_suffix(".bak")
    if path.exists():
        shutil.copy(path, bak)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    tmp.replace(path)
    # Also copy to backups/
    backup_dir = BASE_DIR / PATHS.get("backups", "backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(path, backup_dir / path.name)
    logger.debug("Wrote %s and backed up.", path.name)


# ---------------------------------------------------------------------------
# 1. PC CONTROL  +  App index (discovers every installed app on the device)
# ---------------------------------------------------------------------------

_APP_INDEX: dict[str, str] | None = None          # {lowercase_name: path}
_APP_INDEX_PATH = BASE_DIR / "data" / "apps_cache.json"
_APP_INDEX_MAX_AGE_HOURS = 24


def build_app_index() -> dict[str, str]:
    """
    Scan all Windows Start Menu folders for .lnk shortcuts.
    Also scans Program Files and AppData/Local for bare .exe files.
    Returns {lowercase_display_name: path_to_launch}.
    """
    index: dict[str, str] = {}

    # ── Start Menu (covers virtually every installed app) ────────────────
    start_dirs = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", ""))
            / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for d in start_dirs:
        if not d.exists():
            continue
        for lnk in d.rglob("*.lnk"):
            name = lnk.stem.lower().strip()
            if name and name not in index:
                index[name] = str(lnk)

    # ── Common install dirs (pick up apps without Start Menu shortcuts) ──
    exe_dirs = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs",
    ]
    for d in exe_dirs:
        if not d.exists():
            continue
        try:
            for exe in d.rglob("*.exe"):
                name = exe.stem.lower().strip()
                if name and name not in index:
                    index[name] = str(exe)
        except PermissionError:
            pass

    logger.info("App index built: %d entries.", len(index))
    return index


def _save_app_index(index: dict[str, str]) -> None:
    _APP_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_APP_INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump({"built": _now().isoformat(), "apps": index}, f)


def _load_app_index() -> dict[str, str] | None:
    try:
        with open(_APP_INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        built = datetime.fromisoformat(data["built"])
        age_h = (_now() - built).total_seconds() / 3600
        if age_h > _APP_INDEX_MAX_AGE_HOURS:
            return None
        return data["apps"]
    except Exception:
        return None


def get_app_index(force_rebuild: bool = False) -> dict[str, str]:
    global _APP_INDEX
    if not force_rebuild and _APP_INDEX:
        return _APP_INDEX
    cached = None if force_rebuild else _load_app_index()
    if cached:
        _APP_INDEX = cached
    else:
        _APP_INDEX = build_app_index()
        _save_app_index(_APP_INDEX)
    return _APP_INDEX


def refresh_app_index() -> str:
    """Force-rebuild the app index and save it."""
    idx = get_app_index(force_rebuild=True)
    return f"App list refreshed. I now know {len(idx)} apps on this device."


def _fuzzy_find_app(name: str, index: dict[str, str]) -> tuple[str, str] | None:
    """
    Find the best matching app in the index.
    Returns (matched_name, path) or None.
    """
    import difflib
    name_l = name.lower().strip()

    # 1. Exact
    if name_l in index:
        return name_l, index[name_l]

    # 2. Index key starts with query or query starts with key
    for key, path in index.items():
        if key.startswith(name_l) or name_l.startswith(key):
            return key, path

    # 3. Query is contained in a key (e.g. "chrome" in "google chrome")
    for key, path in index.items():
        if name_l in key:
            return key, path

    # 4. Fuzzy — difflib best match (threshold 0.6)
    matches = difflib.get_close_matches(name_l, index.keys(), n=1, cutoff=0.6)
    if matches:
        return matches[0], index[matches[0]]

    return None


# Explicit name → executable mappings checked before any search.
# Values are tried in order; first one that exists wins.
_APP_MAP: dict[str, list[str]] = {
    "notion": [
        r"%LOCALAPPDATA%\Programs\Notion\Notion.exe",
        r"%LOCALAPPDATA%\Notion\Notion.exe",
        "Notion.exe",
    ],
    "onenote": [
        r"C:\Program Files\Microsoft Office\root\Office16\ONENOTE.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\ONENOTE.EXE",
        r"C:\Program Files\Microsoft Office\Office16\ONENOTE.EXE",
        "ONENOTE.EXE",
    ],
    "notepad++": [
        r"C:\Program Files\Notepad++\notepad++.exe",
        r"C:\Program Files (x86)\Notepad++\notepad++.exe",
        "notepad++.exe",
    ],
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "chrome": [
        r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        "chrome.exe",
    ],
    "firefox": [
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        "firefox.exe",
    ],
    "edge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "msedge.exe",
    ],
    "vscode": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        "Code.exe",
    ],
    "code": [
        r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
        "Code.exe",
    ],
    "spotify": [
        r"%APPDATA%\Spotify\Spotify.exe",
        "Spotify.exe",
    ],
    "discord": [
        r"%LOCALAPPDATA%\Discord\Update.exe",
        "Discord.exe",
    ],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "task manager": ["taskmgr.exe"],
    "settings": ["ms-settings:"],
    "paint": ["mspaint.exe"],
    "word": [
        r"C:\Program Files\Microsoft Office\root\Office16\WINWORD.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\WINWORD.EXE",
        "WINWORD.EXE",
    ],
    "excel": [
        r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        "EXCEL.EXE",
    ],
    "powerpoint": [
        r"C:\Program Files\Microsoft Office\root\Office16\POWERPNT.EXE",
        "POWERPNT.EXE",
    ],
    "teams": [
        r"%LOCALAPPDATA%\Microsoft\Teams\Update.exe",
        "Teams.exe",
    ],
    "zoom": [
        r"%APPDATA%\Zoom\bin\Zoom.exe",
        "Zoom.exe",
    ],
    "whatsapp": [
        r"%LOCALAPPDATA%\WhatsApp\WhatsApp.exe",
        "WhatsApp.exe",
    ],
    "telegram": [
        r"%APPDATA%\Telegram Desktop\Telegram.exe",
        "Telegram.exe",
    ],
    "obs": [
        r"C:\Program Files\obs-studio\bin\64bit\obs64.exe",
        "obs64.exe",
    ],
}


def _resolve_app_map(key: str) -> str | None:
    """Try each candidate path for a known app name. Returns exe path or None."""
    for candidate in _APP_MAP.get(key, []):
        expanded = os.path.expandvars(candidate)
        # Bare exe name → try shell launch directly
        if expanded == candidate and not os.path.isabs(expanded):
            return expanded
        if os.path.isfile(expanded):
            return expanded
    return None


def _launch_exe(exe: str, display_name: str) -> str:
    """Launch an exe path or bare command. Returns result string."""
    try:
        if exe.startswith("ms-"):
            subprocess.Popen(["start", exe], shell=True)
        else:
            subprocess.Popen([exe])
        return f"Opening {display_name}."
    except Exception as e:
        return f"Found {display_name} but couldn't launch it: {e}"


def open_app_or_site(target: str) -> str:
    """Open an app by name or a site by URL/quick-link name."""
    tlow = target.lower().strip()

    # 1. User-defined quick links (highest priority)
    import webbrowser as _wb
    for _cfg_key in ("sites", "memory"):
        try:
            data = _read_json(_p(_cfg_key))
            for name, url in data.get("quick_links", {}).items():
                if tlow in name.lower() or name.lower() in tlow:
                    _wb.open(url)
                    return f"Opened {name}."
        except Exception:
            pass

    # 2. Explicit app map (hardcoded paths — fast and reliable)
    exe = _resolve_app_map(tlow)
    if exe:
        return _launch_exe(exe, target)

    for key in _APP_MAP:
        if tlow in key or key in tlow:
            exe = _resolve_app_map(key)
            if exe:
                return _launch_exe(exe, key)

    # 3. Full device app index (Start Menu + Program Files scan)
    try:
        idx = get_app_index()
        match = _fuzzy_find_app(tlow, idx)
        if match:
            matched_name, path = match
            return _launch_exe(path, matched_name)
    except Exception as e:
        logger.warning("App index lookup failed: %s", e)

    # 4. If it looks like a URL, open directly
    if target.startswith("http://") or target.startswith("https://") or "." in target:
        import webbrowser
        url = target if "://" in target else f"https://{target}"
        webbrowser.open(url)
        return f"Opened {target}."

    # 5. Try launching directly as a process (bare name)
    try:
        subprocess.Popen([target], shell=True)
        return f"Launched {target}."
    except Exception:
        pass

    # 6. Search Windows registry
    exe = _search_registry(target)
    if exe:
        result = _launch_exe(exe, target)
        if "couldn't" not in result:
            return result

    # 7. Search common install paths
    exe = _search_common_paths(target)
    if exe:
        return _launch_exe(exe, target)

    return f"I couldn't find {target}. Is it installed?"


def _search_registry(app_name: str) -> str | None:
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ]
    for hive, subkey in keys:
        try:
            with winreg.OpenKey(hive, subkey) as root:
                i = 0
                while True:
                    try:
                        name = winreg.EnumKey(root, i)
                        if app_name.lower() in name.lower():
                            with winreg.OpenKey(root, name) as k:
                                val, _ = winreg.QueryValueEx(k, "")
                                return val
                        i += 1
                    except OSError:
                        break
        except Exception:
            pass
    return None


def _search_common_paths(app_name: str) -> str | None:
    user = os.environ.get("USERNAME", "user")
    dirs = [
        Path("C:/Program Files"),
        Path("C:/Program Files (x86)"),
        Path(f"C:/Users/{user}/AppData/Local"),
    ]
    for d in dirs:
        if not d.exists():
            continue
        for exe in d.rglob("*.exe"):
            if app_name.lower() in exe.stem.lower():
                return str(exe)
    return None


# ---------------------------------------------------------------------------
# 2. STUDY MODE  +  Background sound
# ---------------------------------------------------------------------------

_HOSTS_PATH  = Path(r"C:\Windows\System32\drivers\etc\hosts")
_REDIRECT_IP = "127.0.0.1"


def _request_elevation_for_site_blocking() -> str:
    """
    Re-launch Jarvis with administrator rights so the hosts file can be edited.
    Shows a Windows UAC prompt. Returns a message to speak while waiting.
    """
    try:
        import ctypes, sys
        logger.info("Requesting UAC elevation for site blocking.")
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas",
            sys.executable,
            " ".join(f'"{a}"' for a in sys.argv),
            None, 1,
        )
        return (
            "I need administrator rights to block websites. "
            "Please accept the Windows prompt that just appeared. "
            "Jarvis will restart with the right permissions."
        )
    except Exception as e:
        return (
            f"I couldn't request administrator rights: {e}. "
            "Right-click tray_icon.py and choose Run as administrator."
        )

# ── Sound state ─────────────────────────────────────────────────────────────
_current_sound: str | None = None
_sound_thread: threading.Thread | None = None
_sound_stop_event = threading.Event()

VALID_SOUNDS = ("lofi", "rain", "white_noise", "none")


def _sound_cfg() -> dict:
    return CFG.get("study_mode", {})


def _resolve_sound_path(name: str) -> Path | None:
    """Return the absolute path to a sound file, trying .mp3 then .wav."""
    sound_dir = BASE_DIR / _sound_cfg().get("sound_path", "assets/sounds/")
    for ext in (".mp3", ".wav"):
        candidate = sound_dir / f"{name}{ext}"
        if candidate.exists():
            return candidate
    return None


def _pygame_play_loop(path: Path, volume: float, stop_event: threading.Event) -> None:
    """Background thread: loads and loops a sound file via pygame."""
    try:
        import pygame  # type: ignore
        pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=1024)
        pygame.mixer.init()
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.set_volume(max(0.0, min(1.0, volume)))
        pygame.mixer.music.play(loops=-1)
        logger.info("Background sound started: %s (vol=%.2f)", path.name, volume)
        while not stop_event.is_set():
            import time
            time.sleep(0.5)
        pygame.mixer.music.stop()
        pygame.mixer.quit()
        logger.info("Background sound stopped.")
    except ImportError:
        logger.warning("pygame not installed — background sound unavailable.")
    except Exception as e:
        logger.error("Sound playback error: %s", e)


def start_background_sound(name: str | None = None) -> str:
    """
    Start looping background sound in a daemon thread.
    name: lofi | rain | white_noise | none (or None to use config default).
    """
    global _current_sound, _sound_thread, _sound_stop_event

    if name is None:
        name = _sound_cfg().get("background_sound", "lofi")

    name = name.lower().replace(" ", "_")

    if name == "none":
        return stop_background_sound()

    if name not in VALID_SOUNDS:
        return f"Unknown sound '{name}'. Choose: {', '.join(s for s in VALID_SOUNDS if s != 'none')}."

    # Stop any currently playing sound first
    if _sound_thread and _sound_thread.is_alive():
        _sound_stop_event.set()
        _sound_thread.join(timeout=3)

    sound_path = _resolve_sound_path(name)
    if not sound_path:
        return (
            f"Sound file for '{name}' not found in {_sound_cfg().get('sound_path', 'assets/sounds/')}. "
            f"Add {name}.mp3 or {name}.wav to that folder."
        )

    volume = float(_sound_cfg().get("volume", 0.4))
    _sound_stop_event = threading.Event()
    _current_sound = name

    _sound_thread = threading.Thread(
        target=_pygame_play_loop,
        args=(sound_path, volume, _sound_stop_event),
        daemon=True,
        name="BackgroundSound",
    )
    _sound_thread.start()
    return f"Playing {name.replace('_', ' ')} sounds."


def stop_background_sound() -> str:
    """Stop background sound if playing."""
    global _current_sound
    if _sound_thread and _sound_thread.is_alive():
        _sound_stop_event.set()
        _sound_thread.join(timeout=3)
    _current_sound = None
    return "Background sound stopped."


def switch_sound(name: str) -> str:
    """Change background sound mid-session."""
    return start_background_sound(name)


def get_current_sound() -> str:
    """Return the name of the currently playing sound."""
    if _current_sound and _sound_thread and _sound_thread.is_alive():
        return f"Playing {_current_sound.replace('_', ' ')} sounds."
    return "No background sound is playing."


# ── Study mode ───────────────────────────────────────────────────────────────

def start_study_mode(subject: str = "") -> str:
    """Open study apps, study sites, block distracting sites, start Pomodoro, play sound."""
    results = []

    # Start study session tracker
    if subject:
        try:
            from study_tracker import start_session
            results.append(start_session(subject))
        except Exception:
            pass

    # Open study apps
    try:
        mem = _read_json(_p("memory"))
        for app in mem.get("study_apps", []):
            open_app_or_site(app)
        results.append(f"Opened {len(mem.get('study_apps', []))} study apps.")
    except Exception as e:
        results.append(f"Could not open study apps: {e}")

    # Open study sites
    try:
        sites = _read_json(_p("sites"))
        import webbrowser
        for site in sites.get("study", []):
            webbrowser.open(f"https://{site}")
        results.append(f"Opened {len(sites.get('study', []))} study sites.")
    except Exception as e:
        results.append(f"Could not open study sites: {e}")

    # Block distracting sites (requires confirm before calling)
    block_result = _block_sites()
    results.append(block_result)

    # Background sound
    sound_result = start_background_sound()
    results.append(sound_result)

    # Pomodoro
    pom_result = start_pomodoro()
    results.append(pom_result)

    return " ".join(results)


def end_study_mode() -> str:
    """Unblock distracting sites, stop background sound, and stop Pomodoro."""
    stop_pomodoro()
    sound_msg = stop_background_sound()
    unblock_msg = _unblock_sites()
    return f"{unblock_msg} {sound_msg}"


# ---------------------------------------------------------------------------
# Pomodoro timer
# ---------------------------------------------------------------------------

# ── Speak injection ──────────────────────────────────────────────────────────
_pom_speak_fn = None   # injected at runtime by jarvis.py / tray_icon.py


def set_pomodoro_speak(fn) -> None:
    global _pom_speak_fn
    _pom_speak_fn = fn


def _pom_say(text: str) -> None:
    logger.info("Pomodoro: %s", text)
    if _pom_speak_fn:
        _pom_speak_fn(text)


# ── Session-RAM state (never saved to disk) ──────────────────────────────────
_pom_state: str = "idle"          # idle | work | break | long_break
_pom_cycle_in_set: int = 0        # cycles completed since last long break
_pom_total_today: int = 0         # total work cycles this session
_pom_end_time: datetime | None = None
_pom_thread: threading.Thread | None = None
_pom_stop_event: threading.Event = threading.Event()
_pom_skip_event: threading.Event = threading.Event()
_pom_lock: threading.Lock = threading.Lock()


def _pom_cfg() -> dict:
    return CFG.get("pomodoro", {})


def _wait_interruptible(
    end_time: datetime,
    stop_event: threading.Event,
    skip_event: threading.Event | None = None,
    poll: float = 0.25,
) -> str:
    """
    Block until end_time is reached.
    Returns:
        "done"   — timer expired normally
        "stop"   — stop_event fired
        "skip"   — skip_event fired (breaks only)
    """
    while True:
        remaining = (end_time - _now()).total_seconds()
        if remaining <= 0:
            return "done"
        if stop_event.is_set():
            return "stop"
        if skip_event and skip_event.is_set():
            return "skip"
        time.sleep(min(poll, remaining))


def _pomodoro_run(work_min: float, break_min: float, long_break_min: float,
                  cycles_before_long: int) -> None:
    """Main Pomodoro state-machine — runs in a daemon thread."""
    global _pom_state, _pom_cycle_in_set, _pom_total_today, _pom_end_time

    _pom_stop_event.clear()
    _pom_skip_event.clear()

    sound_on_end = _pom_cfg().get("sound_on_end", True)

    while not _pom_stop_event.is_set():

        # ── WORK phase ────────────────────────────────────────────────────
        with _pom_lock:
            _pom_state = "work"
            _pom_end_time = _now() + timedelta(minutes=work_min)

        outcome = _wait_interruptible(_pom_end_time, _pom_stop_event)

        if outcome == "stop":
            break

        # Work finished — update counters
        with _pom_lock:
            _pom_cycle_in_set += 1
            _pom_total_today += 1
            cycles_done = _pom_cycle_in_set

        # ── Choose break type ─────────────────────────────────────────────
        if cycles_done >= cycles_before_long:
            phase = "long_break"
            b_min = long_break_min
            work_msg = (
                f"Great work — {cycles_before_long} cycles done. "
                f"Take a {int(long_break_min)} minute break."
            )
            with _pom_lock:
                _pom_cycle_in_set = 0
        else:
            phase = "break"
            b_min = break_min
            work_msg = (
                f"{int(work_min)} minutes up. "
                f"Take a {int(break_min)} minute break."
            )

        if sound_on_end:
            play_sound("done_chime")
            _pom_say(work_msg)

        # ── BREAK phase ───────────────────────────────────────────────────
        with _pom_lock:
            _pom_state = phase
            _pom_end_time = _now() + timedelta(minutes=b_min)

        outcome = _wait_interruptible(
            _pom_end_time, _pom_stop_event, _pom_skip_event
        )
        _pom_skip_event.clear()

        if outcome == "stop":
            break

        if sound_on_end:
            play_sound("done_chime")
            _pom_say("Break over. Back to work.")

    with _pom_lock:
        _pom_state = "idle"
        _pom_end_time = None

    logger.info("Pomodoro session ended. Total cycles today: %d", _pom_total_today)


def start_pomodoro(work_minutes: float | None = None) -> str:
    """Start the Pomodoro timer. Stops any running session first."""
    global _pom_thread

    cfg = _pom_cfg()
    work_min       = work_minutes if work_minutes is not None else float(cfg.get("work_minutes", 25))
    break_min      = float(cfg.get("break_minutes", 5))
    long_break_min = float(cfg.get("long_break_minutes", 15))
    cycles_before  = int(cfg.get("cycles_before_long_break", 4))

    # Stop any running session cleanly
    if _pom_thread and _pom_thread.is_alive():
        _pom_stop_event.set()
        _pom_thread.join(timeout=2)

    _pom_stop_event.clear()
    _pom_skip_event.clear()

    _pom_thread = threading.Thread(
        target=_pomodoro_run,
        args=(work_min, break_min, long_break_min, cycles_before),
        daemon=True,
        name="PomodoroTimer",
    )
    _pom_thread.start()
    logger.info("Pomodoro started: %.0f min work / %.0f min break.", work_min, break_min)
    return f"Pomodoro started. {int(work_min)} minutes of focus."


def stop_pomodoro() -> str:
    """Cancel the running Pomodoro session."""
    global _pom_state, _pom_end_time
    if _pom_thread and _pom_thread.is_alive():
        _pom_stop_event.set()
        _pom_thread.join(timeout=2)
    with _pom_lock:
        _pom_state = "idle"
        _pom_end_time = None
    logger.info("Pomodoro stopped.")
    return "Pomodoro stopped."


def pomodoro_skip_break() -> str:
    """Skip the current break and jump to the next work session."""
    with _pom_lock:
        state = _pom_state
    if state not in ("break", "long_break"):
        return "No break to skip — Pomodoro is not in a break phase."
    _pom_skip_event.set()
    return "Break skipped. Starting next work session."


def pomodoro_time_left() -> str:
    """Return a human-readable string of time remaining in the current phase."""
    with _pom_lock:
        state    = _pom_state
        end_time = _pom_end_time

    if state == "idle" or end_time is None:
        return "No Pomodoro running."

    remaining = (end_time - _now()).total_seconds()
    if remaining <= 0:
        return "Session ending now."

    mins = int(remaining // 60)
    secs = int(remaining % 60)
    label = {"work": "Work", "break": "Break", "long_break": "Long break"}.get(state, state)
    return f"{label} — {mins}:{secs:02d} remaining."


def pomodoro_count() -> str:
    """Return how many Pomodoro work cycles have been completed this session."""
    return (
        f"You've completed {_pom_total_today} Pomodoro"
        f"{'s' if _pom_total_today != 1 else ''} today."
    )


def get_pomodoro_status() -> str:
    """One-line status string for the tray UI."""
    with _pom_lock:
        state    = _pom_state
        end_time = _pom_end_time

    if state == "idle":
        return f"Pomodoro: idle  ({_pom_total_today} done today)"

    remaining = max(0, (end_time - _now()).total_seconds()) if end_time else 0
    mins = int(remaining // 60)
    secs = int(remaining % 60)
    label = {"work": "Work", "break": "Break", "long_break": "Long break"}.get(state, state)
    return f"Pomodoro: {label}  {mins}:{secs:02d} left  ({_pom_total_today} done)"


def _block_sites() -> str:
    try:
        sites = _read_json(_p("sites"))
        distracting = sites.get("distracting", [])
        existing = _HOSTS_PATH.read_text(encoding="utf-8")
        lines = existing.splitlines()
        added = 0
        for site in distracting:
            entry = f"{_REDIRECT_IP} {site}"
            www_entry = f"{_REDIRECT_IP} www.{site}"
            if entry not in existing:
                lines.append(entry)
                added += 1
            if www_entry not in existing:
                lines.append(www_entry)
        _HOSTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return f"Blocked {added} distracting sites."
    except PermissionError:
        return _request_elevation_for_site_blocking()
    except Exception as e:
        return f"Failed to block sites: {e}"


def _unblock_sites() -> str:
    try:
        sites = _read_json(_p("sites"))
        distracting = sites.get("distracting", [])
        existing = _HOSTS_PATH.read_text(encoding="utf-8")
        lines = [
            ln for ln in existing.splitlines()
            if not any(site in ln for site in distracting)
        ]
        _HOSTS_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "Unblocked all distracting sites."
    except PermissionError:
        return _request_elevation_for_site_blocking()
    except Exception as e:
        return f"Failed to unblock sites: {e}"


# ---------------------------------------------------------------------------
# 3. TASK LIST
# ---------------------------------------------------------------------------

_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2, None: 3, "": 3}

def add_task(title: str, deadline: str | None = None, priority: str | None = None) -> str:
    tasks = _read_json(_p("tasks"))
    new_id = str(max((int(t["id"]) for t in tasks), default=0) + 1)
    if priority:
        priority = priority.lower().strip()
        if priority not in ("high", "medium", "low"):
            priority = None
    task = {
        "id":         new_id,
        "title":      title,
        "deadline":   deadline,
        "priority":   priority,
        "done":       False,
        "created_at": _now().isoformat(),
    }
    tasks.append(task)
    _write_json(_p("tasks"), tasks)
    play_sound("done_chime")
    p_str  = f" [{priority} priority]" if priority else ""
    dl_str = f" (due {deadline})" if deadline else ""
    return f"Added task: {title}{p_str}{dl_str}."


def list_tasks(today_only: bool = False) -> str:
    tasks = _read_json(_p("tasks"))
    pending = [t for t in tasks if not t["done"]]
    if today_only:
        today = date.today().isoformat()
        pending = [t for t in pending
                   if t.get("deadline") and t["deadline"][:10] == today]
    if not pending:
        return "No pending tasks."
    pending.sort(key=lambda t: (
        _PRIORITY_ORDER.get(t.get("priority"), 3),
        t.get("deadline", "9999")
    ))
    lines = []
    for t in pending:
        p_tag = f"[{t['priority']}] " if t.get("priority") else ""
        dl = f" — due {t['deadline']}" if t.get("deadline") else ""
        lines.append(f"• {p_tag}{t['title']}{dl}")
    return "\n".join(lines)


def get_top_task() -> str:
    """Return the highest priority + soonest deadline pending task."""
    try:
        tasks = _read_json(_p("tasks"))
        pending = [t for t in tasks if not t.get("done")]
        if not pending:
            return "You have no pending tasks."
        pending.sort(key=lambda t: (
            _PRIORITY_ORDER.get(t.get("priority"), 3),
            t.get("deadline", "9999")
        ))
        top = pending[0]
        p_str  = f"{top['priority']} priority — " if top.get("priority") else ""
        dl_str = f", due {top['deadline'][:10]}" if top.get("deadline") else ""
        return f"Your most important task: {p_str}{top['title']}{dl_str}."
    except Exception as e:
        return f"Couldn't check tasks: {e}"


def update_task_priority(title_fragment: str, priority: str) -> str:
    """Change the priority of a task matching title_fragment."""
    priority = priority.lower().strip()
    if priority not in ("high", "medium", "low"):
        return f"Unknown priority '{priority}'. Use: high, medium, or low."
    tasks = _read_json(_p("tasks"))
    matched = [t for t in tasks if title_fragment.lower() in t["title"].lower() and not t.get("done")]
    if not matched:
        return f"No pending task matching '{title_fragment}'."
    matched[0]["priority"] = priority
    _write_json(_p("tasks"), tasks)
    return f"Updated '{matched[0]['title']}' to {priority} priority."


def mark_task_done(title_fragment: str) -> str:
    tasks = _read_json(_p("tasks"))
    matched = [t for t in tasks if title_fragment.lower() in t["title"].lower() and not t["done"]]
    if not matched:
        return f"No pending task matching '{title_fragment}'."
    matched[0]["done"] = True
    _write_json(_p("tasks"), tasks)
    play_sound("done_chime")
    return f"Marked done: {matched[0]['title']}."


def hours_until_deadline(title_fragment: str) -> str:
    tasks = _read_json(_p("tasks"))
    matched = [t for t in tasks if title_fragment.lower() in t["title"].lower()]
    if not matched or not matched[0].get("deadline"):
        return f"No deadline found for '{title_fragment}'."
    dl = datetime.fromisoformat(matched[0]["deadline"])
    diff = dl - _now()
    hours = max(0, int(diff.total_seconds() // 3600))
    mins  = max(0, int((diff.total_seconds() % 3600) // 60))
    return f"{hours}h {mins}m until '{matched[0]['title']}'."


# ---------------------------------------------------------------------------
# 4. PDF READER
# ---------------------------------------------------------------------------

def read_pdf(path: str, question: str | None = None) -> str:
    if CFG.get("low_power_mode") and not question:
        return "PDF tool skipped in low power mode. Ask explicitly to override."
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError:
        return "pypdf not installed. Run: pip install pypdf"

    path = path.strip().strip('"').strip("'")
    if not os.path.exists(path):
        return f"File not found: {path}"

    try:
        reader = PdfReader(path)
        text = "\n".join(
            page.extract_text() or "" for page in reader.pages
        ).strip()
        if not text:
            return "I couldn't read that PDF — it may be scanned or image-based."
        max_len = CFG.get("notes", {}).get("max_read_length", 500) * 6
        return text[:max_len]
    except Exception as e:
        logger.error("PDF read error: %s", e)
        return "I couldn't read that PDF — it may be scanned or unreadable."


# ---------------------------------------------------------------------------
# 5. SYSTEM INFO
# ---------------------------------------------------------------------------

def get_system_info(query: str = "all") -> str:
    q = query.lower()
    parts = []

    if "battery" in q or q == "all":
        bat = psutil.sensors_battery()
        if bat:
            status = "charging" if bat.power_plugged else "on battery"
            parts.append(f"Battery: {bat.percent:.0f}% ({status}).")
        else:
            parts.append("No battery detected (desktop).")

    if "cpu" in q or q == "all":
        cpu = psutil.cpu_percent(interval=0.5)
        parts.append(f"CPU: {cpu:.1f}%.")

    if "ram" in q or "memory" in q or q == "all":
        ram = psutil.virtual_memory()
        parts.append(f"RAM: {ram.percent:.1f}% used ({ram.used // 1024**3:.1f} GB / {ram.total // 1024**3:.1f} GB).")

    if "storage" in q or "disk" in q or q == "all":
        disk = psutil.disk_usage("/")
        free_gb = disk.free // 1024**3
        parts.append(f"Storage: {free_gb} GB free.")

    if "wifi" in q or "network" in q or q == "all":
        try:
            result = subprocess.run(
                ["netsh", "wlan", "show", "interfaces"],
                capture_output=True, text=True, timeout=5
            )
            ssid_match = re.search(r"SSID\s+:\s+(.+)", result.stdout)
            if ssid_match:
                parts.append(f"WiFi: {ssid_match.group(1).strip()}.")
            else:
                parts.append("WiFi: not connected.")
        except Exception:
            parts.append("WiFi: unable to check.")

    # Warn if CPU or RAM above 85%
    if psutil.cpu_percent(interval=0) > 85:
        logger.warning("High CPU usage detected.")
    if psutil.virtual_memory().percent > 85:
        logger.warning("High RAM usage detected.")

    return " ".join(parts) if parts else "Could not retrieve system info."


# ---------------------------------------------------------------------------
# 6. CALCULATOR
# ---------------------------------------------------------------------------

# Hardcoded exchange rates (USD base)
_FX_RATES = {
    "usd": 1.0, "eur": 0.92, "gbp": 0.79, "jpy": 149.5,
    "cad": 1.36, "aud": 1.52, "chf": 0.90, "inr": 83.1,
    "brl": 4.97, "mxn": 17.1,
}


def calculate(expression: str) -> str:
    expr = expression.strip().lower()

    # Currency conversion: "100 usd to eur"
    fx_match = re.match(r"([\d.]+)\s*([a-z]{3})\s+(?:to|in)\s+([a-z]{3})", expr)
    if fx_match:
        amount = float(fx_match.group(1))
        from_c = fx_match.group(2)
        to_c   = fx_match.group(3)
        if from_c in _FX_RATES and to_c in _FX_RATES:
            result = amount / _FX_RATES[from_c] * _FX_RATES[to_c]
            return f"{amount:.2f} {from_c.upper()} = {result:.2f} {to_c.upper()}"
        return "Unknown currency code."

    # Days until date: "days until 2025-12-25"
    date_match = re.search(r"days?\s+until\s+(\d{4}-\d{2}-\d{2})", expr)
    if date_match:
        target = date.fromisoformat(date_match.group(1))
        delta = (target - date.today()).days
        return f"{delta} days until {date_match.group(1)}."

    # Percentage: "20% of 150"
    pct_match = re.match(r"([\d.]+)%\s+of\s+([\d.]+)", expr)
    if pct_match:
        result = float(pct_match.group(1)) / 100 * float(pct_match.group(2))
        return f"{result:.1f}"

    # General math (safe eval)
    safe_expr = re.sub(r"[^0-9+\-*/().\s%]", "", expression)
    try:
        result = eval(safe_expr, {"__builtins__": {}}, {"sqrt": math.sqrt, "pi": math.pi})
        return str(round(result, 6))
    except Exception:
        return "I couldn't evaluate that expression."


# ---------------------------------------------------------------------------
# 7. CLIPBOARD EXPLAINER
# ---------------------------------------------------------------------------

def explain_clipboard(llm_caller=None) -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["powershell", "-Command", "Get-Clipboard"],
            capture_output=True, text=True, timeout=5
        )
        text = result.stdout.strip()
    except Exception as e:
        return f"Couldn't read clipboard: {e}"

    if not text:
        return "Clipboard is empty."

    if llm_caller:
        prompt = f"Explain this in simple terms:\n\n{text[:2000]}"
        return llm_caller(prompt)
    return f"Clipboard contents:\n{text[:500]}"


# ---------------------------------------------------------------------------
# 8. BRIEFING ENGINE
# ---------------------------------------------------------------------------

def morning_briefing() -> str:
    lines = ["Good morning! Here's your briefing."]

    # Top 3 tasks — sorted by priority then deadline
    try:
        tasks = _read_json(_p("tasks"))
        pending = [t for t in tasks if not t["done"]]
        pending.sort(key=lambda t: (
            _PRIORITY_ORDER.get(t.get("priority"), 3),
            t.get("deadline", "9999")
        ))
        top3 = pending[:3]
        if top3:
            # Call out the top priority task explicitly
            top = top3[0]
            if top.get("priority") == "high":
                lines.append(f"Your top priority today is: {top['title']}.")
                rest = top3[1:]
            else:
                rest = top3
            if rest:
                lines.append("Also pending: " + "; ".join(t["title"] for t in rest) + ".")
    except Exception:
        pass

    # Deadlines today or tomorrow — with related notes reminder
    try:
        today = date.today()
        tomorrow = today + timedelta(days=1)
        tasks = _read_json(_p("tasks"))
        due_soon = [
            t for t in tasks
            if not t["done"] and t.get("deadline")
            and date.fromisoformat(t["deadline"][:10]) in (today, tomorrow)
        ]
        if due_soon:
            lines.append("Due soon: " + "; ".join(t["title"] for t in due_soon) + ".")
            # Related notes nudge
            for task in due_soon:
                related = check_related_notes(task["title"])
                if related:
                    lines.append(
                        f"You have {len(related)} note{'s' if len(related) != 1 else ''} "
                        f"related to '{task['title']}'."
                    )
    except Exception:
        pass

    # Outfit suggestion (if stylist enabled in config)
    if CFG.get("stylist", {}).get("suggest_in_briefing", True):
        try:
            from closet_tool import suggest_daily
            outfit = suggest_daily()
            if outfit and "empty" not in outfit.lower():
                lines.append(f"Outfit suggestion: {outfit}")
        except Exception:
            pass

    # Budget warning (if enabled in config)
    if CFG.get("budget", {}).get("track_in_briefing", True):
        try:
            from budget_tool import budget_briefing_check
            budget_warn = budget_briefing_check()
            if budget_warn:
                lines.append(budget_warn)
        except Exception:
            pass

    # Expiring food
    expiry_warning = _check_expiry()
    if expiry_warning:
        lines.append(expiry_warning)

    # Recipe suggestion
    recipe = suggest_recipe()
    if recipe:
        lines.append(f"Recipe idea: {recipe}")

    # Wellbeing nudge
    try:
        routines = _read_json(_p("routines"))
        habits = routines.get("habits", [])
        if habits:
            lines.append(f"Daily habits: {', '.join(habits)}.")
    except Exception:
        pass

    # Goals progress
    try:
        goals = _read_json(_p("goals"))
        lt = goals.get("long_term", [])
        st = goals.get("short_term", [])
        all_goals = lt + st
        if all_goals:
            g = all_goals[0]
            lines.append(f"Goal — {g['goal']}: {g.get('progress', 0)}% progress.")
    except Exception:
        pass

    # Open follow-ups
    try:
        fups = _read_json(_p("followups"))
        open_fups = [f for f in fups if not f.get("done")]
        if open_fups:
            lines.append(f"You have {len(open_fups)} open follow-up(s).")
    except Exception:
        pass

    # Wellbeing nudge if low mood 3+ days
    try:
        wb = _read_json(_p("wellbeing"))
        recent = wb[-7:] if len(wb) >= 7 else wb
        low_days = sum(1 for e in recent if e.get("mood", "").lower() in ("low", "bad", "tired"))
        if low_days >= 3:
            lines.append("You've had a tough few days — remember to take breaks and be kind to yourself.")
    except Exception:
        pass

    # Exercise streak check
    try:
        wb = _read_json(_p("wellbeing"))
        three_ago = (date.today() - timedelta(days=3)).isoformat()
        recent_3 = [e for e in wb if e.get("date", "") >= three_ago]
        exercise_days = sum(1 for e in recent_3 if e.get("exercise", "").strip())
        if exercise_days == 0:
            lines.append("You haven't logged exercise in 3 days.")
    except Exception:
        pass

    # Hydration check from yesterday
    try:
        wb = _read_json(_p("wellbeing"))
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        yest = next((e for e in wb if e.get("date") == yesterday), None)
        if yest:
            hydration = float(yest.get("hydration_L", 0))
            if 0 < hydration < 1.5:
                lines.append(
                    f"You only logged {hydration} litre{'s' if hydration != 1 else ''} "
                    f"of water yesterday. Try to drink more today."
                )
    except Exception:
        pass

    return "\n".join(lines)


def evening_checkin() -> str:
    """Expanded evening check-in covering tasks, fridge, budget, water, schedule, reminders."""
    try:
        mem  = _read_json(_p("memory"))
        name = mem.get("name", "Samaira").split()[0]
    except Exception:
        name = "Samaira"

    lines = [f"Evening check-in, {name}."]
    today = date.today().isoformat()

    # 1. Tasks completed today
    try:
        tasks = _read_json(_p("tasks"))
        done_today = [t for t in tasks if t.get("done") and
                      (t.get("created_at", "") or "")[:10] == today]
        if done_today:
            titles = ", ".join(t["title"] for t in done_today[:3])
            lines.append(
                f"You completed {len(done_today)} task{'s' if len(done_today) > 1 else ''} "
                f"today: {titles}."
            )
        else:
            lines.append("No tasks completed today. Tomorrow's a new day.")

        # First pending task
        pending = [t for t in tasks if not t.get("done")]
        pending.sort(key=lambda t: (
            {"high": 0, "medium": 1, "low": 2}.get(t.get("priority", "medium"), 1),
            t.get("deadline", "9999")
        ))
        if pending:
            lines.append(f"Your first task tomorrow: {pending[0]['title']}.")
    except Exception:
        pass

    # 2. Fridge expiring tomorrow
    expiry = _check_expiry(days=1)
    if expiry:
        lines.append(expiry)

    # 3. Budget today
    try:
        from budget_tool import today_spending
        spent = today_spending()
        if "No spending" not in spent:
            lines.append(spent.split("\n")[0])   # first line summary
    except Exception:
        pass

    # 4. Water today
    try:
        wb    = _read_json(_p("wellbeing"))
        entry = next((e for e in wb if e.get("date") == today), {})
        water = float(entry.get("hydration_L", 0) or 0)
        if water < 1.5:
            lines.append(
                f"You logged {water}L of water today. "
                f"Try to drink a glass before bed."
            )
    except Exception:
        pass

    # 5. Tomorrow's first class
    try:
        sched = _read_json(BASE_DIR / "data" / "schedule.json")
        tomorrow = (date.today() + timedelta(days=1)).strftime("%A").lower()
        tomorrow_classes = sorted(
            [c for c in sched.get("classes", [])
             if tomorrow in [d.lower() for d in c.get("days", [])]],
            key=lambda c: c.get("time", "")
        )
        if tomorrow_classes:
            first = tomorrow_classes[0]
            lines.append(
                f"Tomorrow your first class is {first.get('name', '?')} "
                f"at {first.get('time', '?')}."
            )
    except Exception:
        pass

    # 6. Tomorrow's reminders
    try:
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        rems = _read_json(_p("reminders"))
        tmrw_rems = [r for r in rems if not r.get("done") and
                     r.get("trigger_at", "")[:10] == tomorrow]
        if tmrw_rems:
            lines.append(
                f"You have {len(tmrw_rems)} reminder{'s' if len(tmrw_rems) > 1 else ''} "
                f"for tomorrow."
            )
    except Exception:
        pass

    # 7. Journal prompt
    try:
        cfg = CFG.get("journal", {})
        if cfg.get("prompt_if_missed", True):
            from journal_tool import JOURNAL_DIR
            today_file = JOURNAL_DIR / f"{today}.md"
            if not today_file.exists():
                lines.append("You haven't journaled today. Want to add a quick entry?")
    except Exception:
        pass

    return " ".join(lines)


def weekly_review() -> str:
    lines = ["Weekly review."]

    # Goals progress
    try:
        progress = _read_json(_p("progress"))
        goals = progress.get("goals", [])
        improved = 0
        for g in goals:
            snaps = g.get("snapshots", [])
            if len(snaps) >= 2:
                delta = snaps[-1]["progress_percent"] - snaps[-2]["progress_percent"]
                if delta > 0:
                    improved += 1
                lines.append(f"{g['goal']}: {snaps[-1]['progress_percent']}% (+{delta}% this week).")
        lines.append(f"Progress on {improved} of {len(goals)} goals this week.")
    except Exception:
        pass

    # Tasks summary
    try:
        tasks = _read_json(_p("tasks"))
        done = [t for t in tasks if t.get("done")]
        pending = [t for t in tasks if not t.get("done")]
        lines.append(f"Tasks: {len(done)} completed, {len(pending)} still pending.")
    except Exception:
        pass

    # Grocery list
    try:
        fridge = _read_json(_p("fridge"))
        grocery = fridge.get("grocery_list", [])
        if grocery:
            joined = ", ".join(grocery)
            lines.append(
                f"You have {len(grocery)} item{'s' if len(grocery) != 1 else ''} "
                f"on your grocery list: {joined}."
            )
        else:
            lines.append("Your grocery list is clear.")
    except Exception:
        pass

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 9. FRIDGE MANAGER
# ---------------------------------------------------------------------------

def _check_expiry(days: int | None = None) -> str:
    if days is None:
        days = CFG.get("expiry_warning_days", 2)
    try:
        fridge = _read_json(_p("fridge"))
        cutoff = date.today() + timedelta(days=days)
        expiring = [
            i for i in fridge.get("items", [])
            if i.get("expires") and date.fromisoformat(i["expires"]) <= cutoff
        ]
        expiring.sort(key=lambda i: i["expires"])
        if expiring:
            items_str = ", ".join(f"{i['name']} (expires {i['expires']})" for i in expiring)
            return f"Expiring soon: {items_str}."
    except Exception:
        pass
    return ""


def fridge_list() -> str:
    try:
        fridge = _read_json(_p("fridge"))
        items = fridge.get("items", [])
        if not items:
            return "Your fridge is empty."
        lines = []
        for i in items:
            exp = f", expires {i['expires']}" if i.get("expires") else ""
            lines.append(f"• {i['name']} — {i.get('quantity', '?')}{exp}")
        return "\n".join(lines)
    except Exception as e:
        return f"Couldn't read fridge: {e}"


def fridge_expiry_check() -> str:
    result = _check_expiry(days=3)
    return result or "Nothing expiring in the next 3 days."


def fridge_add(name: str, quantity: str = "1", expires: str | None = None) -> str:
    fridge = _read_json(_p("fridge"))
    fridge["items"].append({"name": name, "quantity": quantity, "expires": expires})
    fridge["last_updated"] = date.today().isoformat()
    _write_json(_p("fridge"), fridge)
    return f"Added {name} to fridge."


def fridge_remove(name: str) -> str:
    fridge = _read_json(_p("fridge"))
    before = len(fridge["items"])
    fridge["items"] = [i for i in fridge["items"] if i["name"].lower() != name.lower()]
    if len(fridge["items"]) == before:
        return f"'{name}' not found in fridge."
    fridge["last_updated"] = date.today().isoformat()
    _write_json(_p("fridge"), fridge)
    return f"Removed {name} from fridge."


def grocery_add(item: str) -> str:
    fridge = _read_json(_p("fridge"))
    if item not in fridge.get("grocery_list", []):
        fridge.setdefault("grocery_list", []).append(item)
        _write_json(_p("fridge"), fridge)
    return f"Added {item} to grocery list."


def grocery_list_read() -> str:
    """Read the grocery list aloud."""
    try:
        fridge = _read_json(_p("fridge"))
        items = fridge.get("grocery_list", [])
        if not items:
            return "Your grocery list is clear."
        count = len(items)
        joined = ", ".join(items)
        return f"You have {count} item{'s' if count != 1 else ''} on your grocery list: {joined}."
    except Exception as e:
        return f"Couldn't read grocery list: {e}"


def grocery_clear() -> str:
    """Empty the grocery list."""
    fridge = _read_json(_p("fridge"))
    fridge["grocery_list"] = []
    _write_json(_p("fridge"), fridge)
    return "Grocery list cleared."


def grocery_remove_item(item: str) -> str:
    """Remove a specific item from the grocery list."""
    fridge = _read_json(_p("fridge"))
    original = fridge.get("grocery_list", [])
    updated = [i for i in original if i.lower() != item.lower()]
    if len(updated) == len(original):
        return f"'{item}' wasn't on your grocery list."
    fridge["grocery_list"] = updated
    _write_json(_p("fridge"), fridge)
    return f"Removed {item} from grocery list."


# ---------------------------------------------------------------------------
# 10. RECIPES  +  Missing ingredient checker
# ---------------------------------------------------------------------------

# Stores missing ingredients from the last recipe suggestion so the
# confirmation flow can add them all at once.
_last_missing_ingredients: list[str] = []


def _fridge_item_names() -> set[str]:
    """Return a lowercase set of all item names currently in the fridge."""
    try:
        fridge = _read_json(_p("fridge"))
        return {i["name"].lower() for i in fridge.get("items", [])}
    except Exception:
        return set()


def _parse_ingredients(text: str, llm_caller) -> list[str]:
    """
    Ask the LLM to extract ingredient names from a recipe text.
    Returns a list of lowercase ingredient name strings.
    """
    try:
        raw = llm_caller(
            f"Extract only the ingredient names from this recipe as a JSON array of strings. "
            f"No quantities, no measurements — just the ingredient names. "
            f'Example output: ["eggs", "milk", "flour"]\n\nRecipe:\n{text}'
        )
        raw = raw.strip()
        # Find the JSON array in the response
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start != -1 and end > start:
            import json as _json
            items = _json.loads(raw[start:end])
            return [str(i).lower().strip() for i in items if i]
    except Exception as e:
        logger.warning("Ingredient parse failed: %s", e)
    return []


def _find_missing(ingredients: list[str]) -> list[str]:
    """Return ingredients not currently in the fridge."""
    have = _fridge_item_names()
    return [ing for ing in ingredients if ing.lower() not in have]


def add_missing_to_grocery(ingredients: list[str] | None = None) -> str:
    """
    Add a list of ingredients to the grocery list.
    If ingredients is None, uses _last_missing_ingredients.
    """
    global _last_missing_ingredients
    items = ingredients if ingredients is not None else _last_missing_ingredients
    if not items:
        return "No missing ingredients to add."
    added = []
    for item in items:
        fridge = _read_json(_p("fridge"))
        if item not in fridge.get("grocery_list", []):
            fridge.setdefault("grocery_list", []).append(item)
            _write_json(_p("fridge"), fridge)
            added.append(item)
    _last_missing_ingredients = []
    if not added:
        return "All items were already on your grocery list."
    joined = ", ".join(added)
    return f"Added {joined} to your grocery list."


def suggest_recipe(llm_caller=None) -> str:
    """
    Suggest a recipe from fridge contents.
    After suggesting, checks for missing ingredients and sets up
    _last_missing_ingredients so the user can confirm adding them.
    Returns the full response string including missing-item prompt.
    """
    global _last_missing_ingredients
    _last_missing_ingredients = []

    try:
        fridge = _read_json(_p("fridge"))
        items  = fridge.get("items", [])

        # Prioritise soonest-expiring
        perishables = sorted(
            [i for i in items if i.get("expires")],
            key=lambda i: i["expires"]
        )
        have = [i["name"] for i in perishables] + [i["name"] for i in items if not i.get("expires")]

        if not have:
            return "Your fridge is empty — no recipe suggestion."

        ingredient_list = ", ".join(have[:8])

        if not llm_caller:
            return f"Try a dish with: {ingredient_list}."

        recipe_text = llm_caller(
            f"Suggest one simple recipe using some of these ingredients "
            f"(prioritise the first ones as they expire soonest): {ingredient_list}. "
            f"Be brief — recipe name, then 3 numbered steps."
        )

        # Parse ingredients needed and find what's missing
        needed  = _parse_ingredients(recipe_text, llm_caller)
        missing = _find_missing(needed)

        if not missing:
            return recipe_text

        _last_missing_ingredients = missing
        if len(missing) == 1:
            prompt = (
                f"\n\nYou're missing {missing[0]} for this recipe. "
                f"Say 'yes' or 'add it' to add it to your grocery list."
            )
        else:
            joined = ", ".join(missing[:-1]) + f", and {missing[-1]}"
            prompt = (
                f"\n\nYou're missing {joined}. "
                f"Say 'yes' or 'add all' to add them to your grocery list."
            )

        return recipe_text + prompt

    except Exception as e:
        return f"Recipe suggestion failed: {e}"


def check_missing_for_recipe(recipe_name: str, llm_caller=None) -> str:
    """
    Given a recipe name, ask the LLM for its ingredients,
    compare with the fridge, and report what's missing.
    """
    global _last_missing_ingredients
    _last_missing_ingredients = []

    if not llm_caller:
        return f"I need the LLM to look up ingredients for {recipe_name}."

    # Get ingredient list for the named recipe
    raw = llm_caller(
        f"List only the main ingredients needed for {recipe_name} as a JSON array. "
        f'No quantities. Example: ["chicken", "garlic", "lemon"]\n'
        f"Just the array, nothing else."
    )

    ingredients = _parse_ingredients(raw, llm_caller) or _parse_ingredients(
        llm_caller(f"What ingredients do I need for {recipe_name}? List them simply."),
        llm_caller
    )

    if not ingredients:
        return f"I couldn't determine the ingredients for {recipe_name}."

    missing = _find_missing(ingredients)
    have    = [i for i in ingredients if i not in missing]

    if not missing:
        return (
            f"Good news — you have everything for {recipe_name}. "
            f"You have: {', '.join(have)}."
        )

    _last_missing_ingredients = missing

    have_str    = f"You have: {', '.join(have)}. " if have else ""
    if len(missing) == 1:
        missing_str = f"You're missing {missing[0]}."
        prompt      = f" Say 'yes' or 'add it' to add it to your grocery list."
    else:
        joined      = ", ".join(missing[:-1]) + f", and {missing[-1]}"
        missing_str = f"You're missing {joined}."
        prompt      = f" Say 'yes' or 'add all' to add them all to your grocery list."

    return f"{have_str}{missing_str}{prompt}"


# ---------------------------------------------------------------------------
# 11. SITES MANAGER
# ---------------------------------------------------------------------------

def sites_add(site: str, category: str) -> str:
    sites = _read_json(_p("sites"))
    cat = category.lower()
    if cat not in sites:
        sites[cat] = []
    if site not in sites[cat]:
        sites[cat].append(site)
        _write_json(_p("sites"), sites)
        return f"Added {site} to {cat} sites."
    return f"{site} is already in {cat} sites."


def sites_remove(site: str, category: str) -> str:
    sites = _read_json(_p("sites"))
    cat = category.lower()
    if site in sites.get(cat, []):
        sites[cat].remove(site)
        _write_json(_p("sites"), sites)
        return f"Removed {site} from {cat} sites."
    return f"{site} not found in {cat} sites."


def sites_list(category: str) -> str:
    sites = _read_json(_p("sites"))
    cat = category.lower()
    items = sites.get(cat, [])
    if not items:
        return f"No {cat} sites."
    return f"{cat.title()} sites: " + ", ".join(items) + "."


def open_quick_link(name: str) -> str:
    return open_app_or_site(name)


# ---------------------------------------------------------------------------
# 12. ROUTINE LAUNCHER
# ---------------------------------------------------------------------------

def launch_routine(name: str) -> str:
    n = name.lower()
    if "study" in n:
        return start_study_mode()
    if "work" in n:
        return switch_profile("work")
    if "chill" in n:
        return switch_profile("chill")
    return f"Unknown routine: {name}"


def switch_profile(profile: str) -> str:
    valid = ("study", "work", "chill")
    if profile not in valid:
        return f"Unknown profile '{profile}'. Choose: {', '.join(valid)}."
    CFG["profile"] = profile
    logger.info("Profile switched to: %s", profile)
    return f"Switched to {profile} mode."


# ---------------------------------------------------------------------------
# 13. NOTES MANAGER
# ---------------------------------------------------------------------------

NOTES_FOLDERS = ("quick", "study", "projects", "ideas", "meetings", "personal")


def _notes_dir(folder: str = "quick") -> Path:
    return BASE_DIR / PATHS["notes"] / folder


def _notes_index_path() -> Path:
    return _p("notes_index")


def _read_index() -> list:
    try:
        return _read_json(_notes_index_path())
    except Exception:
        return []


def _extract_keywords(text: str) -> list[str]:
    """Return meaningful words from text, removing common stop words."""
    stop = {"the", "a", "an", "is", "to", "for", "and", "or", "my", "i",
            "in", "on", "at", "it", "this", "that", "do", "be", "with",
            "are", "was", "has", "have", "from", "by", "about", "finish",
            "complete", "write", "create", "make", "start", "work"}
    return [w for w in re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
            if w not in stop and len(w) > 2]


def check_related_notes(task_title: str) -> list[dict]:
    """
    Search notes_index.json for notes related to a task title.
    Returns a list of matching note index entries.
    """
    if not CFG.get("notes", {}).get("remind_related", True):
        return []
    keywords = _extract_keywords(task_title)
    if not keywords:
        return []
    index = _read_index()
    matches = []
    for note in index:
        note_text = (
            note.get("title", "") + " " +
            note.get("preview", "") + " " +
            " ".join(note.get("tags", []))
        ).lower()
        if any(kw in note_text for kw in keywords):
            matches.append(note)
    return matches


def _write_index(index: list) -> None:
    _write_json(_notes_index_path(), index)


def note_to_app(text: str, app: str = "jarvis") -> str:
    """
    Route a note to a specific app.
    Uses pyautogui to actually TYPE the note into the app.
    app: "jarvis" | "notion" | "notepad" | "onenote" | "word"
    """
    import time as _time

    app_l = app.lower().strip()

    def _type_text(content: str) -> None:
        """Type text via pyautogui — handles Unicode via clipboard."""
        try:
            import pyautogui  # type: ignore
            import subprocess
            # Use clipboard paste for Unicode safety
            subprocess.run(
                ["powershell", "-Command",
                 f"Set-Clipboard -Value @'\n{content}\n'@"],
                capture_output=True, timeout=5
            )
            _time.sleep(0.3)
            pyautogui.hotkey("ctrl", "v")
        except Exception as e:
            logger.warning("pyautogui type failed: %s", e)

    # ── Notion — use API first (most reliable), then app as fallback ─────────
    if "notion" in app_l:
        try:
            from notion_tool import notion_append_to_page, notion_create_page
            result = notion_append_to_page("Quick Notes", text)
            if "not found" in result.lower():
                result = notion_create_page("Quick Notes", text)
            play_sound("done_chime")
            return result
        except Exception:
            pass
        # Fallback: open Notion app and type
        try:
            exe = _resolve_app_map("notion")
            if exe:
                import subprocess
                subprocess.Popen([exe])
                _time.sleep(3)
                import pyautogui  # type: ignore
                pyautogui.hotkey("ctrl", "n")   # new page
                _time.sleep(1)
                _type_text(text)
                play_sound("done_chime")
                return "Note added to Notion."
        except Exception as e:
            return f"Couldn't open Notion: {e}"

    # ── OneNote — open and type on a new page ────────────────────────────────
    if "onenote" in app_l or "one note" in app_l:
        try:
            exe = _resolve_app_map("onenote")
            if exe:
                import subprocess
                subprocess.Popen([exe])
                _time.sleep(3)
                import pyautogui  # type: ignore
                pyautogui.hotkey("ctrl", "n")   # new page
                _time.sleep(1.5)
                _type_text(text)
                play_sound("done_chime")
                return "Note added to OneNote."
            else:
                return "OneNote not found. Is Microsoft Office installed?"
        except Exception as e:
            return f"Couldn't open OneNote: {e}"

    # ── Word — open new document and type ────────────────────────────────────
    if "word" in app_l:
        try:
            exe = _resolve_app_map("word")
            if exe:
                import subprocess
                subprocess.Popen([exe])
                _time.sleep(3)
                _type_text(text)
                play_sound("done_chime")
                return "Note added to Word."
        except Exception as e:
            return f"Couldn't open Word: {e}"

    # ── Notepad — create dated file and open it ──────────────────────────────
    if "notepad" in app_l or "text" in app_l:
        try:
            import subprocess
            now = _now()
            note_dir = BASE_DIR / "data" / "notepad_notes"
            note_dir.mkdir(exist_ok=True)
            fname  = now.strftime("%Y-%m-%d") + "_notes.txt"
            fpath  = note_dir / fname
            existing = fpath.read_text(encoding="utf-8") if fpath.exists() else ""
            fpath.write_text(
                existing + f"\n[{now.strftime('%H:%M')}] {text}\n",
                encoding="utf-8"
            )
            subprocess.Popen(["notepad.exe", str(fpath)])
            play_sound("done_chime")
            return f"Note added to Notepad ({fname})."
        except Exception as e:
            return f"Couldn't open Notepad: {e}"

    # ── Default — save to Jarvis notes ───────────────────────────────────────
    return save_note(text, folder="quick")


def save_note(text: str, folder: str = "quick", title: str | None = None,
              tags: list | None = None, project: str | None = None) -> str:
    tags = tags or []
    now = _now()
    ts = now.strftime("%Y-%m-%d_%H-%M-%S")
    folder = folder.lower()
    if folder not in NOTES_FOLDERS:
        folder = "quick"

    # Auto-detect topic via simple keyword matching
    topic = _detect_topic(text)

    first_sentence = text.split(".")[0][:60].strip() if text else "Note"
    note_title = title or first_sentence

    frontmatter = (
        f"---\n"
        f"title: \"{note_title}\"\n"
        f"topic: \"{topic}\"\n"
        f"tags: {json.dumps(tags)}\n"
        f"project: \"{project or ''}\"\n"
        f"created: \"{now.isoformat()}\"\n"
        f"modified: \"{now.isoformat()}\"\n"
        f"---\n\n"
    )
    content = frontmatter + text

    note_dir = _notes_dir(folder)
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / f"{ts}.md"
    note_path.write_text(content, encoding="utf-8")

    # Update index
    index = _read_index()
    index.append({
        "path": str(note_path.relative_to(BASE_DIR)),
        "title": note_title,
        "topic": topic,
        "tags": tags,
        "project": project or "",
        "folder": folder,
        "created": now.isoformat(),
        "preview": text[:100],
    })
    _write_index(index)
    play_sound("done_chime")
    return f"Got it, saved to {folder}."


def _detect_topic(text: str) -> str:
    text_l = text.lower()
    if any(w in text_l for w in ("code", "python", "css", "html", "function", "bug", "debug")):
        return "study"
    if any(w in text_l for w in ("idea", "concept", "what if", "brainstorm")):
        return "ideas"
    if any(w in text_l for w in ("project", "sprint", "scrum", "task", "deadline", "feature")):
        return "projects"
    if any(w in text_l for w in ("meeting", "standup", "call", "discussed")):
        return "meetings"
    return "quick"


def search_notes(query: str) -> str:
    index = _read_index()
    q = query.lower()
    matches = [
        n for n in index
        if q in n.get("title", "").lower()
        or q in n.get("preview", "").lower()
        or q in n.get("topic", "").lower()
        or any(q in tag.lower() for tag in n.get("tags", []))
        or q in n.get("project", "").lower()
    ]
    if not matches:
        return f"No notes found about '{query}'."
    lines = []
    for m in matches[:3]:
        lines.append(f"• {m['title']} ({m['folder']}) — {m['preview'][:60]}...")
    return "\n".join(lines)


def read_note(query: str) -> str:
    index = _read_index()
    q = query.lower()
    matches = [
        n for n in index
        if q in n.get("title", "").lower() or q in n.get("preview", "").lower()
    ]
    if not matches:
        return f"No note found about '{query}'."
    path = BASE_DIR / matches[0]["path"]
    try:
        text = path.read_text(encoding="utf-8")
        # Strip frontmatter
        if text.startswith("---"):
            text = text.split("---", 2)[-1].strip()
        max_len = CFG.get("notes", {}).get("max_read_length", 500)
        return text[:max_len]
    except Exception as e:
        return f"Couldn't read note: {e}"


def list_notes(folder_or_topic: str) -> str:
    index = _read_index()
    q = folder_or_topic.lower()
    matches = [
        n for n in index
        if q in n.get("folder", "").lower() or q in n.get("topic", "").lower()
    ]
    if not matches:
        return f"No notes in '{folder_or_topic}'."
    titles = [f"• {n['title']}" for n in matches[:10]]
    return "\n".join(titles)


def summarise_notes(query: str, llm_caller=None) -> str:
    index = _read_index()
    q = query.lower()

    if query.lower() == "today":
        today = date.today().isoformat()
        matches = [n for n in index if n.get("created", "")[:10] == today]
    else:
        matches = [
            n for n in index
            if q in n.get("title", "").lower()
            or q in n.get("preview", "").lower()
            or q in n.get("project", "").lower()
        ]

    if not matches:
        return f"No notes found to summarise for '{query}'."

    combined = []
    for n in matches[:5]:
        try:
            path = BASE_DIR / n["path"]
            text = path.read_text(encoding="utf-8")
            if text.startswith("---"):
                text = text.split("---", 2)[-1].strip()
            combined.append(text[:300])
        except Exception:
            combined.append(n.get("preview", ""))

    full_text = "\n\n".join(combined)
    if llm_caller:
        return llm_caller(f"Summarise these notes concisely:\n\n{full_text}")
    return f"Found {len(matches)} notes. Preview: {full_text[:200]}..."


def organise_notes() -> str:
    quick_dir = _notes_dir("quick")
    if not quick_dir.exists():
        return "No notes to organise."

    moved = 0
    index = _read_index()
    index_map = {n["path"]: n for n in index}

    for note_file in quick_dir.glob("*.md"):
        try:
            text = note_file.read_text(encoding="utf-8")
            if text.startswith("---"):
                body = text.split("---", 2)[-1].strip()
            else:
                body = text

            topic = _detect_topic(body)
            if topic == "quick":
                continue

            dest_dir = _notes_dir(topic)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / note_file.name
            shutil.move(str(note_file), str(dest))

            old_rel = str(note_file.relative_to(BASE_DIR))
            new_rel = str(dest.relative_to(BASE_DIR))
            if old_rel in index_map:
                index_map[old_rel]["path"] = new_rel
                index_map[old_rel]["folder"] = topic

            moved += 1
        except Exception as e:
            logger.warning("Could not organise note %s: %s", note_file, e)

    _write_index(list(index_map.values()))
    return f"Organised {moved} note(s)."


# ---------------------------------------------------------------------------
# 14. LONG-TERM MEMORY
# ---------------------------------------------------------------------------

def get_long_term_facts() -> str:
    try:
        lt = _read_json(_p("lt_memory"))
        lines = []
        for category, facts in lt.items():
            for f in facts[:5]:
                lines.append(f"• [{category}] {f.get('fact', '')}")
        return "\n".join(lines) if lines else "No long-term facts stored yet."
    except Exception as e:
        return f"Could not read long-term memory: {e}"


def forget_fact(fragment: str) -> str:
    lt = _read_json(_p("lt_memory"))
    removed = 0
    for category in lt:
        before = len(lt[category])
        lt[category] = [
            f for f in lt[category]
            if fragment.lower() not in f.get("fact", "").lower()
        ]
        removed += before - len(lt[category])
    if removed:
        _write_json(_p("lt_memory"), lt)
        return f"Removed {removed} fact(s) matching '{fragment}'."
    return f"No facts found matching '{fragment}'."


def get_session_summary(date_str: str | None = None) -> str:
    sessions = _read_json(_p("sessions"))
    if not sessions:
        return "No previous sessions recorded."
    if date_str:
        matched = [s for s in sessions if date_str in s.get("date", "")]
        if not matched:
            return f"No session found for {date_str}."
        s = matched[-1]
    else:
        s = sessions[-1]
    return (
        f"Session on {s.get('date', '?')}: {s.get('summary', 'No summary.')}\n"
        f"Topics: {', '.join(s.get('topics', []))}.\n"
        f"Left unfinished: {', '.join(s.get('left_unfinished', [])) or 'nothing'}."
    )


def get_followups() -> str:
    fups = _read_json(_p("followups"))
    open_fups = [f for f in fups if not f.get("done")]
    if not open_fups:
        return "No open follow-ups."
    lines = [f"• [{f['id']}] {f['topic']}: {f['note']}" for f in open_fups]
    return "\n".join(lines)


def get_decisions(topic: str | None = None) -> str:
    decisions = _read_json(_p("decisions"))
    if topic:
        decisions = [d for d in decisions if topic.lower() in d.get("decision", "").lower()
                     or topic.lower() in d.get("context", "").lower()]
    if not decisions:
        return "No decisions recorded."
    lines = []
    for d in decisions[-5:]:
        lines.append(f"• {d.get('date', '?')}: {d.get('decision', '')} — {d.get('reason', '')}")
    return "\n".join(lines)


def get_wellbeing(period: str = "week") -> str:
    wb = _read_json(_p("wellbeing"))
    if not wb:
        return "No wellbeing data recorded."
    recent = wb[-7:] if period == "week" else wb[-30:]
    moods = [e.get("mood", "unknown") for e in recent]
    return f"Recent mood entries: {', '.join(moods)}."


def get_progress(goal_fragment: str | None = None) -> str:
    progress = _read_json(_p("progress"))
    goals = progress.get("goals", [])
    if goal_fragment:
        goals = [g for g in goals if goal_fragment.lower() in g.get("goal", "").lower()]
    if not goals:
        return "No progress data found."
    lines = []
    for g in goals:
        snaps = g.get("snapshots", [])
        latest = snaps[-1] if snaps else {}
        pct = latest.get("progress_percent", 0)
        lines.append(f"• {g['goal']}: {pct}% — {latest.get('note', '')}")
    return "\n".join(lines)


def update_progress(goal_fragment: str, percent: int, note: str = "") -> str:
    progress = _read_json(_p("progress"))
    goals    = progress.get("goals", [])
    matched  = [g for g in goals if goal_fragment.lower() in g.get("goal", "").lower()]
    if not matched:
        return f"No goal found matching '{goal_fragment}'."

    goal = matched[0]
    snaps = goal.setdefault("snapshots", [])
    prev_pct = snaps[-1]["progress_percent"] if snaps else 0

    snaps.append({
        "date":                  date.today().isoformat(),
        "progress_percent":      percent,
        "note":                  note,
        "completed_this_week":   [],
        "next_steps":            [],
    })
    _write_json(_p("progress"), progress)

    # ── Milestone celebrations ─────────────────────────────────────────────
    celebration = ""
    for milestone in (25, 50, 75, 100):
        if prev_pct < milestone <= percent:
            if percent == 100:
                celebration = (
                    f" Congratulations — you've completed '{goal['goal']}'! "
                    f"Outstanding work, Samaira."
                )
                play_sound("done_chime")
            else:
                celebration = (
                    f" You've hit {milestone}% on '{goal['goal']}'. "
                    f"Keep it up!"
                )
                play_sound("done_chime")
            break

    return f"Updated progress for '{goal['goal']}' to {percent}%.{celebration}"


# ---------------------------------------------------------------------------
# Weekly habits consistency report
# ---------------------------------------------------------------------------

def weekly_habits_report() -> str:
    """
    Return a spoken habits consistency report for the past 7 days.
    Checks wellbeing_log for exercise, hydration, and mood trends.
    Also checks notes and tasks.
    """
    try:
        wb = _read_json(_p("wellbeing"))
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        recent   = [e for e in wb if e.get("date", "") >= week_ago]

        if not recent:
            return "No wellbeing data for this week yet."

        days_logged   = len(recent)
        exercise_days = sum(1 for e in recent if e.get("exercise", "").strip())
        hydration_vals = [float(e.get("hydration_L", 0)) for e in recent if e.get("hydration_L")]
        avg_hydration = round(sum(hydration_vals) / len(hydration_vals), 1) if hydration_vals else 0
        moods         = [e.get("mood", "") for e in recent if e.get("mood")]
        good_moods    = sum(1 for m in moods if m.lower() in ("good", "great", "amazing", "happy"))

        lines = [f"Your week in review — {days_logged} days logged."]

        # Exercise
        if exercise_days == 0:
            lines.append("No exercise logged this week.")
        elif exercise_days >= 5:
            lines.append(f"Excellent — you exercised {exercise_days} days this week!")
        else:
            lines.append(f"Exercise: {exercise_days} out of 7 days.")

        # Hydration
        if avg_hydration >= 2.0:
            lines.append(f"Great hydration — averaging {avg_hydration} litres per day.")
        elif avg_hydration > 0:
            lines.append(f"Hydration average: {avg_hydration} litres per day. Aim for 2 litres.")
        else:
            lines.append("No hydration logged this week.")

        # Mood
        if moods:
            if good_moods >= len(moods) * 0.7:
                lines.append("Your mood has been mostly positive this week.")
            else:
                lines.append(f"You had {good_moods} good mood days out of {len(moods)} logged.")

        # Tasks completed this week
        try:
            tasks = _read_json(_p("tasks"))
            completed = [t for t in tasks if t.get("done") and
                         t.get("created_at", "")[:10] >= week_ago]
            lines.append(f"Tasks completed: {len(completed)}.")
        except Exception:
            pass

        return " ".join(lines)

    except Exception as e:
        return f"Couldn't generate habits report: {e}"


def search_transcripts(query: str) -> str:
    convo_dir = BASE_DIR / PATHS["convos"]
    if not convo_dir.exists():
        return "No conversation history found."
    q = query.lower()
    results = []
    for md_file in sorted(convo_dir.glob("*.md"), reverse=True)[:30]:
        text = md_file.read_text(encoding="utf-8", errors="ignore")
        lines = [ln for ln in text.splitlines() if q in ln.lower()]
        if lines:
            results.append(f"**{md_file.stem}**: {lines[0][:120]}")
        if len(results) >= 5:
            break
    return "\n".join(results) if results else f"No conversations found about '{query}'."


# ---------------------------------------------------------------------------
# Weather (wttr.in — no API key needed, requires internet)
# ---------------------------------------------------------------------------

_WEATHER_URL = "https://wttr.in/{location}"

# Emoji → spoken word map so TTS reads naturally
_WEATHER_EMOJI = {
    "☀️": "sunny", "🌤": "partly cloudy", "⛅": "partly cloudy",
    "🌥": "cloudy", "☁️": "overcast", "🌦": "light rain", "🌧": "rainy",
    "⛈": "thunderstorms", "🌩": "thunderstorms", "❄️": "snowing",
    "🌨": "snowing", "🌫": "foggy", "🌬": "windy", "🌈": "rainbow",
    "🌡": "", "+": "+", "°C": " degrees Celsius", "°F": " degrees Fahrenheit",
}


def _strip_weather_emoji(text: str) -> str:
    """Replace weather emoji with spoken equivalents, strip all remaining non-speech chars."""
    import unicodedata
    result = text
    for emoji, word in _WEATHER_EMOJI.items():
        result = result.replace(emoji, f" {word} " if word else " ")
    # Remove variation selectors (U+FE0F, U+FE0E), zero-width chars, and any
    # remaining emoji (categories So = Symbol/Other, Mn = combining marks)
    cleaned = []
    for c in result:
        cp = ord(c)
        cat = unicodedata.category(c)
        if cp in (0xFE0F, 0xFE0E, 0x200B, 0x200C, 0x200D):
            continue
        if cat.startswith("So") or (0x1F000 <= cp <= 0x1FFFF):
            continue
        cleaned.append(c)
    return " ".join("".join(cleaned).split())


def _default_location() -> str:
    """Return location from config > memory > fallback."""
    try:
        loc = CFG.get("weather", {}).get("default_location", "").strip()
        if loc:
            return loc
    except Exception:
        pass
    try:
        mem = _read_json(_p("memory"))
        loc = mem.get("location", "").strip()
        if loc:
            return loc
    except Exception:
        pass
    return "London"


_WEATHER_CACHE_PATH = BASE_DIR / "data" / "weather_cache.json"


def _load_cached_weather() -> dict | None:
    try:
        cache = _read_json(_WEATHER_CACHE_PATH)
        age_h = (datetime.now() - datetime.fromisoformat(
            cache.get("last_updated", "2000-01-01"))).total_seconds() / 3600
        if age_h < 12:
            logger.info("Weather: using cache (%.1fh old).", age_h)
            return cache.get("data")
        logger.warning("Weather cache too old (%.1fh).", age_h)
    except Exception:
        pass
    return None


def _fetch_weather_json(location: str) -> dict:
    """Fetch weather JSON with 5s hard timeout + automatic cache fallback."""
    url = _WEATHER_URL.format(location=location.replace(" ", "+")) + "?format=j1"
    try:
        resp = requests.get(url, timeout=5, headers={"User-Agent": "Jarvis/1.0"})
        resp.raise_for_status()
        data = resp.json()
        # Cache the successful response
        _WEATHER_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _write_json(_WEATHER_CACHE_PATH, {
            "location":     location,
            "last_updated": datetime.now().isoformat(),
            "data":         data,
        })
        return data
    except requests.exceptions.Timeout:
        logger.warning("Weather fetch timed out — using cache.")
        cached = _load_cached_weather()
        if cached:
            return cached
        raise
    except Exception as e:
        logger.warning("Weather fetch failed (%s) — trying cache.", e)
        cached = _load_cached_weather()
        if cached:
            return cached
        raise


def get_weather(location: str | None = None, query: str = "current") -> str:
    """
    Get weather info from wttr.in.
    query: "current" | "rain" | "forecast" | "outfit"
    """
    loc = (location or _default_location()).strip()

    try:
        # ── Simple one-liner for current weather ──────────────────────────
        if query == "current":
            url  = _WEATHER_URL.format(location=loc.replace(" ", "+")) + "?format=3"
            resp = requests.get(url, timeout=6)
            resp.raise_for_status()
            raw  = resp.text.strip()
            return _strip_weather_emoji(raw)

        # ── Full JSON for all other queries ───────────────────────────────
        data    = _fetch_weather_json(loc)
        current = data.get("current_condition", [{}])[0]
        weather = data.get("weather", [])

        temp_c      = int(current.get("temp_C", 0))
        feels_c     = int(current.get("FeelsLikeC", temp_c))
        desc        = current.get("weatherDesc", [{}])[0].get("value", "")
        precip_mm   = float(current.get("precipMM", 0))
        humidity    = int(current.get("humidity", 0))
        wind_kmph   = int(current.get("windspeedKmph", 0))

        units = CFG.get("weather", {}).get("units", "metric")
        if units == "imperial":
            temp_show   = f"{int(current.get('temp_F', temp_c * 9/5 + 32))}°F"
            feels_show  = f"{int(current.get('FeelsLikeF', feels_c * 9/5 + 32))}°F"
        else:
            temp_show  = f"{temp_c}°C"
            feels_show = f"{feels_c}°C"

        # ── Rain check ───────────────────────────────────────────────────
        if query == "rain":
            today_w    = weather[0] if weather else {}
            hourly     = today_w.get("hourly", [])
            max_precip = max((float(h.get("precipMM", 0)) for h in hourly), default=0)
            chance     = max((int(h.get("chanceofrain", 0)) for h in hourly), default=0)
            if chance > 50 or max_precip > 1:
                return (
                    f"Yes, rain is likely in {loc} today. "
                    f"Up to {max_precip:.1f} mm expected, {chance}% chance. "
                    "I'd recommend taking an umbrella."
                )
            return f"No significant rain expected in {loc} today. Current chance is {chance}%."

        # ── 3-day forecast ───────────────────────────────────────────────
        if query == "forecast":
            if not weather:
                return f"No forecast data available for {loc}."
            lines = [f"Three-day forecast for {loc}."]
            days  = ["Today", "Tomorrow", "The day after"]
            for i, (day_name, w) in enumerate(zip(days, weather[:3])):
                max_c = int(w.get("maxtempC", 0))
                min_c = int(w.get("mintempC", 0))
                day_desc = w.get("hourly", [{}])[4].get("weatherDesc", [{}])[0].get("value", "")
                if units == "imperial":
                    temps = f"{int(max_c*9/5+32)} to {int(min_c*9/5+32)}°F"
                else:
                    temps = f"{max_c} to {min_c}°C"
                lines.append(f"{day_name}: {day_desc}, {temps}.")
            return " ".join(lines)

        # ── Outfit suggestion ────────────────────────────────────────────
        if query == "outfit":
            rain_chance = max(
                (int(h.get("chanceofrain", 0)) for h in weather[0].get("hourly", [{}])),
                default=0,
            ) if weather else 0

            if temp_c <= 5:
                outfit = "a heavy coat, thermal layers, gloves and a scarf"
            elif temp_c <= 12:
                outfit = "a warm jacket and layers"
            elif temp_c <= 18:
                outfit = "a light jacket or a hoodie"
            elif temp_c <= 24:
                outfit = "a t-shirt or light top — it's pleasant out"
            else:
                outfit = "light, breathable clothing — it's warm"

            umbrella = " Don't forget an umbrella — rain is likely." if rain_chance > 50 else ""
            return (
                f"It's {temp_show} in {loc}, feels like {feels_show}. "
                f"I'd suggest {outfit}.{umbrella}"
            )

    except requests.exceptions.ConnectionError:
        return "I can't reach the weather service right now. Check your connection."
    except requests.exceptions.Timeout:
        return "The weather service took too long to respond. Try again in a moment."
    except Exception as e:
        logger.error("Weather tool error: %s", e)
        return "I couldn't retrieve the weather at the moment."

    return get_weather(location=loc, query="current")


# ---------------------------------------------------------------------------
# Alarm & Reminder tool
# ---------------------------------------------------------------------------

_ALARM_SOUND      = BASE_DIR / "assets" / "sounds" / "alarm.mp3"
_POMODORO_END_SND = BASE_DIR / "assets" / "sounds" / "pomodoro_end.mp3"


def _play_pomodoro_end_sound() -> None:
    """Play the 3-beep Pomodoro end tone via pygame."""
    snd = _POMODORO_END_SND
    if not snd.exists():
        return
    try:
        import pygame  # type: ignore
        if not pygame.mixer.get_init():
            pygame.mixer.pre_init(44100, -16, 1, 512)
            pygame.mixer.init()
        pygame.mixer.music.load(str(snd))
        pygame.mixer.music.play()
        # Block until the ~1.35 s clip finishes before the voice line
        import time as _t
        while pygame.mixer.music.get_busy():
            _t.sleep(0.05)
    except Exception as e:
        logger.warning("Pomodoro end sound failed: %s", e)


def _next_reminder_id(reminders: list) -> str:
    if not reminders:
        return "rem_001"
    nums = []
    for r in reminders:
        try:
            nums.append(int(r["id"].split("_")[1]))
        except Exception:
            pass
    return f"rem_{(max(nums, default=0) + 1):03d}"


def parse_reminder_time(text: str) -> datetime | None:
    """
    Parse natural language time expressions into a datetime.
    Handles: "in 30 minutes", "at 3pm", "tomorrow at 9am",
             "at 15:30", "in 2 hours", "every day at 8am"
    Returns a future datetime or None on failure.
    """
    try:
        import dateparser  # type: ignore
        settings = {
            "PREFER_DATES_FROM": "future",
            "RETURN_AS_TIMEZONE_AWARE": False,
            "PREFER_DAY_OF_MONTH": "first",
        }
        dt = dateparser.parse(text, settings=settings)
        if dt:
            # Strip timezone info if present to avoid naive/aware comparison
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            # For "at X" patterns where the time today has passed,
            # dateparser should return tomorrow — but add 1 day as safety net
            now = _now()
            if dt <= now:
                dt = dt + timedelta(days=1)
            return dt
    except Exception as e:
        logger.warning("dateparser failed: %s", e)

    # Manual fallback for simple patterns
    now = _now()
    m = re.search(r"in\s+(\d+)\s+minute", text, re.I)
    if m:
        return now + timedelta(minutes=int(m.group(1)))
    m = re.search(r"in\s+(\d+)\s+hour", text, re.I)
    if m:
        return now + timedelta(hours=int(m.group(1)))
    return None


def _detect_repeat(text: str) -> str | None:
    t = text.lower()
    if "every day" in t or "daily" in t:
        return "daily"
    if "every week" in t or "weekly" in t:
        return "weekly"
    return None


def create_reminder(message: str, trigger_at: datetime,
                    repeat: str | None = None, kind: str = "reminder") -> str:
    """Save a new reminder/alarm to reminders.json."""
    reminders = _read_json(_p("reminders"))
    new_id = _next_reminder_id(reminders)
    reminders.append({
        "id":         new_id,
        "kind":       kind,            # "reminder" or "alarm"
        "created":    _now().isoformat(),
        "trigger_at": trigger_at.isoformat(),
        "message":    message,
        "repeat":     repeat,
        "done":       False,
    })
    _write_json(_p("reminders"), reminders)

    # Human-readable confirmation
    now  = _now()
    diff = (trigger_at - now).total_seconds()
    if diff < 3600:
        when = f"in {int(diff // 60)} minute{'s' if diff >= 120 else ''}"
    elif diff < 86400:
        when = f"at {trigger_at.strftime('%I:%M %p').lstrip('0')}"
    else:
        when = f"on {trigger_at.strftime('%A at %I:%M %p').lstrip('0')}"

    play_sound("done_chime")
    if repeat:
        return f"I'll remind you {repeat} {when} to {message}."
    label = "alarm" if kind == "alarm" else "reminder"
    return f"I'll {label} you {when} — {message}."


def list_reminders() -> str:
    """List upcoming (undone) reminders."""
    reminders = _read_json(_p("reminders"))
    upcoming = sorted(
        [r for r in reminders if not r.get("done")],
        key=lambda r: r.get("trigger_at", "")
    )
    if not upcoming:
        return "You have no upcoming reminders or alarms."
    now = _now()
    lines = []
    for r in upcoming[:8]:
        try:
            dt   = datetime.fromisoformat(r["trigger_at"])
            diff = (dt - now).total_seconds()
            if diff < 60:
                when = "in less than a minute"
            elif diff < 3600:
                when = f"in {int(diff // 60)} minutes"
            elif diff < 86400:
                when = f"at {dt.strftime('%I:%M %p').lstrip('0')}"
            else:
                when = f"on {dt.strftime('%A at %I:%M %p').lstrip('0')}"
            rep  = f" (repeats {r['repeat']})" if r.get("repeat") else ""
            lines.append(f"• {r['message']} — {when}{rep}")
        except Exception:
            lines.append(f"• {r.get('message', '?')}")
    return f"You have {len(upcoming)} upcoming reminder{'s' if len(upcoming) != 1 else ''}:\n" + "\n".join(lines)


def edit_reminder(fragment: str, new_time_str: str) -> str:
    """
    Find a reminder matching fragment and reschedule it to new_time_str.
    Matches both active and done reminders (to allow reactivation).
    Example: edit_reminder("dentist", "Thursday at 3pm")
    """
    reminders = _read_json(_p("reminders"))
    frag = fragment.lower()
    # Active reminders first, then done ones
    all_matches = [r for r in reminders if frag in r.get("message", "").lower()]
    all_matches.sort(key=lambda r: r.get("done", False))  # False sorts before True
    if not all_matches:
        return f"No reminder found matching '{fragment}'."
    matches = all_matches

    dt = parse_reminder_time(new_time_str)
    if not dt:
        return f"I couldn't understand '{new_time_str}'. Try 'Thursday at 3pm' or 'in 2 hours'."

    # Update the first match
    target = matches[0]
    for r in reminders:
        if r["id"] == target["id"]:
            r["trigger_at"] = dt.isoformat()
            r["done"] = False   # reactivate if it was done
            break

    _write_json(_p("reminders"), reminders)

    # Human-readable confirmation
    diff = (dt - _now()).total_seconds()
    if diff < 3600:
        when = f"in {int(diff // 60)} minutes"
    elif diff < 86400:
        when = f"at {dt.strftime('%I:%M %p').lstrip('0')} today"
    else:
        when = f"on {dt.strftime('%A at %I:%M %p')}"

    return f"Updated '{target['message']}' — I'll remind you {when}."


def cancel_reminder(fragment: str) -> str:
    """Cancel a reminder whose message contains fragment."""
    reminders = _read_json(_p("reminders"))
    matches = [
        r for r in reminders
        if not r.get("done") and fragment.lower() in r.get("message", "").lower()
    ]
    if not matches:
        return f"No active reminder found matching '{fragment}'."
    for r in matches:
        r["done"] = True
    _write_json(_p("reminders"), reminders)
    cancelled = ", ".join(r["message"] for r in matches)
    return f"Cancelled: {cancelled}."


def fire_reminder(reminder: dict, speak_fn=None) -> None:
    """
    Fire a single reminder: speak it, show a toast, mark done (or reschedule).
    Called by the scheduler.
    """
    msg  = reminder.get("message", "Reminder")
    kind = reminder.get("kind", "reminder")

    # Speak
    spoken = f"Alarm: {msg}" if kind == "alarm" else f"Reminder: {msg}"
    logger.info("Firing %s: %s", kind, msg)
    if speak_fn:
        speak_fn(spoken)

    # Windows toast notification
    try:
        from winotify import Notification  # type: ignore
        toast = Notification(
            app_id="Jarvis",
            title="Alarm" if kind == "alarm" else "Reminder",
            msg=msg,
            duration="long",
        )
        toast.show()
    except Exception as e:
        logger.warning("Toast notification failed: %s", e)

    # Send phone notification via ntfy
    try:
        from notification_tool import send_reminder_notification
        send_reminder_notification(msg)
    except Exception:
        pass

    # Play alarm or done chime
    if kind == "alarm":
        play_sound("alarm")
    else:
        play_sound("done_chime")

    # Mark done / reschedule
    reminders = _read_json(_p("reminders"))
    for r in reminders:
        if r["id"] == reminder["id"]:
            repeat = r.get("repeat")
            if repeat == "daily":
                r["trigger_at"] = (
                    datetime.fromisoformat(r["trigger_at"]) + timedelta(days=1)
                ).isoformat()
                r["done"] = False
            elif repeat == "weekly":
                r["trigger_at"] = (
                    datetime.fromisoformat(r["trigger_at"]) + timedelta(weeks=1)
                ).isoformat()
                r["done"] = False
            else:
                r["done"] = True
            break
    _write_json(_p("reminders"), reminders)


# ---------------------------------------------------------------------------
# Life summary
# ---------------------------------------------------------------------------

def life_summary() -> str:
    """
    One flowing spoken summary of mood, goals, tasks, habits,
    notes, fridge, and open follow-ups. Kept under ~120 words
    (≈ 55 seconds of speech at a natural pace).
    """
    parts: list[str] = []

    # ── 1. Mood trend (last 7 days) ──────────────────────────────────────
    try:
        wb = _read_json(_p("wellbeing"))
        recent = wb[-7:] if len(wb) >= 7 else wb
        if recent:
            mood_counts: dict[str, int] = {}
            for entry in recent:
                mood = entry.get("mood", "unknown").lower()
                mood_counts[mood] = mood_counts.get(mood, 0) + 1
            mood_strs = [f"{m} {c} day{'s' if c != 1 else ''}" for m, c in mood_counts.items()]
            parts.append(f"Mood-wise you've been {', '.join(mood_strs)} this week.")
        else:
            parts.append("No mood data recorded yet this week.")
    except Exception:
        pass

    # ── 2. Goals progress ────────────────────────────────────────────────
    try:
        progress = _read_json(_p("progress"))
        goals = progress.get("goals", [])
        if goals:
            goal_strs = []
            for g in goals[:3]:
                snaps = g.get("snapshots", [])
                pct   = snaps[-1]["progress_percent"] if snaps else 0
                delta = ""
                if len(snaps) >= 2:
                    d = snaps[-1]["progress_percent"] - snaps[-2]["progress_percent"]
                    delta = f", up {d}% from last week" if d > 0 else (f", down {abs(d)}%" if d < 0 else ", no change")
                goal_strs.append(f"{g['goal']} is at {pct}%{delta}")
            parts.append(". ".join(goal_strs) + ".")
        else:
            # Fall back to goals.json raw data
            gdata = _read_json(_p("goals"))
            all_g = gdata.get("long_term", []) + gdata.get("short_term", [])
            if all_g:
                g_strs = [f"{g['goal']} at {g.get('progress', 0)}%" for g in all_g[:2]]
                parts.append(". ".join(g_strs) + ".")
    except Exception:
        pass

    # ── 3. Tasks (with priority breakdown) ──────────────────────────────
    try:
        tasks    = _read_json(_p("tasks"))
        pending  = [t for t in tasks if not t.get("done")]
        today    = date.today().isoformat()
        high     = [t for t in pending if t.get("priority") == "high"]
        due_today = [t for t in pending if t.get("deadline", "")[:10] == today]
        overdue  = [t for t in pending
                    if t.get("deadline") and t["deadline"][:10] < today]
        task_str = f"You have {len(pending)} pending task{'s' if len(pending) != 1 else ''}."
        if high:
            task_str += f" {len(high)} high priority."
        if due_today:
            task_str += f" {len(due_today)} due today."
        if overdue:
            task_str += f" {len(overdue)} overdue."
        parts.append(task_str)
    except Exception:
        pass

    # ── 4. Habits ────────────────────────────────────────────────────────
    try:
        routines = _read_json(_p("routines"))
        habits   = routines.get("habits", [])
        if habits:
            parts.append(f"Your daily habits include {', '.join(habits)}.")
    except Exception:
        pass

    # ── 5. Notes this week ───────────────────────────────────────────────
    try:
        index     = _read_json(_p("notes_index"))
        week_ago  = (date.today() - timedelta(days=7)).isoformat()
        recent_n  = [n for n in index if n.get("created", "")[:10] >= week_ago]
        if recent_n:
            folders  = {}
            for n in recent_n:
                f = n.get("folder", "quick")
                folders[f] = folders.get(f, 0) + 1
            folder_str = " and ".join(f"{v} in {k}" for k, v in list(folders.items())[:2])
            parts.append(f"You've taken {len(recent_n)} note{'s' if len(recent_n) != 1 else ''} this week, {folder_str}.")
        else:
            parts.append("No notes taken this week.")
    except Exception:
        pass

    # ── 6. Fridge expiry ─────────────────────────────────────────────────
    try:
        fridge  = _read_json(_p("fridge"))
        cutoff  = date.today() + timedelta(days=3)
        expiring = sorted(
            [i for i in fridge.get("items", []) if i.get("expires") and date.fromisoformat(i["expires"]) <= cutoff],
            key=lambda i: i["expires"]
        )
        if expiring:
            exp_strs = []
            for i in expiring[:3]:
                days = (date.fromisoformat(i["expires"]) - date.today()).days
                if days < 0:
                    when = f"already expired {abs(days)} day{'s' if abs(days) != 1 else ''} ago"
                elif days == 0:
                    when = "today"
                elif days == 1:
                    when = "tomorrow"
                else:
                    when = f"in {days} days"
                exp_strs.append(f"{i['name']} {when}")
            parts.append(f"{len(expiring)} item{'s' if len(expiring) != 1 else ''} expiring soon: {', '.join(exp_strs)}.")
        else:
            parts.append("Nothing expiring in your fridge soon.")
    except Exception:
        pass

    # ── 7. Open follow-ups ───────────────────────────────────────────────
    try:
        fups = _read_json(_p("followups"))
        open_fups = [f for f in fups if not f.get("done")]
        if open_fups:
            parts.append(
                f"I have {len(open_fups)} open follow-up{'s' if len(open_fups) != 1 else ''} "
                f"from our previous conversations."
            )
    except Exception:
        pass

    # ── 8. Exercise this week ────────────────────────────────────────────
    try:
        wb = _read_json(_p("wellbeing"))
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        recent_wb = [e for e in wb if e.get("date", "") >= week_ago]
        ex_days = sum(1 for e in recent_wb if e.get("exercise", "").strip())
        if ex_days > 0:
            parts.append(f"You exercised {ex_days} time{'s' if ex_days != 1 else ''} this week.")
        else:
            parts.append("No exercise logged this week.")
    except Exception:
        pass

    # ── 9. Average hydration ─────────────────────────────────────────────
    try:
        wb = _read_json(_p("wellbeing"))
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        recent_wb = [e for e in wb if e.get("date", "") >= week_ago]
        hydration_days = [float(e.get("hydration_L", 0)) for e in recent_wb if e.get("hydration_L")]
        if hydration_days:
            avg = round(sum(hydration_days) / len(hydration_days), 1)
            parts.append(f"Average {avg} litres of water per day this week.")
    except Exception:
        pass

    if not parts:
        return "I don't have enough data yet to give you a summary."

    return " ".join(parts)


# ---------------------------------------------------------------------------
# 13. Backup / export
# ---------------------------------------------------------------------------

def backup_everything(silent: bool = False) -> str:
    """
    Zip data/, memory/, notes/, logs/conversations/ into exports/.
    Respects config backup.keep_last_n — deletes oldest exports beyond the limit.
    silent=True suppresses the return string (used for auto-weekly backups).
    """
    import zipfile
    exports_dir = BASE_DIR / PATHS.get("exports", "exports/")
    exports_dir.mkdir(parents=True, exist_ok=True)
    ts  = _now().strftime("%Y-%m-%d_%H-%M")
    out = exports_dir / f"jarvis_backup_{ts}.zip"

    dirs_to_backup = ["data", "memory", "notes", "logs/conversations"]
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for d in dirs_to_backup:
            full = BASE_DIR / d
            if not full.exists():
                continue
            for f in full.rglob("*"):
                if f.is_file():
                    zf.write(f, f.relative_to(BASE_DIR))
                    count += 1

    size_kb = out.stat().st_size // 1024
    logger.info("Backup saved: %s (%d files, %d KB)", out.name, count, size_kb)

    # Enforce keep_last_n (default 8) — delete oldest beyond the limit
    bak_cfg = CFG.get("backup", {})
    keep_n  = int(bak_cfg.get("keep_last_n", 8))
    existing = sorted(exports_dir.glob("jarvis_backup_*.zip"),
                      key=lambda p: p.stat().st_mtime)
    for old in existing[:-keep_n]:
        try:
            old.unlink()
            logger.info("Deleted old backup: %s", old.name)
        except Exception:
            pass

    # Monthly permanent backup — first Sunday of month
    if bak_cfg.get("keep_monthly", True):
        now = _now()
        if now.day <= 7:   # within first week
            monthly_dir = exports_dir / "monthly"
            monthly_dir.mkdir(exist_ok=True)
            monthly_name = f"jarvis_monthly_{now.strftime('%Y-%m')}.zip"
            monthly_path = monthly_dir / monthly_name
            if not monthly_path.exists():
                shutil.copy2(out, monthly_path)
                logger.info("Monthly backup saved: %s", monthly_name)

    msg = f"Backup saved to exports/{out.name} — {count} files, {size_kb} KB."
    return "" if silent else msg


def last_backup_time() -> str:
    """Return when the most recent backup was created."""
    exports_dir = BASE_DIR / PATHS.get("exports", "exports/")
    backups = sorted(exports_dir.glob("jarvis_backup_*.zip"),
                     key=lambda p: p.stat().st_mtime, reverse=True)
    if not backups:
        return "No backups found yet."
    latest = backups[0]
    ts = datetime.fromtimestamp(latest.stat().st_mtime).strftime("%A %d %B at %H:%M")
    return f"Last backup: {latest.name}, created {ts}."


# ---------------------------------------------------------------------------
# Jarvis doctor — self-diagnostic
# ---------------------------------------------------------------------------

def jarvis_doctor() -> str:
    """
    Run a full system self-check and return a spoken summary.
    Checks: Ollama, model, wake word, mic, admin, data files,
    edge-tts, disk space, RAM.
    """
    import shutil

    results: list[tuple[str, str]] = []   # (status_char, message)

    def ok(msg):   results.append(("ok",   msg))
    def warn(msg): results.append(("warn", msg))
    def fail(msg): results.append(("fail", msg))

    # 1. Ollama running?
    try:
        requests.get("http://localhost:11434", timeout=2)
        ok("Ollama is running.")
    except Exception:
        fail("Ollama is not running. Start it with: ollama serve")

    # 2. llama3 model available?
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        models = [m["name"] for m in r.json().get("models", [])]
        model_name = CFG.get("model", "llama3")
        if any(model_name in m for m in models):
            ok(f"{model_name} model is available.")
        else:
            fail(f"{model_name} not found. Run: ollama pull {model_name}")
    except Exception:
        warn("Could not check Ollama models.")

    # 3. Wake word model
    try:
        from setup_models import get_oww_model_path
        if get_oww_model_path():
            ok("Wake word model found.")
        else:
            fail("Wake word model missing. Restart Jarvis to download it.")
    except Exception:
        warn("Could not check wake word model.")

    # 4. Microphone
    try:
        import sounddevice as sd
        mic_idx = CFG.get("mic_device_index", None)
        if isinstance(mic_idx, str) and mic_idx.lower() == "auto":
            mic_idx = None
        sd.query_devices(mic_idx)
        ok("Microphone accessible.")
    except Exception:
        fail("Microphone not found. Check mic_device_index in config.yaml.")

    # 5. Admin rights
    try:
        import ctypes
        if ctypes.windll.shell32.IsUserAnAdmin():
            ok("Running as administrator.")
        else:
            warn("Not running as admin. Site blocking will trigger UAC prompt.")
    except Exception:
        warn("Could not check admin rights.")

    # 6. All data files present
    data_files = ["memory.json", "tasks.json", "goals.json", "fridge.json",
                  "routines.json", "sites.json", "reminders.json"]
    missing = [f for f in data_files if not (BASE_DIR / "data" / f).exists()]
    if not missing:
        ok("All data files present.")
    else:
        fail(f"Missing data files: {', '.join(missing)}")

    # 7. edge-tts reachable
    try:
        import asyncio, edge_tts as _et  # type: ignore
        asyncio.run(_et.list_voices())
        ok("edge-tts is online.")
    except Exception:
        warn("edge-tts offline. Piper or pyttsx3 fallback will be used.")

    # 8. Disk space
    total, used, free = shutil.disk_usage(str(BASE_DIR))
    free_gb = free // (2 ** 30)
    if free_gb > 2:
        ok(f"Disk space: {free_gb} GB free.")
    else:
        warn(f"Low disk space: {free_gb} GB free.")

    # 9. RAM
    ram = psutil.virtual_memory()
    ok(f"RAM: {ram.percent:.0f}% used, {ram.available // (2 ** 20)} MB free.")

    # Build summary
    passed = sum(1 for s, _ in results if s == "ok")
    warned = sum(1 for s, _ in results if s == "warn")
    failed = sum(1 for s, _ in results if s == "fail")

    summary = (
        f"Diagnostics complete. "
        f"{passed} checks passed, "
        f"{warned} warning{'s' if warned != 1 else ''}, "
        f"{failed} failure{'s' if failed != 1 else ''}. "
    )

    details = []
    for status, msg in results:
        prefix = "" if status == "ok" else ("Warning: " if status == "warn" else "Issue: ")
        details.append(prefix + msg)

    logger.info("Doctor results:\n%s", "\n".join(f"[{s}] {m}" for s, m in results))
    return summary + " ".join(details)


# ---------------------------------------------------------------------------
# Project status tool
# ---------------------------------------------------------------------------

def project_status(project_name: str | None = None) -> str:
    """
    Return status of a specific project or all active projects.
    Pulls from memory.json projects, goals progress, and recent notes.
    """
    try:
        mem      = _read_json(_p("memory"))
        projects = mem.get("projects", [])
    except Exception:
        return "Could not read project data."

    if not projects:
        return "No projects found in memory. Add some via first-run setup or voice."

    # Filter if specific project requested
    if project_name:
        projects = [
            p for p in projects
            if project_name.lower() in (
                p if isinstance(p, str) else p.get("name", "")
            ).lower()
        ]
        if not projects:
            return f"No project found matching '{project_name}'."

    lines = []
    for proj in projects[:5]:
        name = proj if isinstance(proj, str) else proj.get("name", "?")

        # Find goal progress
        pct = 0
        try:
            progress = _read_json(_p("progress"))
            for g in progress.get("goals", []):
                if name.lower() in g.get("goal", "").lower():
                    snaps = g.get("snapshots", [])
                    pct   = snaps[-1]["progress_percent"] if snaps else 0
                    break
        except Exception:
            pass

        # Find related notes count
        note_count = 0
        try:
            index = _read_index()
            note_count = sum(
                1 for n in index
                if name.lower() in n.get("project", "").lower()
                or name.lower() in n.get("title", "").lower()
            )
        except Exception:
            pass

        # Find open tasks
        task_count = 0
        try:
            tasks = _read_json(_p("tasks"))
            task_count = sum(
                1 for t in tasks
                if not t.get("done") and name.lower() in t.get("title", "").lower()
            )
        except Exception:
            pass

        lines.append(
            f"{name}: {pct}% progress, "
            f"{task_count} open task{'s' if task_count != 1 else ''}, "
            f"{note_count} note{'s' if note_count != 1 else ''}."
        )

    return "Project status: " + " | ".join(lines) if lines else "No project data available."


# ---------------------------------------------------------------------------
# 15. Help command
# ---------------------------------------------------------------------------

def help_tool() -> str:
    """
    Categorised spoken summary of Jarvis's capabilities.
    Kept under ~90 seconds of speech.
    """
    # Pull the configured city so the weather line is accurate
    try:
        city = CFG.get("weather", {}).get("default_location", "your city")
    except Exception:
        city = "your city"

    return (
        "Here's what I can do. "

        "Tasks and goals: add tasks, check deadlines, "
        "track progress on your goals. "

        "Notes: take quick notes by voice, search, summarise, "
        "and organise them by topic. "

        "Study mode: block distracting sites, open your study apps, "
        "start a Pomodoro timer, play background sounds. "

        "Reminders and alarms: remind you at any time, "
        "set repeating daily reminders. "

        "Fridge and recipes: track what's in your fridge, "
        "warn about expiry, suggest recipes. "

        "Apps and sites: open any app or website by name. "

        "System info: battery, WiFi, CPU, RAM, storage. "

        f"Weather: current conditions and forecast for {city} "
        "or any city. "

        "Memory: I remember our conversations, your decisions, "
        "your mood trends, and your progress over time. "

        "Calculator: math, currency, percentages, "
        "time until deadlines. "

        "Conversations: just talk to me — I can explain anything, "
        "help you study, answer questions, or just chat. "

        "Want me to go deeper on any of these?"
    )


# Keep old name as alias for backward compatibility
what_can_you_do = help_tool


# ---------------------------------------------------------------------------
# 17. Notes — append to existing note
# ---------------------------------------------------------------------------

def append_to_note(query: str, text: str) -> str:
    """
    Find the best matching note and append text with a timestamped separator.
    Backs up the file before writing, updates frontmatter modified field,
    and refreshes the notes index preview.
    """
    import difflib
    index = _read_index()
    if not index:
        return f"No notes found. Save a note first, then I can append to it."

    q = query.lower()

    # Score matches: exact title/project > partial > fuzzy
    def _score(n: dict) -> int:
        title   = n.get("title", "").lower()
        project = n.get("project", "").lower()
        preview = n.get("preview", "").lower()
        if q == title or q == project:                 return 0
        if q in title or q in project:                 return 1
        if q in preview:                               return 2
        ratio = difflib.SequenceMatcher(None, q, title).ratio()
        if ratio > 0.5:                                return 3
        return 99

    ranked = sorted(index, key=_score)
    if _score(ranked[0]) == 99:
        return f"No note found matching '{query}'. Say 'note this' to create one."

    best = ranked[0]
    note_path = BASE_DIR / best["path"]

    try:
        # Backup before writing
        shutil.copy(note_path, note_path.with_suffix(".bak"))

        existing = note_path.read_text(encoding="utf-8")

        # Update modified field in frontmatter if present
        now_str = _now().strftime("%Y-%m-%dT%H:%M:%S")
        if existing.startswith("---"):
            existing = re.sub(
                r'^(modified:\s*)"[^"]*"',
                f'\\1"{now_str}"',
                existing,
                flags=re.MULTILINE,
            )

        # Append with timestamp separator
        ts_label = _now().strftime("%Y-%m-%d %H:%M")
        separator = f"\n\n--- appended {ts_label} ---\n"
        updated = existing.rstrip() + separator + text.strip() + "\n"
        note_path.write_text(updated, encoding="utf-8")

        # Refresh index entry
        for n in index:
            if n["path"] == best["path"]:
                n["modified"] = now_str
                n["preview"]  = (n.get("preview", "") + " " + text)[:120].strip()
        _write_index(index)

        play_sound("done_chime")
        return f"Added to your {best['title']} note."
    except Exception as e:
        return f"Couldn't append to note: {e}"


def open_note_in_editor(query: str) -> str:
    """Open a note in VS Code or Notepad."""
    index = _read_index()
    q = query.lower()
    matches = [n for n in index if q in n.get("title", "").lower()
               or q in n.get("preview", "").lower()]
    if not matches:
        return f"No note found matching '{query}'."
    path = str(BASE_DIR / matches[0]["path"])
    editors = [
        _resolve_app_map("vscode") or "Code",
        _resolve_app_map("notepad++") or "notepad++",
        "notepad",
    ]
    for editor in editors:
        try:
            subprocess.Popen([editor, path])
            return f"Opening '{matches[0]['title']}' in your editor."
        except Exception:
            continue
    return f"Couldn't open an editor. The note is at: {path}"


# ---------------------------------------------------------------------------
# 19. Wellbeing — exercise and water tracking
# ---------------------------------------------------------------------------

def log_exercise(activity: str = "exercised", duration: str = "") -> str:
    wb = _read_json(_p("wellbeing"))
    today = date.today().isoformat()
    # Update today's entry if it exists
    for entry in wb:
        if entry.get("date") == today:
            entry["exercise"] = activity
            if duration:
                entry["exercise_duration"] = duration
            _write_json(_p("wellbeing"), wb)
            return f"Logged: {activity}{' for ' + duration if duration else ''} today."
    # Create new entry
    wb.append({
        "date":              today,
        "mood":              "",
        "energy":            "",
        "sleep":             "",
        "exercise":          activity,
        "exercise_duration": duration,
        "hydration_L":       0,
        "notes":             "",
        "source":            "user-stated",
    })
    _write_json(_p("wellbeing"), wb)
    return f"Logged: {activity}{' for ' + duration if duration else ''} today. Well done!"


_GLASS_TO_LITRES = 0.25   # one standard glass ≈ 250 mL


def parse_hydration_amount(raw: str) -> float:
    """
    Parse a hydration amount string to litres.
    Handles: "2 litres", "1.5L", "8 glasses", "500ml", "2 cups"
    """
    raw = raw.lower().strip()
    m = re.search(r"([\d.]+)", raw)
    if not m:
        return 1.0
    amount = float(m.group(1))
    if any(k in raw for k in ("glass", "cup", "mug")):
        return round(amount * _GLASS_TO_LITRES, 2)
    if "ml" in raw or "millil" in raw:
        return round(amount / 1000, 2)
    return round(amount, 2)   # assume litres


def log_hydration(amount_L: float) -> str:
    wb = _read_json(_p("wellbeing"))
    today = date.today().isoformat()
    for entry in wb:
        if entry.get("date") == today:
            prev = float(entry.get("hydration_L", 0))
            total = round(prev + amount_L, 2)
            entry["hydration_L"] = total
            _write_json(_p("wellbeing"), wb)
            return f"Logged {amount_L} litres of water today. Total: {total} litres."
    wb.append({
        "date":              today,
        "mood":              "",
        "energy":            "",
        "sleep":             "",
        "exercise":          "",
        "exercise_duration": "",
        "hydration_L":       amount_L,
        "notes":             "",
        "source":            "user-stated",
    })
    _write_json(_p("wellbeing"), wb)
    return f"Logged {amount_L} litres of water today."


def check_exercise_streak() -> str:
    """Return a string about exercise frequency this week. Used in briefing."""
    try:
        wb = _read_json(_p("wellbeing"))
        week_ago = (date.today() - timedelta(days=7)).isoformat()
        recent = [e for e in wb if e.get("date", "") >= week_ago]
        exercised_days = sum(1 for e in recent if e.get("exercise", "").strip())
        if exercised_days == 0:
            return "You haven't logged any exercise this week."
        return f"You've exercised {exercised_days} day{'s' if exercised_days != 1 else ''} this week."
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Memory extraction (called after session ends)
# ---------------------------------------------------------------------------

def extract_memory(conversation: list[dict], llm_caller=None) -> None:
    """
    Extract memory from a completed session. Called in background thread.
    Updates sessions.json, long_term.json, decisions.json, followups.json,
    wellbeing_log.json, progress.json, and creates backups.
    """
    if not conversation:
        return

    text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in conversation
    )
    today = date.today().isoformat()
    now = _now().isoformat()

    # Session summary
    summary = "Session completed."
    topics: list[str] = []
    if llm_caller:
        try:
            summary = llm_caller(
                f"In 2 sentences, summarise what was discussed and accomplished:\n{text[:3000]}"
            )
            topics_raw = llm_caller(
                f"List up to 5 topic keywords from this conversation as a JSON array:\n{text[:2000]}"
            )
            topics = json.loads(topics_raw) if topics_raw.startswith("[") else []
        except Exception:
            pass

    sessions = _read_json(_p("sessions"))
    sessions.append({
        "date": today,
        "session_start": now,
        "session_end": _now().isoformat(),
        "topics": topics,
        "summary": summary,
        "mood": "",
        "what_we_worked_on": summary,
        "completed": [],
        "left_unfinished": [],
    })
    _write_json(_p("sessions"), sessions)

    # Long-term facts
    if llm_caller:
        try:
            facts_raw = llm_caller(
                "Extract any personal facts, preferences, or opinions the user revealed. "
                "Return as JSON: [{\"category\": \"preferences|personal|opinions|context\", \"fact\": \"...\"}]\n"
                f"Conversation:\n{text[:3000]}"
            )
            if facts_raw.strip().startswith("["):
                facts = json.loads(facts_raw)
                lt = _read_json(_p("lt_memory"))
                max_facts = CFG.get("memory", {}).get("max_long_term_facts", 20)
                for f in facts:
                    cat = f.get("category", "context")
                    if cat in lt:
                        lt[cat].append({"fact": f["fact"], "source": today, "confidence": "medium"})
                        if len(lt[cat]) > max_facts:
                            lt[cat] = lt[cat][-max_facts:]
                _write_json(_p("lt_memory"), lt)
        except Exception as e:
            logger.warning("Long-term extraction failed: %s", e)

    logger.info("Memory extraction complete for session %s.", today)
