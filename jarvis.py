"""
jarvis.py — Core Jarvis AI loop.
Handles: session context, STT, intent routing, LLM, TTS, transcripts, memory extraction.
"""

import json
import logging
import logging.handlers
import os
import queue
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable

import yaml

# ---------------------------------------------------------------------------
# Logging setup (must happen before other imports that use logging)
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


CFG = _load_cfg()
_LOG_PATH = BASE_DIR / CFG["paths"]["logs"]
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

_handler = logging.handlers.RotatingFileHandler(
    _LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
)
_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
_console = logging.StreamHandler()
_console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

logging.basicConfig(
    level=getattr(logging, CFG.get("log_level", "info").upper(), logging.INFO),
    handlers=[_handler, _console],
)
logger = logging.getLogger(__name__)

import tools
import intent_router
import jarvis_persona as persona
from tts import (speak, speak_async, is_speaking as tts_is_speaking,
                  set_tts_language, get_tts_language,
                  adjust_volume, adjust_rate, play_chime)
from setup_models import run_first_launch_setup

# ---------------------------------------------------------------------------
# Quit callback
# ---------------------------------------------------------------------------

_quit_callback = None

def set_quit_callback(fn) -> None:
    global _quit_callback
    _quit_callback = fn

def request_quit() -> None:
    if _quit_callback:
        _quit_callback()


# ---------------------------------------------------------------------------
# Admin rights check
# ---------------------------------------------------------------------------

def is_admin() -> bool:
    """Return True if Jarvis is running with administrator privileges."""
    try:
        import ctypes
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


_admin = is_admin()
if not _admin:
    logger.warning(
        "Jarvis is NOT running as administrator. "
        "Site blocking (Study Mode) will fail. "
        "Right-click tray_icon.py → Run as administrator to enable it."
    )

# ---------------------------------------------------------------------------
# Language management
# ---------------------------------------------------------------------------

_lang_cfg = CFG.get("language", {})
_session_language: str = _lang_cfg.get("default", "en")
_auto_detect: bool = _lang_cfg.get("auto_detect", True)
_last_whisper_lang: str = "en"   # updated after each STT call

_LANG_NAMES = {"en": "English", "de": "German", "fr": "French",
               "es": "Spanish", "it": "Italian", "nl": "Dutch"}

_CONFIRM_MSGS = {
    "de": "Okay, ich antworte jetzt auf Deutsch.",
    "en": "Switching back to English.",
    "fr": "Bien sûr, je réponds maintenant en français.",
    "es": "De acuerdo, ahora respondo en español.",
}


# ---------------------------------------------------------------------------
# Timezone
# ---------------------------------------------------------------------------

def _local_now() -> datetime:
    """Return current datetime in the configured timezone."""
    tz_name = CFG.get("timezone", "Europe/Berlin")
    try:
        import zoneinfo
        tz = zoneinfo.ZoneInfo(tz_name)
        return datetime.now(tz)
    except Exception:
        return datetime.now()


# ---------------------------------------------------------------------------
# Sleep mode
# ---------------------------------------------------------------------------

_sleep_mode = False
_sleep_status_callback = None   # injected by tray_icon.py


def is_sleeping() -> bool:
    return _sleep_mode


def set_sleep_status_callback(fn) -> None:
    global _sleep_status_callback
    _sleep_status_callback = fn


def go_to_sleep() -> str:
    global _sleep_mode
    _sleep_mode = True
    logger.info("Jarvis entering sleep mode.")

    # Pause scheduler so no reminders/check-ins fire overnight
    try:
        import scheduler as _sched
        _sched.set_paused(True)
    except Exception:
        pass

    tools.play_sound("done_chime")
    if _sleep_status_callback:
        _sleep_status_callback("Sleeping")

    return "Going to sleep. Say 'Jarvis, wake up' to resume."


