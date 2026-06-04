"""
tray_icon.py — Host process for Jarvis.
Starts 3 threads: wake word, STT/LLM loop, scheduler.
Provides system tray icon, status UI, global hotkey, and Windows startup registration.
"""

import logging
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

import keyboard  # type: ignore
import pystray   # type: ignore
import yaml
from PIL import Image, ImageDraw  # type: ignore

import jarvis
import jarvis_persona as persona
import scheduler
from tts import speak, speak_async

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CFG = _load_cfg()

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_stop_event = threading.Event()
_audio_queue: queue.Queue = queue.Queue()
_paused = False
_status = "Starting"
_last_command = ""
_status_window: tk.Tk | None = None
_status_label: tk.Label | None = None
_command_label: tk.Label | None = None
_profile_var: tk.StringVar | None = None


def _set_status(s: str) -> None:
    global _status
    _status = s
    logger.debug("Status: %s", s)
    if _status_label:
        try:
            _status_label.config(text=f"State: {s}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Tray icon image (generated if no assets/jarvis.ico)
# ---------------------------------------------------------------------------

def _make_icon_image() -> Image.Image:
    ico_path = BASE_DIR / "assets" / "jarvis.ico"
    if ico_path.exists():
        return Image.open(ico_path)
    # Generate a simple blue circle icon
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([4, 4, 60, 60], fill=(0, 120, 215, 255))
    d.text((18, 18), "J", fill="white")
    return img


# ---------------------------------------------------------------------------
# Windows startup registration
# ---------------------------------------------------------------------------

def _register_startup() -> None:
    """Register tray_icon.py and Ollama in Windows Task Scheduler."""
    python_exe = sys.executable
    script = str(BASE_DIR / "tray_icon.py")
    task_name = "JarvisAssistant"

    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", task_name],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return  # Already registered
    except Exception:
        pass

    try:
        cmd = (
            f'schtasks /Create /TN "{task_name}" '
            f'/TR "\\"{python_exe}\\" \\"{script}\\"" '
            f'/SC ONLOGON /RL LIMITED /F'
        )
        subprocess.run(cmd, shell=True, check=True, capture_output=True)
        logger.info("Registered Jarvis in Task Scheduler.")
    except Exception as e:
        logger.warning("Could not register startup task: %s", e)

    # Ollama startup
    ollama_exe = _find_ollama()
    if ollama_exe:
        try:
            ollama_task = "OllamaServer"
            result = subprocess.run(
                ["schtasks", "/Query", "/TN", ollama_task],
                capture_output=True, text=True
            )
            if result.returncode != 0:
                cmd = (
                    f'schtasks /Create /TN "{ollama_task}" '
                    f'/TR "\\"{ollama_exe}\\" serve" '
                    f'/SC ONLOGON /RL LIMITED /F'
                )
                subprocess.run(cmd, shell=True, check=True, capture_output=True)
                logger.info("Registered Ollama in Task Scheduler.")
        except Exception as e:
            logger.warning("Could not register Ollama startup: %s", e)


def _find_ollama() -> str | None:
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


# ---------------------------------------------------------------------------
# Status UI (Tkinter)
# ---------------------------------------------------------------------------

_pom_label: tk.Label | None = None   # Pomodoro live-update label


def _open_status_ui() -> None:
    global _status_window, _status_label, _command_label, _profile_var, _pom_label

    if _status_window and _status_window.winfo_exists():
        _status_window.lift()
        return

    win = tk.Tk()
    win.title("Jarvis Status")
    win.geometry("420x310")
    win.resizable(False, False)
    win.configure(bg="#0a0a0f")

    tk.Label(win, text="JARVIS", fg="#00c8ff", bg="#0a0a0f",
             font=("Courier", 18, "bold")).pack(pady=(16, 4))

    sleep_prefix = "😴 Sleeping  •  " if jarvis.is_sleeping() else ""
    _status_label = tk.Label(
        win,
        text=f"{sleep_prefix}State: {_status}",
        fg="#ffaa00" if jarvis.is_sleeping() else "#c8eaf8",
        bg="#0a0a0f",
        font=("Courier", 11),
    )
    _status_label.pack()

    _command_label = tk.Label(
        win, text=f"Last: {_last_command[:60]}", fg="#5e9ab8", bg="#0a0a0f", font=("Courier", 9)
    )
    _command_label.pack(pady=4)

    # ── Pomodoro live status ─────────────────────────────────────────────────
    tk.Frame(win, bg="#0b1428", height=1).pack(fill="x", padx=20, pady=4)

    _pom_label = tk.Label(
        win,
        text=jarvis.tools.get_pomodoro_status(),
        fg="#ffaa00", bg="#0a0a0f", font=("Courier", 10),
    )
    _pom_label.pack(pady=2)

    # ── Admin warning ────────────────────────────────────────────────────────
    if not _check_admin():
        tk.Label(
            win,
            text="⚠  Not running as admin — site blocking disabled",
            fg="#ffaa00", bg="#0a0a0f", font=("Courier", 8),
        ).pack(pady=(2, 0))

    # ── Profile / version ───────────────────────────────────────────────────
    tk.Label(
        win,
        text=f"Profile: {CFG.get('profile','?')}  |  v{CFG.get('version','?')}",
        fg="#2e5a70", bg="#0a0a0f", font=("Courier", 9),
    ).pack(pady=(2, 0))

    tk.Button(
        win, text="Close", command=win.destroy,
        bg="#0b1428", fg="#00c8ff", relief="flat", font=("Courier", 9)
    ).pack(pady=12)

    # Refresh Pomodoro label every second while window is open
    def _tick():
        if _pom_label and win.winfo_exists():
            _pom_label.config(text=jarvis.tools.get_pomodoro_status())
            win.after(1000, _tick)

    win.after(1000, _tick)

    _status_window = win
    win.mainloop()
    _status_window = None
    _pom_label = None


# ---------------------------------------------------------------------------
# Tray menu actions
# ---------------------------------------------------------------------------

def _pause_resume(icon, item) -> None:
    global _paused
    _paused = not _paused
    if _paused:
        _set_status("Paused")
        speak_async("Paused.")
    else:
        _set_status("Listening")
        speak_async("Resumed.")
    icon.update_menu()


def _switch_profile(profile: str):
    def _do(icon, item):
        result = jarvis.tools.switch_profile(profile)
        speak_async(result)
    return _do


def _toggle_dryrun(icon, item) -> None:
    jarvis.DRY_RUN = not jarvis.DRY_RUN
    state = "on" if jarvis.DRY_RUN else "off"
    speak_async(f"Dry-run mode {state}.")
    icon.update_menu()


def _reload_config(icon, item) -> None:
    global CFG
    CFG = _load_cfg()
    speak_async("Config reloaded.")


def _open_logs(icon, item) -> None:
    log_dir = BASE_DIR / "logs"
    os.startfile(str(log_dir))


def _open_convos(icon, item) -> None:
    convo_dir = BASE_DIR / "logs" / "conversations"
    convo_dir.mkdir(exist_ok=True)
    os.startfile(str(convo_dir))


def _open_status(icon, item) -> None:
    t = threading.Thread(target=_open_status_ui, daemon=True)
    t.start()


def _restart_jarvis(icon, item) -> None:
    speak_async("Restarting systems. One moment.")
    _stop_event.set()
    os.execv(sys.executable, [sys.executable] + sys.argv)


def _quit_jarvis(icon, item) -> None:
    speak_async(persona.shutdown())
    _stop_event.set()
    icon.stop()


def _toggle_sleep(icon, item) -> None:
    if jarvis.is_sleeping():
        response = jarvis.wake_from_sleep(good_morning=False)
        speak_async(response)
    else:
        response = jarvis.go_to_sleep()
        speak_async(response)
    icon.update_menu()


def _build_menu() -> pystray.Menu:
    return pystray.Menu(
        pystray.MenuItem("Status", _open_status),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda item: "Resume Listening" if _paused else "Pause Listening",
            _pause_resume,
        ),
        pystray.MenuItem(
            lambda item: "Wake Jarvis" if jarvis.is_sleeping() else "Sleep Mode",
            _toggle_sleep,
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Switch Profile", pystray.Menu(
            pystray.MenuItem("Study", _switch_profile("study")),
            pystray.MenuItem("Work",  _switch_profile("work")),
            pystray.MenuItem("Chill", _switch_profile("chill")),
        )),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            lambda item: "Disable Dry-run" if jarvis.DRY_RUN else "Enable Dry-run",
            _toggle_dryrun,
        ),
        pystray.MenuItem("Reload Config", _reload_config),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Open Logs", _open_logs),
        pystray.MenuItem("Open Conversations", _open_convos),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Restart Jarvis", _restart_jarvis),
        pystray.MenuItem("Quit", _quit_jarvis),
    )


