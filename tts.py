"""
tts.py — Text-to-speech for Jarvis.
Primary: edge-tts (async, needs internet on first use, cached after).
Fallback: Piper TTS (fully offline binary).
"""

import asyncio
import logging
import os
import subprocess
import threading
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).parent.resolve()
# Fixed output file — avoids Windows file-locking issues with temp files.
# TTS is serialized (one utterance at a time via _speak_lock) so one file is safe.
_TTS_OUT  = str(_BASE_DIR / "tts_out.mp3")


def _load_cfg() -> dict:
    with open(_BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


_cfg    = _load_cfg()
_RATE   = _cfg.get("speaking_rate",   "+0%")
_VOL_DB = _cfg.get("speaking_volume", "+0%")   # edge-tts volume offset
_PITCH  = _cfg.get("speaking_pitch",  "-5Hz")
_VOLUME = float(_cfg.get("volume", 1.0))        # pygame playback volume 0.0–1.0

# Volume/speed step sizes
_VOLUME_STEP = 0.15
_RATE_STEP   = 5    # percent points


def adjust_volume(delta: float) -> str:
    """Increase or decrease TTS volume. delta = +/- VOLUME_STEP."""
    global _VOLUME
    _VOLUME = max(0.05, min(1.0, _VOLUME + delta))
    pct = int(_VOLUME * 100)
    return f"Volume set to {pct} percent."


def adjust_rate(delta_pct: int) -> str:
    """Increase or decrease speaking rate. delta_pct = +/- integer percent points."""
    global _RATE
    import re as _re
    m = _re.match(r"([+-]?\d+)%", _RATE)
    current = int(m.group(1)) if m else 0
    new_val = max(-50, min(50, current + delta_pct))
    _RATE = f"{new_val:+d}%"
    direction = "faster" if delta_pct > 0 else "slower"
    return f"Speaking {direction} now."


def play_chime(chime_key: str) -> None:
    """
    Play a named chime. Delegates to tools.play_sound() which uses
    pygame.mixer.Sound (Channel 1) so it overlays background music.
    Non-blocking — fires in a background thread.
    """
    import threading as _th
    def _play():
        try:
            import tools as _t
            _t.play_sound(chime_key)
        except Exception:
            pass
    _th.Thread(target=_play, daemon=True).start()

# Language → voice map loaded from config
_lang_cfg    = _cfg.get("language", {})
_VOICE_MAP   = {
    "en": _lang_cfg.get("tts_voice_en", "en-GB-RyanNeural"),
    "de": _lang_cfg.get("tts_voice_de", "de-DE-ConradNeural"),
}
_CURRENT_LANG = _lang_cfg.get("default", "en")
_VOICE        = _VOICE_MAP.get(_CURRENT_LANG, _cfg.get("voice", "en-GB-RyanNeural"))


def set_tts_language(lang: str) -> None:
    """Switch the TTS voice to match the given language code (e.g. 'de', 'en')."""
    global _CURRENT_LANG, _VOICE
    _CURRENT_LANG = lang
    _VOICE = _VOICE_MAP.get(lang, _VOICE_MAP.get("en", "en-GB-RyanNeural"))
    logger.info("TTS language set to %s → voice: %s", lang, _VOICE)


def get_tts_language() -> str:
    return _CURRENT_LANG

# ---------------------------------------------------------------------------
# Playback helper (cross-platform but focused on Windows)
# ---------------------------------------------------------------------------

def _play_wav(path: str) -> None:
    """
    Play a WAV or MP3 file (blocking).
    Uses pygame.mixer which supports MP3 natively on Windows.
    Pauses any background music for the duration of playback.
    """
    try:
        import time as _time
        import pygame  # type: ignore

        if not pygame.mixer.get_init():
            pygame.mixer.pre_init(frequency=44100, size=-16, channels=2, buffer=512)
            pygame.mixer.init()

        # Pause background music so TTS is clearly audible
        bg_busy = pygame.mixer.music.get_busy()
        if bg_busy:
            pygame.mixer.music.pause()

        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.set_volume(max(0.0, min(1.0, _VOLUME)))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                _time.sleep(0.05)
            pygame.mixer.music.unload()  # release file handle so next write can overwrite
        finally:
            if bg_busy:
                pygame.mixer.music.unpause()

    except Exception as e:
        logger.error("TTS playback failed: %s", e)
        # Last resort for WAV files only
        try:
            import winsound
            if path.endswith(".wav"):
                winsound.PlaySound(path, winsound.SND_FILENAME)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# edge-tts (primary)
# ---------------------------------------------------------------------------

async def _edge_speak_async(text: str, voice: str, rate: str,
                            pitch: str = "-5Hz", volume: str = "+0%") -> bool:
    """Speak text via edge-tts. Returns True on success."""
    try:
        import edge_tts  # type: ignore
        communicate = edge_tts.Communicate(
            text, voice, rate=rate, pitch=pitch, volume=volume
        )
        await communicate.save(_TTS_OUT)
        _play_wav(_TTS_OUT)
        return True
    except Exception as e:
        logger.warning("edge-tts failed: %s", e)
        return False


def _edge_speak(text: str, voice: str, rate: str,
                pitch: str = "-5Hz", volume: str = "+0%") -> bool:
    """Synchronous wrapper around edge-tts."""
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_edge_speak_async(text, voice, rate, pitch, volume))
        loop.close()
        return result
    except Exception as e:
        logger.warning("edge-tts loop error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Piper TTS (offline fallback)
# ---------------------------------------------------------------------------

def _find_piper() -> str | None:
    """Return path to piper executable if available."""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper", "piper.exe"),
        r"C:\Program Files\piper\piper.exe",
        "piper",  # on PATH
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    try:
        subprocess.run(["piper", "--version"], capture_output=True, timeout=2)
        return "piper"
    except Exception:
        return None


def _find_piper_model() -> str | None:
    """Return path to a Piper .onnx model file if one exists."""
    dirs = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper"),
        os.path.expanduser("~/.local/share/piper"),
    ]
    for d in dirs:
        if os.path.isdir(d):
            for fn in os.listdir(d):
                if fn.endswith(".onnx"):
                    return os.path.join(d, fn)
    return None