def wake_from_sleep(good_morning: bool = False) -> str:
    global _sleep_mode
    _sleep_mode = False
    logger.info("Jarvis waking from sleep mode.")

    # Resume scheduler
    try:
        import scheduler as _sched
        _sched.set_paused(False)
    except Exception:
        pass

    play_chime("wake_chime")
    if _sleep_status_callback:
        _sleep_status_callback("Listening")

    try:
        mem = tools._read_json(tools._p("memory"))
        name = mem.get("name", "Samaira").split()[0]
    except Exception:
        name = "Samaira"

    if good_morning:
        return f"Good morning, {name}. Would you like your morning briefing?"
    return f"Good morning, {name}. Systems restored."


# ---------------------------------------------------------------------------
# Repeat last response
# ---------------------------------------------------------------------------

_last_spoken_response: str = ""


def repeat_last() -> str:
    if not _last_spoken_response:
        return "I haven't said anything yet."
    return _last_spoken_response


# ---------------------------------------------------------------------------
# New session
# ---------------------------------------------------------------------------

def start_new_session() -> str:
    """
    End the current session cleanly and start fresh:
    1. Flush transcript to disk
    2. Run extract_memory() in background
    3. Clear conversation history (RAM)
    4. Reset last_response and Pomodoro cycle count
    5. Start a new transcript entry
    6. Play chime + speak confirmation
    """
    global _last_spoken_response

    # 1. Save transcript
    _flush_transcript()

    # 2. Extract memory from current session in background
    if _history:
        threading.Thread(
            target=tools.extract_memory,
            args=(list(_history), llm_caller),
            daemon=True,
            name="MemoryExtraction",
        ).start()

    # 3. Clear history
    clear_history()

    # 4. Reset state
    _last_spoken_response = ""
    try:
        tools._pom_total_today = 0
        tools._pom_cycle_in_set = 0
    except Exception:
        pass

    # 5. Fresh transcript
    _init_transcript()

    logger.info("New session started by user request.")

    # 6. Chime + confirm
    play_chime("wake_chime")
    return "Starting fresh. What are we working on?"


def get_language() -> str:
    return _session_language


def set_language(lang: str) -> str:
    """Switch session language and TTS voice. Returns confirmation string."""
    global _session_language
    _session_language = lang
    set_tts_language(lang)
    logger.info("Language switched to: %s", lang)
    return _CONFIRM_MSGS.get(lang, f"Switched to {_LANG_NAMES.get(lang, lang)}.")


def language_status() -> str:
    lang = _session_language
    return f"I'm currently speaking {_LANG_NAMES.get(lang, lang)}."


def _maybe_translate(text: str) -> str:
    """
    Translate fast-path tool responses into the current session language.
    LLM responses are already in the right language (system prompt handles it).
    Only translates when language is not English.
    """
    if not text or _session_language == "en":
        return text
    lang_name = _LANG_NAMES.get(_session_language, _session_language)
    # Use fast model for translation — simpler task doesn't need llama3
    translated = _fast_llm_caller(
        f"Translate only the following text to {lang_name}. "
        f"Output only the translation, nothing else:\n\n{text}"
    )
    return translated if translated and "offline" not in translated.lower() else text

# First-launch: download wake word model before any thread starts
run_first_launch_setup()

# Inject speak into Pomodoro so it can announce phase transitions
tools.set_pomodoro_speak(speak_async)


# ---------------------------------------------------------------------------
# Time-aware startup greeting
# ---------------------------------------------------------------------------

def speak_startup_greeting() -> str:
    """Return a time-appropriate startup greeting."""
    try:
        mem  = tools._read_json(tools._p("memory"))
        name = mem.get("name", "Samaira").split()[0]
    except Exception:
        name = "Samaira"

    hour    = datetime.now().hour
    profile = CFG.get("profile", "study").upper()

    if 6 <= hour < 12:
        greeting = "Good morning"
    elif 12 <= hour < 18:
        greeting = "Good afternoon"
    elif 18 <= hour < 24:
        greeting = "Good evening"
    else:
        greeting = "You're up late"

    return (
        f"System online. {greeting}, {name}. "
        f"Profile: {profile}. All systems nominal."
    )


# ---------------------------------------------------------------------------
# Whisper pre-warm
# ---------------------------------------------------------------------------

