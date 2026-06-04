"""
meeting_mode.py -- Meeting mode with continuous transcription.

State:
  in_meeting = False  (session RAM only)

On:
  - Suppress reminders, Pomodoro sounds, scheduler alerts
  - Start continuous Whisper transcription (30-second chunks)
  - Append [HH:MM] timestamped transcript to notes/meetings/
  - Speak: "Meeting mode on. Transcribing."
  - Show "MEETING" status in HUD

Off:
  - Stop transcription thread
  - Re-enable all alerts
  - Offer LLM summary
  - Speak: "Meeting mode off."
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
_meeting_active   = False
_meeting_end_timer: threading.Timer | None = None
_transcribe_thread: threading.Thread | None = None
_transcribe_stop   = threading.Event()
_meeting_file_path: Path | None = None
_speak_fn  = None
_llm_fn    = None
_status_fn = None   # tray/HUD status callback


def set_speak(fn) -> None:
    global _speak_fn; _speak_fn = fn

def set_llm(fn) -> None:
    global _llm_fn; _llm_fn = fn

def set_status_callback(fn) -> None:
    global _status_fn; _status_fn = fn


def is_in_meeting() -> bool:
    return _meeting_active


def _cfg() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Transcription thread
# ---------------------------------------------------------------------------

def _transcription_loop(file_path: Path) -> None:
    """Record 30-s chunks and append [HH:MM] timestamped lines to the meeting file."""
    try:
        import numpy as np
        import sounddevice as sd
        from jarvis import _get_whisper_model, _audio_rms, _VAD_ENERGY_THRESHOLD
    except Exception as e:
        logger.error("Meeting transcription setup failed: %s", e)
        return

    cfg         = _cfg()
    chunk_s     = int(cfg.get("meeting", {}).get("chunk_seconds", 30))
    sample_rate = cfg.get("sample_rate", 16000)
    model       = _get_whisper_model()

    while not _transcribe_stop.is_set() and _meeting_active:
        try:
            audio = sd.rec(sample_rate * chunk_s, samplerate=sample_rate,
                           channels=1, dtype="float32")
            # Wait chunk_s seconds or until stopped
            for _ in range(chunk_s * 10):
                if _transcribe_stop.is_set():
                    break
                time.sleep(0.1)
            sd.stop()

            flat = audio.flatten()
            if _audio_rms(flat) < _VAD_ENERGY_THRESHOLD * 0.5:
                continue   # silence

            segments, _ = model.transcribe(flat, language=None)
            text = " ".join(seg.text for seg in segments).strip()
            if text and len(text) > 5:
                ts   = datetime.now().strftime("%H:%M")
                line = f"[{ts}] {text}\n"
                with open(file_path, "a", encoding="utf-8") as f:
                    f.write(line)
                logger.debug("Meeting transcript: %s", text[:60])
        except Exception as e:
            logger.warning("Transcription chunk error: %s", e)
            time.sleep(5)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_meeting(duration_minutes: int | None = None) -> str:
    global _meeting_active, _meeting_end_timer, _transcribe_thread
    global _transcribe_stop, _meeting_file_path

    _meeting_active = True
    logger.info("Meeting mode activated.")

    # Notify HUD/tray
    if _status_fn:
        _status_fn("MEETING")

    # Create meeting file
    cfg = _cfg()
    now = datetime.now()
    meetings_dir = BASE_DIR / "notes" / "meetings"
    meetings_dir.mkdir(parents=True, exist_ok=True)
    fname = now.strftime("%Y-%m-%d-%H-%M") + "-meeting.md"
    _meeting_file_path = meetings_dir / fname

    with open(_meeting_file_path, "w", encoding="utf-8") as f:
        f.write(f"# Meeting -- {now.strftime('%d %B %Y %H:%M')}\n\n")
        f.write("## Transcript\n\n")

    # Launch Windows Sound Recorder for visual/manual recording backup
    try:
        import subprocess
        # Windows 11 Sound Recorder
        subprocess.Popen(["explorer", "ms-soundrecorder:"], shell=False)
        logger.info("Sound Recorder launched.")
    except Exception:
        try:
            subprocess.Popen(["SoundRecorder.exe"])
        except Exception:
            pass   # Sound Recorder not available — Whisper handles it

    # Start transcription thread
    if cfg.get("meeting", {}).get("save_raw_transcript", True):
        _transcribe_stop.clear()
        _transcribe_thread = threading.Thread(
            target=_transcription_loop,
            args=(_meeting_file_path,),
            daemon=True,
            name="MeetingTranscriber",
        )
        _transcribe_thread.start()
        logger.info("Meeting transcription started: %s", fname)

    # Auto-end timer
    if _meeting_end_timer:
        _meeting_end_timer.cancel()
    if duration_minutes:
        def _auto_end():
            end_meeting()
        _meeting_end_timer = threading.Timer(duration_minutes * 60, _auto_end)
        _meeting_end_timer.daemon = True
        _meeting_end_timer.start()
        return (
            f"Meeting mode on. Transcribing for {duration_minutes} minutes. "
            "I'll stay quiet unless you ask me something."
        )

    return "Meeting mode on. Transcribing."


def end_meeting(want_summary: bool | None = None) -> str:
    global _meeting_active, _meeting_end_timer, _transcribe_thread

    _meeting_active = False

    if _meeting_end_timer:
        _meeting_end_timer.cancel()
        _meeting_end_timer = None

    # Stop transcription
    _transcribe_stop.set()
    if _transcribe_thread and _transcribe_thread.is_alive():
        _transcribe_thread.join(timeout=5)

    # Restore status
    if _status_fn:
        _status_fn("Listening")

    logger.info("Meeting mode off.")

    cfg = _cfg()
    auto_summarise = cfg.get("meeting", {}).get("auto_summarise", True)

    if _meeting_file_path and _meeting_file_path.exists():
        # Index into RAG
        try:
            from rag_tool import index_file
            index_file(_meeting_file_path)
        except Exception:
            pass

        if auto_summarise and _llm_fn:
            try:
                transcript = _meeting_file_path.read_text(encoding="utf-8")
                summary = _llm_fn(
                    f"Summarise this meeting transcript in bullet points. "
                    f"Extract: key decisions, action items, important points.\n\n"
                    f"Transcript:\n{transcript[:4000]}"
                )
                # Prepend summary to file
                existing = _meeting_file_path.read_text(encoding="utf-8")
                _meeting_file_path.write_text(
                    f"## Summary\n\n{summary}\n\n{existing}",
                    encoding="utf-8"
                )
                if _speak_fn:
                    _speak_fn(f"Meeting ended. Here are the key points: {summary[:300]}")
                return "Meeting mode off. Summary saved."
            except Exception as e:
                logger.warning("Meeting summary failed: %s", e)

        if _speak_fn:
            _speak_fn("Meeting mode off.")

    return "Meeting mode off."


def get_last_meeting_summary(llm_caller=None) -> str:
    """Find and summarise the most recent meeting file."""
    meetings_dir = BASE_DIR / "notes" / "meetings"
    if not meetings_dir.exists():
        return "No meetings recorded yet."

    files = sorted(meetings_dir.glob("*-meeting.md"),
                   key=lambda f: f.stat().st_mtime, reverse=True)
    if not files:
        return "No meeting files found."

    latest = files[0]
    text   = latest.read_text(encoding="utf-8")

    # Check if summary already exists
    if "## Summary" in text:
        summary_section = text.split("## Summary")[1].split("## Transcript")[0].strip()
        return f"Last meeting ({latest.stem}): {summary_section[:400]}"

    if llm_caller and len(text) > 50:
        summary = llm_caller(
            f"Summarise this meeting in 3-5 bullet points:\n\n{text[:3000]}"
        )
        return f"Last meeting summary: {summary}"

    return f"Last meeting: {latest.stem}\n\n{text[:400]}"