# ---------------------------------------------------------------------------
# Global hotkey — Ctrl+Shift+J
# ---------------------------------------------------------------------------

def _on_hotkey() -> None:
    global _paused
    if _paused:
        _paused = False
        _set_status("Listening")
        speak_async("Listening.")
    else:
        _paused = True
        _set_status("Paused")
        speak_async("Muted.")


def _quick_note_capture() -> None:
    """
    Ctrl+Shift+N — instant voice note capture without saying 'Jarvis'.
    Flow: wake_chime → listen (STT) → save to notes/quick/ → done_chime → toast.
    Designed for lectures: fast, silent, no wake word needed.
    """
    def _run():
        try:
            import tools as _t
            from tts import play_chime as _chime

            # 1. Wake chime — immediate feedback
            _chime("wake_chime")

            # 2. Record audio
            import sounddevice as sd  # type: ignore
            import numpy as np
            cfg = _load_cfg()
            sr  = cfg.get("sample_rate", 16000)
            dur = 6   # seconds to listen

            audio = sd.rec(sr * dur, samplerate=sr, channels=1, dtype="float32")
            sd.wait()
            flat = audio.flatten()

            # 3. Transcribe via Whisper (reuse jarvis.transcribe_audio)
            try:
                text = jarvis.transcribe_audio(flat, sr)
            except Exception:
                text = ""

            if not text or len(text.strip()) < 3:
                _chime("error_chime")
                return

            # 4. Save directly to notes/quick/ — bypasses LLM and intent router
            result = _t.save_note(text.strip(), folder="quick")
            logger.info("Quick note saved: %s", text[:60])

            # 5. Done chime
            _chime("done_chime")

            # 6. Windows toast notification
            try:
                from winotify import Notification  # type: ignore
                toast = Notification(
                    app_id="Jarvis",
                    title="Note saved",
                    msg=text.strip()[:80],
                    duration="short",
                )
                toast.show()
            except Exception:
                pass

        except Exception as e:
            logger.error("Quick note capture failed: %s", e)

    threading.Thread(target=_run, daemon=True, name="QuickNote").start()