def prewarm_whisper(status_callback=None) -> None:
    """
    Load the Whisper model into memory with a silent transcription.
    Run in a background daemon thread so the tray appears immediately.
    """
    if status_callback:
        status_callback("Loading Whisper...")
    try:
        import numpy as np

        w_cfg     = CFG.get("whisper", {})
        lang_hint = None if w_cfg.get("language", "auto") == "auto" else w_cfg["language"]

        model = _get_whisper_model()   # uses singleton
        dummy = np.zeros(16000, dtype=np.float32)
        segments, _ = model.transcribe(dummy, language=lang_hint)
        list(segments)   # consume generator to force full load

        logger.info("Whisper model pre-warmed — ready for voice input.")
        if status_callback:
            status_callback("Listening")
        play_chime("wake_chime")
        speak_async("Ready.")
    except Exception as e:
        logger.warning("Whisper pre-warm failed (will load on first use): %s", e)
        if status_callback:
            status_callback("Listening")

# ---------------------------------------------------------------------------
# Version banner
# ---------------------------------------------------------------------------

VERSION = CFG.get("version", "0.1.0")
PROFILE = CFG.get("profile", "study")
DRY_RUN = CFG.get("dry_run", False)

logger.info("Jarvis v%s starting — profile: %s, dry_run: %s", VERSION, PROFILE, DRY_RUN)

# ---------------------------------------------------------------------------
# Conversation history
# ---------------------------------------------------------------------------

MAX_TURNS = CFG.get("max_turns", 20)
_history: list[dict] = []


def _append_turn(role: str, content: str) -> None:
    _history.append({"role": role, "content": content})
    if len(_history) > MAX_TURNS * 2:
        _history[:] = _history[-(MAX_TURNS * 2):]


def get_history() -> list[dict]:
    return list(_history)


def clear_history() -> None:
    _history.clear()


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------

def _build_system_prompt() -> str:
    template_path = BASE_DIR / CFG["paths"]["prompts"]
    try:
        template = template_path.read_text(encoding="utf-8")
    except Exception:
        template = "You are Jarvis, a local AI assistant."

    try:
        mem = tools._read_json(tools._p("memory"))
    except Exception:
        mem = {}

    # Long-term facts
    lt_facts = tools.get_long_term_facts()

    # Last session
    try:
        sessions = tools._read_json(tools._p("sessions"))
        last = sessions[-1] if sessions else {}
        last_date = last.get("date", "no previous session")
        last_summary = last.get("summary", "No summary available.")
    except Exception:
        last_date = "no previous session"
        last_summary = "No summary available."

    # Goals
    try:
        goals_data = tools._read_json(tools._p("goals"))
        lt = goals_data.get("long_term", [])
        st = goals_data.get("short_term", [])
        goals_str = "; ".join(
            f"{g['goal']} ({g.get('progress', 0)}%)"
            for g in lt + st
        )
    except Exception:
        goals_str = "No goals set."

    profile_notes = {
        "study": "study: ultra-brief answers, no small talk, focus reminders",
        "work":  "work: balanced, professional, task-focused",
        "chill": "chill: conversational, warmer, longer answers allowed",
    }.get(PROFILE, "")

    replacements = {
        "{name}":                 mem.get("name", "User"),
        "{location}":             mem.get("location", "Unknown"),
        "{uni}":                  mem.get("uni", "Unknown"),
        "{projects}":             ", ".join(mem.get("projects", [])),
        "{preferences}":          str(mem.get("preferences", {})),
        "{long_term_facts}":      lt_facts,
        "{last_session_date}":    last_date,
        "{last_session_summary}": last_summary,
        "{goals_and_progress}":   goals_str,
        "{language}":             mem.get("preferences", {}).get("language", "English"),
        "{expiry_warning_days}":  str(CFG.get("expiry_warning_days", 2)),
    }
    for key, val in replacements.items():
        template = template.replace(key, val)

    if PROFILE:
        template += f"\n\nActive profile: {profile_notes}"
    if DRY_RUN:
        template += "\n\nDRY-RUN MODE IS ACTIVE. Do not execute any tools."

    return template


# ---------------------------------------------------------------------------
# LLM (Ollama)
# ---------------------------------------------------------------------------