def _piper_speak(text: str) -> bool:
    """Speak text via Piper offline TTS. Returns True on success."""
    exe = _find_piper()
    if not exe:
        logger.warning("Piper executable not found.")
        return False
    model = _find_piper_model()
    if not model:
        logger.warning("No Piper .onnx model found.")
        return False
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        result = subprocess.run(
            [exe, "--model", model, "--output_file", tmp],
            input=text.encode("utf-8"),
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            logger.warning("Piper error: %s", result.stderr.decode())
            return False
        _play_wav(tmp)
        os.unlink(tmp)
        return True
    except Exception as e:
        logger.warning("Piper speak failed: %s", e)
        return False


def _pyttsx3_speak(text: str) -> bool:
    """Last-resort TTS using pyttsx3 (offline, always available on Windows)."""
    try:
        import pyttsx3  # type: ignore
        engine = pyttsx3.init()
        engine.setProperty("rate", 160)
        engine.say(text)
        engine.runAndWait()
        engine.stop()
        return True
    except Exception as e:
        logger.warning("pyttsx3 speak failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_speak_lock = threading.Lock()

# Set while Jarvis is speaking so the wake word thread can mute itself.
is_speaking = threading.Event()

# ---------------------------------------------------------------------------
# Voice output toggle
# When False: Jarvis processes commands and shows in chat but does NOT speak.
# Useful in lectures — "lecture mode" / "go silent" / "voice off".
# ---------------------------------------------------------------------------
_voice_output_enabled: bool = True


def set_voice_output(enabled: bool) -> None:
    global _voice_output_enabled
    _voice_output_enabled = enabled
    logger.info("Voice output: %s", "ON" if enabled else "OFF (silent mode)")


def is_voice_on() -> bool:
    return _voice_output_enabled


def voice_status() -> str:
    return "Voice output is on." if _voice_output_enabled else "Silent mode is on — I'll respond in chat only."

# ---------------------------------------------------------------------------
# Response queue — speak_async() queues items; a worker thread drains it
# so responses are never interrupted and always play in order.
# ---------------------------------------------------------------------------

import queue as _queue

_tts_queue: _queue.Queue = _queue.Queue()
_tts_worker_started = False


def _tts_worker() -> None:
    """Background worker that drains _tts_queue one utterance at a time."""
    while True:
        try:
            text, voice_arg, rate_arg = _tts_queue.get(timeout=1)
        except _queue.Empty:
            continue
        speak(text, voice=voice_arg, rate=rate_arg)
        _tts_queue.task_done()


def _strip_markdown(text: str) -> str:
    """Remove markdown symbols so TTS speaks clean natural text."""
    import re
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)   # **bold**, *italic*, ***both***
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)      # __bold__, _italic_
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)           # `code` / ```blocks```
    text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)  # # headings
    text = re.sub(r'^\s*[-*+]\s+', '', text, flags=re.MULTILINE)  # bullet points
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)  # numbered lists → strip number
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)    # [link text](url)
    text = re.sub(r'!\[[^\]]*\]\([^)]+\)', '', text)         # ![image](url)
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)    # > blockquotes
    text = re.sub(r'-{3,}|={3,}', '', text)                  # --- horizontal rules
    text = re.sub(r'\|', ', ', text)                          # table pipes → commas
    text = re.sub(r' {2,}', ' ', text)                        # multiple spaces
    text = re.sub(r'\n{2,}', '. ', text)                     # blank lines → pause
    text = text.replace('\n', ' ').strip()
    return text


def speak(text: str, voice: str | None = None, rate: str | None = None) -> None:
    """
    Speak text aloud. Tries edge-tts first; falls back to Piper.
    Thread-safe (one utterance at a time).
    Sets is_speaking for the duration so the wake word listener won't
    trigger on Jarvis's own voice.
    """
    if not text or not text.strip():
        return

    # In silent/lecture mode: emit to chat UI but skip audio
    if not _voice_output_enabled:
        try:
            from ui.signals import JarvisSignals
            JarvisSignals.instance().jarvis_speaking.emit(text)
        except Exception:
            pass
        logger.debug("Silent mode: skipped audio for: %s", text[:60])
        return

    text = _strip_markdown(text)
    if not text:
        return

    voice = voice or _VOICE
    rate  = rate  or _RATE

    with _speak_lock:
        is_speaking.set()
        try:
            logger.debug("TTS: %s", text[:80])
            if not _edge_speak(text, voice, rate, _PITCH, _VOL_DB):
                logger.info("Falling back to Piper TTS.")
                if not _piper_speak(text):
                    logger.warning("Piper also failed. Trying pyttsx3 last-resort.")
                    if not _pyttsx3_speak(text):
                        logger.error("All TTS engines failed. No audio output.")
        finally:
            is_speaking.clear()


def speak_async(text: str, voice: str | None = None, rate: str | None = None) -> None:
    """
    Queue text for speaking. The TTS worker thread plays each item in order,
    so responses are never interrupted by the next one.
    """
    global _tts_worker_started
    if not text or not text.strip():
        return
    if not _tts_worker_started:
        _tts_worker_started = True
        threading.Thread(target=_tts_worker, daemon=True, name="TTSWorker").start()
    _tts_queue.put((text, voice, rate))
