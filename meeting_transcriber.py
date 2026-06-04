"""
meeting_transcriber.py — Silent background meeting transcription.

When meeting mode is activated, records audio in 30-second chunks,
transcribes each chunk, and appends to a meeting note.
On meeting end: LLM summarises the full transcript.
"""

import logging
import threading
import time
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()

_transcribing  = False
_transcript    = []    # list of (timestamp, text) tuples
_thread: threading.Thread | None = None
_stop_event    = threading.Event()
_meeting_start = None
_llm_fn        = None
_speak_fn      = None


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


def set_llm(fn) -> None:
    global _llm_fn
    _llm_fn = fn


def set_speak(fn) -> None:
    global _speak_fn
    _speak_fn = fn


def is_transcribing() -> bool:
    return _transcribing


def start_transcription(title: str = "") -> str:
    """Start silent background meeting transcription."""
    global _transcribing, _transcript, _thread, _meeting_start
    if _transcribing:
        return "Already transcribing."

    _transcribing  = True
    _transcript    = []
    _meeting_start = datetime.now()
    _stop_event.clear()

    meeting_title = title or f"Meeting {_meeting_start.strftime('%d %b %H:%M')}"

    _thread = threading.Thread(
        target=_transcription_loop,
        args=(meeting_title,),
        daemon=True,
        name="MeetingTranscriber",
    )
    _thread.start()

    logger.info("Meeting transcription started: %s", meeting_title)
    return f"Transcribing your meeting silently. I'll save notes when you end the meeting."


def stop_transcription(llm_caller=None) -> str:
    """Stop transcription and save + summarise the meeting note."""
    global _transcribing
    if not _transcribing:
        return "No meeting transcription running."

    _transcribing = False
    _stop_event.set()
    if _thread:
        _thread.join(timeout=5)

    return _save_meeting_note(llm_caller or _llm_fn)


def _transcription_loop(title: str) -> None:
    """Record 30-second audio chunks and transcribe each one."""
    try:
        import numpy as np
        import sounddevice as sd  # type: ignore
        from jarvis import _get_whisper_model, _audio_rms, _VAD_ENERGY_THRESHOLD
    except Exception as e:
        logger.error("Meeting transcription setup failed: %s", e)
        return

    cfg         = _load_cfg()
    sample_rate = cfg.get("sample_rate", 16000)
    chunk_s     = 30   # seconds per chunk
    model       = _get_whisper_model()

    while not _stop_event.is_set() and _transcribing:
        try:
            audio = sd.rec(
                sample_rate * chunk_s,
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
            )
            # Wait for chunk OR stop event
            for _ in range(chunk_s * 10):
                if _stop_event.is_set():
                    break
                time.sleep(0.1)
            sd.stop()

            flat = audio.flatten()
            if _audio_rms(flat) < _VAD_ENERGY_THRESHOLD * 0.5:
                continue   # silence chunk, skip

            segments, _ = model.transcribe(flat, language=None)
            text = " ".join(seg.text for seg in segments).strip()
            if text and len(text) > 10:
                ts = datetime.now().strftime("%H:%M:%S")
                _transcript.append((ts, text))
                logger.debug("Meeting transcript chunk: %s", text[:60])
        except Exception as e:
            logger.warning("Transcription chunk error: %s", e)
            time.sleep(5)


def _save_meeting_note(llm_caller=None) -> str:
    """Save transcript + LLM summary to notes/meetings/."""
    if not _transcript:
        return "No speech detected during the meeting."

    now      = datetime.now()
    duration = (now - _meeting_start).seconds // 60 if _meeting_start else 0
    filename = now.strftime("%Y-%m-%d_%H-%M") + "_meeting.md"
    note_dir = BASE_DIR / "notes" / "meetings"
    note_dir.mkdir(parents=True, exist_ok=True)
    note_path = note_dir / filename

    # Full transcript text
    full_text = "\n".join(f"[{ts}] {text}" for ts, text in _transcript)

    # LLM summary
    summary = ""
    if llm_caller and full_text:
        try:
            summary = llm_caller(
                f"Summarise this meeting transcript in bullet points. "
                f"Extract: key decisions, action items, and important points.\n\n"
                f"Transcript:\n{full_text[:4000]}"
            )
        except Exception as e:
            logger.warning("Meeting summary failed: %s", e)
            summary = "Summary unavailable."

    # Write note
    content = (
        f"---\n"
        f"title: \"Meeting {now.strftime('%d %b %Y %H:%M')}\"\n"
        f"topic: \"meetings\"\n"
        f"tags: [\"meeting\", \"transcript\"]\n"
        f"created: \"{now.isoformat()}\"\n"
        f"duration: \"{duration} minutes\"\n"
        f"---\n\n"
        f"## Summary\n\n{summary}\n\n"
        f"## Full Transcript\n\n{full_text}\n"
    )
    note_path.write_text(content, encoding="utf-8")
    logger.info("Meeting note saved: %s", note_path)

    # Index the new note into RAG
    try:
        from rag_tool import index_file
        index_file(note_path)
    except Exception:
        pass

    spoken_summary = (
        f"Meeting ended. {len(_transcript)} chunks transcribed over {duration} minutes. "
        f"Note saved to meetings folder."
    )
    if _speak_fn:
        _speak_fn(spoken_summary)
    return spoken_summary


def get_live_transcript() -> str:
    """Return the current in-progress transcript (last 5 entries)."""
    if not _transcript:
        return "No transcript yet."
    recent = _transcript[-5:]
    return "\n".join(f"[{ts}] {text}" for ts, text in recent)