_llm_lock = threading.Lock()
_llm_queue: queue.Queue = queue.Queue()
_ollama_restart_attempts = 0
_MAX_OLLAMA_RESTARTS = 2


def _try_restart_ollama() -> bool:
    """Attempt to restart the Ollama process. Returns True if successful."""
    global _ollama_restart_attempts
    if _ollama_restart_attempts >= _MAX_OLLAMA_RESTARTS:
        return False
    try:
        import subprocess as _sub
        _sub.Popen(
            ["ollama", "serve"],
            creationflags=_sub.CREATE_NO_WINDOW if hasattr(_sub, "CREATE_NO_WINDOW") else 0,
        )
        _ollama_restart_attempts += 1
        logger.info("Ollama restart attempted (%d/%d).", _ollama_restart_attempts, _MAX_OLLAMA_RESTARTS)
        import time as _t
        _t.sleep(8)   # give Ollama 8s to start
        return True
    except Exception as e:
        logger.error("Ollama restart failed: %s", e)
        return False


def _call_ollama(prompt: str, system: str | None = None) -> str:
    """
    Call Ollama with a single prompt. Thread-safe with a lock.
    Automatically attempts to restart Ollama on connection failure.
    """
    global _ollama_restart_attempts
    try:
        import ollama as ol  # type: ignore
    except ImportError:
        return "Ollama client not installed."

    with _llm_lock:
        try:
            # Context overflow protection — if history is very long, summarise
            # older turns to stay within the model's context window.
            history_to_send = list(_history)
            ctx_limit = CFG.get("context_length", 4096)
            total_chars = sum(len(t["content"]) for t in history_to_send)
            # Rough estimate: 1 token ≈ 4 chars; keep headroom for system+prompt
            if total_chars > ctx_limit * 3:
                # Keep last 6 turns, summarise the rest
                older = history_to_send[:-6]
                recent = history_to_send[-6:]
                if older:
                    try:
                        import ollama as _ol  # type: ignore
                        summary_resp = _ol.chat(
                            model=CFG.get("model", "llama3"),
                            messages=[
                                {"role": "system", "content": "Summarise this conversation in 3 sentences."},
                                *older,
                            ],
                            options={"num_ctx": ctx_limit},
                        )
                        summary = summary_resp["message"]["content"].strip()
                        history_to_send = [
                            {"role": "assistant", "content": f"[Earlier summary: {summary}]"},
                            *recent,
                        ]
                        logger.info("Context overflow: summarised %d older turns.", len(older))
                    except Exception as e:
                        logger.warning("Context summarisation failed: %s", e)
                        history_to_send = recent   # just drop oldest if summarise fails

            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            for turn in history_to_send:
                messages.append(turn)
            messages.append({"role": "user", "content": prompt})

            t0 = datetime.now()
            response = ol.chat(
                model=CFG.get("model", "llama3"),
                messages=messages,
                options={"num_ctx": CFG.get("context_length", 4096)},
            )
            elapsed = int((datetime.now() - t0).total_seconds() * 1000)
            reply = response["message"]["content"].strip()
            tokens = response.get("eval_count", "?")
            logger.info("LLM response: %d ms, ~%s tokens.", elapsed, tokens)
            return reply
        except Exception as e:
            err  = str(e).lower()
            full = repr(e)
            logger.error("Ollama error: %s", e)
            model_name = CFG.get("model", "llama3")

            # Ollama process not running — try auto-restart
            if any(k in err for k in ("connection", "refused", "connect", "unreachable",
                                       "timeout", "network", "cannot connect")):
                tools.play_sound("error_chime")
                if _ollama_restart_attempts < _MAX_OLLAMA_RESTARTS:
                    speak_async("I've lost my connection. Restarting Ollama, one moment.")
                    if _try_restart_ollama():
                        # Retry once after restart
                        try:
                            response = ol.chat(
                                model=CFG.get("model", "llama3"),
                                messages=messages,
                                options={"num_ctx": CFG.get("context_length", 4096)},
                            )
                            _ollama_restart_attempts = 0   # reset on success
                            return response["message"]["content"].strip()
                        except Exception:
                            pass
                return (
                    "Ollama isn't responding. Please restart it manually. "
                    "Basic tools like tasks, reminders, and fridge still work."
                )

            # Model not downloaded — 404 from Ollama API or explicit "not found"
            if any(k in err for k in ("not found", "pull", "doesn't exist",
                                       "no such model", "model not found", "404")):
                return (
                    f"The {model_name} model isn't downloaded yet. "
                    f"Please run: ollama pull {model_name}"
                )

            # Unknown Ollama error — fall back to generic offline message
            return persona.llm_offline()