def _on_mute_toggle() -> None:
    """Ctrl+Shift+M — dedicated mute toggle (separate from manual trigger)."""
    global _paused
    _paused = not _paused
    if _paused:
        _set_status("Muted")
    else:
        _set_status("Listening")


def _register_hotkey() -> None:
    cfg = _load_cfg()
    hk  = cfg.get("hotkeys", {})
    trigger_key = hk.get("manual_trigger", "ctrl+shift+j")
    note_key    = hk.get("quick_note",     "ctrl+shift+n")
    mute_key    = hk.get("mute_toggle",    "ctrl+shift+m")

    def _toggle_hud():
        """Ctrl+Shift+H — show/hide the HUD dashboard."""
        try:
            if _dashboard_window:
                _dashboard_window.toggle_visibility()
        except Exception:
            pass

    for key, fn, label in [
        (trigger_key,    _on_hotkey,           "manual trigger"),
        (note_key,       _quick_note_capture,  "quick note"),
        (mute_key,       _on_mute_toggle,      "mute toggle"),
        ("ctrl+shift+h", _toggle_hud,          "toggle HUD"),
    ]:
        try:
            keyboard.add_hotkey(key, fn, suppress=False)
            logger.info("Hotkey registered: %s (%s)", key.upper(), label)
        except Exception as e:
            logger.warning("Could not register hotkey %s (%s): %s", key, label, e)


# ---------------------------------------------------------------------------
# Wake word wrapper (respects pause state)
# ---------------------------------------------------------------------------