def llm_caller(prompt: str) -> str:
    """Used by tools that need an LLM call (recipe, clipboard, etc.)."""
    return _call_ollama(prompt)


def _fast_llm_caller(prompt: str) -> str:
    """
    Use the fast model if configured, else fall back to primary.
    Used for tool-result translation, summarisation, keyword extraction, etc.
    """
    fast = CFG.get("fast_model", "").strip()
    if not fast:
        return _call_ollama(prompt)
    try:
        import ollama as ol  # type: ignore
        resp = ol.chat(
            model=fast,
            messages=[{"role": "user", "content": prompt}],
            options={"num_ctx": 2048},
        )
        return resp["message"]["content"].strip()
    except Exception:
        return _call_ollama(prompt)   # fall back


# ---------------------------------------------------------------------------
# STT — faster-whisper (singleton model, loaded once)
# ---------------------------------------------------------------------------

_whisper_model = None
_whisper_model_lock = threading.Lock()
_VAD_ENERGY_THRESHOLD = 0.002   # RMS below this = silence, skip Whisper


def _get_whisper_model():
    """
    Return the cached WhisperModel, creating it on first call.
    After the model is downloaded once, we pass local_files_only=True
    to skip HuggingFace metadata HTTP requests on every startup —
    this eliminates the 1-2 second network delay per transcription.
    """
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model
    with _whisper_model_lock:
        if _whisper_model is not None:
            return _whisper_model
        w_cfg      = CFG.get("whisper", {})
        model_size = w_cfg.get("model_size", "base")
        device     = w_cfg.get("device", "cpu")
        compute    = w_cfg.get("compute_type", "float16" if device == "cuda" else "int8")
        from faster_whisper import WhisperModel  # type: ignore

        logger.info("Loading WhisperModel (%s / %s / %s)…", model_size, device, compute)

        # Try local-only first (no HF network call — fast)
        try:
            import os
            os.environ.setdefault("HF_HUB_OFFLINE", "1")   # suppress metadata checks
            _whisper_model = WhisperModel(
                model_size, device=device, compute_type=compute,
                local_files_only=True,
            )
        except Exception:
            # First-ever download: allow network, then cache
            os.environ.pop("HF_HUB_OFFLINE", None)
            _whisper_model = WhisperModel(model_size, device=device, compute_type=compute)
            os.environ["HF_HUB_OFFLINE"] = "1"   # lock offline from now on

        logger.info("WhisperModel ready (offline mode).")
    return _whisper_model


def _audio_rms(audio) -> float:
    """Return root-mean-square energy of a numpy float32 array."""
    import numpy as np
    arr = np.asarray(audio, dtype=np.float32)
    return float(np.sqrt(np.mean(arr ** 2)))


def transcribe_audio(audio_data, sample_rate: int = 16000) -> str:
    """
    Transcribe audio using faster-whisper.
    - Reuses cached WhisperModel (no reload penalty).
    - Skips Whisper entirely if audio energy is below VAD threshold.
    """
    global _last_whisper_lang
    try:
        import numpy as np

        if not isinstance(audio_data, np.ndarray):
            import io
            import soundfile as sf
            audio_data, _ = sf.read(io.BytesIO(audio_data), dtype="float32")

        # Voice activity detection — skip silence
        if _audio_rms(audio_data) < _VAD_ENERGY_THRESHOLD:
            logger.debug("VAD: audio energy too low — skipping Whisper.")
            return ""

        model     = _get_whisper_model()
        lang_hint = None if _auto_detect else _session_language
        segments, info = model.transcribe(audio_data, language=lang_hint)
        text = " ".join(seg.text for seg in segments).strip()

        if _auto_detect and info and info.language:
            _last_whisper_lang = info.language
            logger.debug("Whisper detected language: %s (prob=%.2f)",
                         info.language, getattr(info, "language_probability", 0))

        return text
    except Exception as e:
        logger.error("STT error: %s", e)
        return ""


# ---------------------------------------------------------------------------
# Transcript writer
# ---------------------------------------------------------------------------

def _convo_log_path() -> Path:
    convo_dir = BASE_DIR / CFG["paths"]["convos"]
    convo_dir.mkdir(parents=True, exist_ok=True)
    return convo_dir / f"{date.today().isoformat()}.md"


_transcript_lines: list[str] = []
_session_start_time = datetime.now()


def _init_transcript() -> None:
    global _session_start_time
    _session_start_time = datetime.now()
    _transcript_lines.clear()
    _transcript_lines.append(
        f"\n---\ndate: {date.today().isoformat()}\n"
        f"session_start: {_session_start_time.strftime('%H:%M:%S')}\n---\n"
    )


def _log_turn(role: str, text: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    label = "YOU" if role == "user" else "JARVIS"
    _transcript_lines.append(f"[{ts}] {label}: {text}")


def _flush_transcript() -> None:
    if not CFG.get("save_transcripts", True):
        return
    path = _convo_log_path()
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(_transcript_lines) + "\n")
    _transcript_lines.clear()


# ---------------------------------------------------------------------------
# Low-power / resource guardrails
# ---------------------------------------------------------------------------

def _is_low_power() -> bool:
    mode = CFG.get("low_power_mode", "auto")
    if mode is True:
        return True
    if mode == "auto":
        try:
            import psutil
            bat = psutil.sensors_battery()
            return bat is not None and not bat.power_plugged
        except Exception:
            return False
    return False


# ---------------------------------------------------------------------------
# Main process — single voice exchange
# ---------------------------------------------------------------------------

def process_command(user_text: str, status_callback: Callable | None = None) -> str:
    """
    Given transcribed user text:
    1. Try intent router (fast path)
    2. Fall back to LLM
    3. Speak and log the response.
    Returns response string.
    """
    global _last_spoken_response

    if not user_text.strip():
        return ""

    # Strip wake word variants that Whisper often mangles
    # e.g. "Hey Jarvis, ..." / "Pajawis ..." / "Jarlispear ..."
    import re as _re
    _WW = _re.compile(
        r'^(hey\s+)?(jarvis|jarvise|jarviss|jarliss|jarlispear|javed|pajawis|javis|jarves|j[ao]r[bvw]is)\b[,.\s]*',
        _re.IGNORECASE,
    )
    user_text = _WW.sub("", user_text).strip()
    if not user_text:
        return ""

    # Apply user-defined STT corrections (e.g. "style mate" → "StyleMate")
    try:
        from language_learning_tool import apply_corrections
        user_text = apply_corrections(user_text)
    except Exception:
        pass

    logger.info("STT result: %s", user_text)

    if status_callback:
        status_callback("Processing")

    # In sleep mode — only wake phrases pass through
    if _sleep_mode:
        if re.search(r"\bgood\s+morning\b", user_text, re.I):
            response = wake_from_sleep(good_morning=True)
            speak_async(response)
            return response
        if re.search(r"\bwake\s+up\b", user_text, re.I):
            response = wake_from_sleep(good_morning=False)
            speak_async(response)
            return response
        return ""

    # "Yes" after a good-morning briefing offer
    import re as _re2
    if _re2.search(r"^\s*(yes|yeah|sure|go\s+ahead|please)\s*$", user_text, _re2.I):
        if _last_spoken_response and "briefing" in _last_spoken_response.lower():
            response = tools.morning_briefing()
            _append_turn("assistant", response)
            _log_turn("assistant", response)
            speak_async(response)
            return response

    # Auto-detect language from Whisper and switch if needed
    if _auto_detect and _last_whisper_lang and _last_whisper_lang != _session_language:
        # Only switch for supported languages
        if _last_whisper_lang in _lang_cfg.get("tts_voice_en", "") or \
           _last_whisper_lang in ("en", "de", "fr", "es", "it", "nl"):
            logger.info("Auto-switching language: %s → %s",
                        _session_language, _last_whisper_lang)
            set_language(_last_whisper_lang)

    if _is_low_power():
        logger.info("Low power mode active.")

    _append_turn("user", user_text)
    _log_turn("user", user_text)

    # Dry-run passthrough
    if DRY_RUN:
        response = f"I would handle '{user_text}' now, but dry-run mode is on."
        _append_turn("assistant", response)
        _log_turn("assistant", response)
        speak_async(response)
        return response

    # Fast-path routing
    from_fast_path = True
    response = intent_router.route(user_text, llm_caller=llm_caller)

    # LLM fallback — already responds in the right language via system prompt
    if response is None:
        from_fast_path = False
        system = _build_system_prompt()
        response = _call_ollama(user_text, system=system)

    # Translate fast-path tool responses when not speaking English
    if from_fast_path and _session_language != "en":
        response = _maybe_translate(response)

    _last_spoken_response = response

    _append_turn("assistant", response)
    _log_turn("assistant", response)

    if status_callback:
        status_callback("Speaking")
    speak_async(response)

    return response


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------