def _wake_word_thread_fn() -> None:
    """
    Wraps the wake word listener.
    Respects both _paused (mute/unmute) and jarvis.is_sleeping() (sleep mode).
    In sleep mode, audio still passes through so STT can detect wake phrases
    ("wake up" / "good morning") — jarvis.process_command() handles the rest.
    """
    inner_queue: queue.Queue = queue.Queue()

    ww_thread = threading.Thread(
        target=jarvis.wake_word_listener,
        args=(inner_queue, _stop_event, _set_status),
        daemon=True,
        name="WakeWordInner",
    )
    ww_thread.start()

    while not _stop_event.is_set():
        try:
            audio = inner_queue.get(timeout=0.5)
            if _paused:
                continue
            # Sleep mode: still forward audio so wake phrases can be detected
            _audio_queue.put(audio)
        except queue.Empty:
            pass


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _check_admin() -> bool:
    """Return True if Jarvis is running with administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def main() -> None:
    # ── Admin rights check ───────────────────────────────────────────────────
    _is_admin = _check_admin()
    if not _is_admin:
        logger.warning(
            "Jarvis is NOT running as administrator. "
            "Site blocking (Study Mode) will fail. "
            "Right-click tray_icon.py → Run as administrator to enable it."
        )
        # Speak the warning after TTS is ready (give it 5 s to load)
        def _admin_warn():
            import time as _t
            _t.sleep(5)
            speak_async(
                "Warning: I'm not running as administrator. "
                "I can't block distracting websites in study mode. "
                "Please restart me as administrator to enable that feature."
            )
        threading.Thread(target=_admin_warn, daemon=True).start()
    else:
        logger.info("Running as administrator — site blocking enabled.")

    _register_startup()
    _register_hotkey()
    scheduler.set_speak(speak)

    # Wire voice "stop/quit/goodbye" → tray quit (icon not created yet,
    # so we store a deferred lambda that closes the icon once it exists)
    _icon_ref: list = []
    def _voice_quit():
        _stop_event.set()
        if _icon_ref:
            _icon_ref[0].stop()
    jarvis.set_quit_callback(_voice_quit)
    jarvis.set_sleep_status_callback(_set_status)

    # Wire proactive engine
    try:
        import proactive_engine
        proactive_engine.set_speak(speak)
        proactive_engine.set_llm(jarvis.llm_caller)
    except Exception as e:
        logger.warning("Proactive engine setup failed: %s", e)

    # Wire meeting mode (speak, llm, status callback)
    try:
        import meeting_mode as _mm
        _mm.set_speak(speak)
        _mm.set_llm(jarvis.llm_caller)
        _mm.set_status_callback(_set_status)
    except Exception as e:
        logger.warning("Meeting mode setup failed: %s", e)

    # Patch speak_async to record last speak time for proactive engine
    _orig_speak_async = speak_async.__wrapped__ if hasattr(speak_async, "__wrapped__") else None
    try:
        import tts as _tts
        _orig_sa = _tts.speak_async
        def _wrapped_sa(text, voice=None, rate=None):
            proactive_engine.record_jarvis_spoke()
            _orig_sa(text, voice=voice, rate=rate)
        _tts.speak_async = _wrapped_sa
    except Exception:
        pass

    # Auto-index notes into RAG on first run (background)
    def _bg_index():
        import time as _t
        _t.sleep(30)   # let everything else start first
        try:
            from rag_tool import index_all
            index_all()
        except Exception as e:
            logger.debug("Background RAG indexing: %s", e)
    import threading as _th
    _th.Thread(target=_bg_index, daemon=True, name="RAGIndex").start()

    # Load plugins from plugins/ directory
    try:
        from plugin_loader import load_plugins
        load_plugins()
    except Exception as e:
        logger.warning("Plugin loading failed: %s", e)

    # Start focus tracking
    try:
        from focus_tool import start_focus_tracking
        start_focus_tracking()
    except Exception as e:
        logger.warning("Focus tracking failed to start: %s", e)

    # Thread 1: Wake word
    ww_thread = threading.Thread(
        target=_wake_word_thread_fn,
        daemon=True,
        name="WakeWord",
    )
    ww_thread.start()

    # Thread 2: STT + LLM loop
    stt_thread = threading.Thread(
        target=jarvis.stt_llm_loop,
        args=(_audio_queue, _stop_event, _set_status),
        daemon=True,
        name="STT_LLM",
    )
    stt_thread.start()

    # Thread 3: Scheduler
    scheduler.start_scheduler_thread(_stop_event)

    # Tray icon (runs on main thread — required by pystray on Windows)
    icon = pystray.Icon(
        "Jarvis",
        _make_icon_image(),
        "Jarvis",
        menu=_build_menu(),
    )
    _icon_ref.append(icon)   # allow voice quit to stop the icon

    logger.info("Jarvis tray icon running.")
    # Time-aware greeting (replaces static startup line)
    try:
        greeting = jarvis.speak_startup_greeting()
        speak_async(greeting)
    except Exception:
        speak_async(persona.startup())

    # Whisper pre-warm in background — shows "⏳ Loading..." then "✅ Listening"
    def _prewarm_status(msg: str) -> None:
        _set_status(msg)
        if _status_label:
            try:
                _status_label.config(text=f"State: {msg}")
            except Exception:
                pass

    threading.Thread(
        target=jarvis.prewarm_whisper,
        args=(_prewarm_status,),
        daemon=True,
        name="WhisperPrewarm",
    ).start()

    # Auto startup briefing — reads from config briefing section
    br_cfg = CFG.get("briefing", CFG.get("startup_briefing", {}))  # backward compat
    auto   = br_cfg.get("auto_on_startup", br_cfg.get("enabled", True))
    if auto:
        delay = int(br_cfg.get("startup_delay_seconds", br_cfg.get("delay_seconds", 60)))

        def _delayed_briefing():
            import time as _t
            _t.sleep(delay)
            logger.info("Startup briefing firing after %d s delay.", delay)
            import tools as _tools
            speak(_tools.morning_briefing())

        threading.Thread(target=_delayed_briefing, daemon=True,
                         name="StartupBriefing").start()
        logger.info("Startup briefing scheduled in %d seconds.", delay)

    # ── Launch PyQt6 dashboard (must run on main thread alongside pystray) ──
    # We run the Qt event loop in a background thread and pystray on main.
    # Qt requires the QApplication to be on the thread that calls exec(),
    # so we start Qt in its own thread with a thread-safe flag.
    _dashboard_window = None
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QFont

        _qt_app = QApplication.instance() or QApplication(sys.argv)
        _qt_app.setApplicationName("Jarvis")

        # Choose UI mode from config
        ui_mode = CFG.get("ui", {}).get("mode", "hud")

        if ui_mode == "hud":
            from ui.hud_dashboard import (
                JarvisHUD as _DashClass,
                wire_jarvis_signals, start_file_watcher, _load_stylesheet
            )
            _qt_app.setStyleSheet(_load_stylesheet())
            _qt_app.setFont(QFont("Share Tech Mono", 10))
        else:
            from ui.dashboard import (
                JarvisDashboard as _DashClass,
                wire_jarvis_signals, start_file_watcher, _load_stylesheet
            )
            _qt_app.setStyleSheet(_load_stylesheet())
            _qt_app.setFont(QFont("Segoe UI", 11))

        _dashboard_window = _DashClass()
        _dashboard_window.show()
        wire_jarvis_signals()
        _file_watcher = start_file_watcher()

        # Add "Open Dashboard" to tray left-click
        def _left_click_handler(icon_obj, button):
            if str(button) == "Button.left":
                _dashboard_window.toggle_visibility()

        icon.run_detached()    # run pystray in its own thread
        _qt_app.exec()         # Qt event loop on main thread

    except ImportError:
        logger.warning("PyQt6 not installed — dashboard unavailable. Run: pip install PyQt6")
        icon.run()             # fallback: just run tray without dashboard
    except Exception as e:
        logger.error("Dashboard failed to launch: %s", e)
        icon.run()

    # Cleanup on exit
    _stop_event.set()
    logger.info("Jarvis shut down.")


if __name__ == "__main__":
    main()