def start_session() -> None:
    """Called when Jarvis starts listening for the first time."""
    _init_transcript()
    logger.info("Session started.")

    # First-run voice setup (blocking — must finish before normal operation)
    try:
        from first_run import run_first_run_setup
        run_first_run_setup(
            speak_fn=speak,
            chime_fn=lambda: play_chime("wake_chime"),
        )
    except Exception as e:
        logger.warning("First-run setup failed: %s", e)

    # Open follow-ups reminder
    if CFG.get("memory", {}).get("followup_reminder", True):
        try:
            fups = tools._read_json(tools._p("followups"))
            open_fups = [f for f in fups if not f.get("done")]
            if open_fups:
                speak_async(f"Reminder: you have {len(open_fups)} open follow-up(s).")
        except Exception:
            pass


def end_session(status_callback: Callable | None = None) -> None:
    """Called when session ends (tray quit, etc.)"""
    _flush_transcript()

    if CFG.get("memory", {}).get("extract_after_session", True) and _history:
        speak_async("Session archived. Memory consolidation underway in the background.")
        t = threading.Thread(
            target=tools.extract_memory,
            args=(list(_history), llm_caller),
            daemon=True,
            name="MemoryExtraction",
        )
        t.start()

    logger.info("Session ended.")


# ---------------------------------------------------------------------------
# Wake word listener thread
# ---------------------------------------------------------------------------

def wake_word_listener(audio_queue: queue.Queue, stop_event: threading.Event,
                       status_callback: Callable | None = None) -> None:
    """
    Runs in a dedicated daemon thread.
    Listens for 'jarvis' wake word via openWakeWord,
    then pushes audio chunk to audio_queue for STT.
    Survives crashes — restarts on any exception.
    """
    ww_cfg      = CFG.get("wake_word", {})
    sensitivity = ww_cfg.get("sensitivity", CFG.get("wake_word_sensitivity", 0.5))
    sample_rate = CFG.get("sample_rate", 16000)
    mic_index   = CFG.get("mic_device_index", None)
    if isinstance(mic_index, str) and mic_index.lower() == "auto":
        mic_index = None

    # OWW loads models by NAME from its own resources/models/ directory.
    # setup_models.py ensures the file is placed there before we start.
    oww_model_name = "hey_jarvis"

    # Verify the model is actually present before entering the loop.
    from setup_models import get_oww_model_path
    if get_oww_model_path() is None:
        logger.error(
            "Wake word model not found in openWakeWord resources — "
            "wake word detection disabled. Run setup_models.py to fix."
        )
        if status_callback:
            status_callback("No wake word model")
        return   # exit thread cleanly — do NOT restart

    while not stop_event.is_set():
        try:
            import numpy as np
            import sounddevice as sd
            from openwakeword.model import Model  # type: ignore

            oww = Model(wakeword_models=[oww_model_name], inference_framework="onnx")

            # Get the actual prediction buffer key OWW assigned (may include version suffix)
            model_key = next(iter(oww.prediction_buffer.keys()), oww_model_name)
            logger.info(
                "Wake word listener ready — model: %s, key: %s, sensitivity: %.2f.",
                oww_model_name, model_key, sensitivity,
            )

            if status_callback:
                status_callback("Listening")

            chunk_size = 1280  # ~80ms at 16kHz
            audio_buffer = []
            cooldown_until = datetime.min   # no trigger before this time

            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype="int16",
                device=mic_index,
                blocksize=chunk_size,
            ) as stream:
                while not stop_event.is_set():
                    chunk, _ = stream.read(chunk_size)
                    flat = chunk.flatten().astype(np.int16)

                    oww.predict(flat)
                    scores = oww.prediction_buffer.get(model_key, [0])
                    score = scores[-1] if scores else 0

                    audio_buffer.append(flat)
                    # Keep ~3 seconds of pre-wake audio for context
                    if len(audio_buffer) > int(3 * sample_rate / chunk_size):
                        audio_buffer.pop(0)

                    if score >= sensitivity:
                        now = datetime.now()

                        # Hard cooldown — ignore for 8 s after each trigger
                        if now < cooldown_until:
                            continue

                        # Ignore if Jarvis is currently speaking — prevents echo loop
                        if tts_is_speaking.is_set():
                            audio_buffer.clear()
                            continue

                        ts = now.strftime("%H:%M:%S")
                        logger.info("Wake word detected at %s (score=%.3f).", ts, score)
                        cooldown_until = now + timedelta(seconds=12)

                        # Play wake chime then acknowledge
                        play_chime("wake_chime")
                        speak(persona.wake())

                        if status_callback:
                            status_callback("Recording")
                        # Collect 4 more seconds for the command
                        command_chunks = []   # fresh — don't use pre-wake buffer
                        for _ in range(int(4 * sample_rate / chunk_size)):
                            c, _ = stream.read(chunk_size)
                            command_chunks.append(c.flatten().astype(np.int16))
                        audio = np.concatenate(command_chunks).astype(np.float32) / 32768.0
                        audio_queue.put(audio)
                        audio_buffer.clear()

        except Exception as e:
            logger.error("Wake word thread crashed: %s — restarting in 3s.", e)
            if status_callback:
                status_callback("Error")
            import time
            time.sleep(3)


# ---------------------------------------------------------------------------
# STT + LLM main loop thread
# ---------------------------------------------------------------------------

def stt_llm_loop(audio_queue: queue.Queue, stop_event: threading.Event,
                 status_callback: Callable | None = None) -> None:
    """
    Processes audio from audio_queue:
    transcribe → route → respond.
    """
    logger.info("STT/LLM loop started.")
    start_session()

    while not stop_event.is_set():
        try:
            audio = audio_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        # If Jarvis just finished speaking, wait for the echo to clear and
        # drain any audio that snuck into the queue while it was speaking.
        if tts_is_speaking.is_set():
            tts_is_speaking.wait()          # block until speech finishes
        import time as _t
        _t.sleep(0.8)                       # 800 ms echo tail clearance
        while not audio_queue.empty():
            try:
                audio_queue.get_nowait()
            except Exception:
                break

        if status_callback:
            status_callback("Transcribing")

        text = transcribe_audio(audio)
        if not text:
            logger.warning("STT returned empty — retrying once.")
            text = transcribe_audio(audio)
        if not text:
            tools.play_sound("error_chime")
            speak_async("I'm afraid I didn't catch that, Samaira. Could you repeat?")
            if status_callback:
                status_callback("Listening")
            continue

        # Discard obvious noise: single words under 3 chars, or pure filler
        _FILLERS = {"you", "huh", "uh", "um", "ah", "oh", "mm", "hmm", "yeah", "no"}
        words = text.strip().split()
        if len(words) <= 1 and text.strip().lower() in _FILLERS:
            logger.info("STT noise filtered: %r", text)
            if status_callback:
                status_callback("Listening")
            continue

        process_command(text, status_callback=status_callback)

        if status_callback:
            status_callback("Listening")

    end_session(status_callback)
    logger.info("STT/LLM loop exited.")
