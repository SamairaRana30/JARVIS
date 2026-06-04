"""
setup_wizard.py — First-run voice setup wizard.
Detects if memory.json still has placeholder values and walks
Samaira through personalising Jarvis by voice.
Runs once, saves answers to memory.json, then starts normal operation.
"""

import json
import logging
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _is_first_run() -> bool:
    """Return True if memory.json still has the placeholder name."""
    try:
        mem_path = BASE_DIR / _load_cfg()["paths"]["memory"]
        mem = json.loads(mem_path.read_text(encoding="utf-8"))
        name = mem.get("name", "").lower().strip()
        return name in ("your name", "", "name", "user")
    except Exception:
        return False


def _ask_and_listen(question: str, speak_fn, listen_fn, timeout: float = 10.0) -> str:
    """Speak a question, wait for a spoken answer, return the text."""
    speak_fn(question)
    time.sleep(0.5)   # small gap after TTS before mic opens
    answer = listen_fn(timeout=timeout)
    return answer.strip()


def run_setup_wizard(speak_fn, listen_fn) -> None:
    """
    Walk through first-run setup by voice.
    speak_fn(text)     — speaks text (blocking)
    listen_fn(timeout) — records and returns transcribed text
    """
    if not _is_first_run():
        return

    logger.info("First run detected — starting setup wizard.")

    speak_fn(
        "Hello! I'm Jarvis. It looks like this is our first time meeting. "
        "Let me take a moment to get to know you. "
        "Please answer each question out loud."
    )
    time.sleep(1)

    cfg = _load_cfg()
    mem_path = BASE_DIR / cfg["paths"]["memory"]
    mem = json.loads(mem_path.read_text(encoding="utf-8"))

    # Question 1 — Name
    name = _ask_and_listen(
        "First — what's your name?",
        speak_fn, listen_fn, timeout=8
    )
    if not name:
        name = "Samaira"
    # Strip filler words that Whisper might prepend
    for filler in ("my name is", "i'm", "i am", "it's", "its"):
        if name.lower().startswith(filler):
            name = name[len(filler):].strip()
    name = name.strip(" .,!?")
    speak_fn(f"Nice to meet you, {name}.")
    mem["name"] = name
    time.sleep(0.5)

    # Question 2 — University
    uni = _ask_and_listen(
        "What university are you at? Or say 'skip' if not applicable.",
        speak_fn, listen_fn, timeout=8
    )
    if uni and "skip" not in uni.lower():
        mem["uni"] = uni.strip(" .,")
        speak_fn(f"Got it — {mem['uni']}.")
    time.sleep(0.5)

    # Question 3 — Current projects
    projects_raw = _ask_and_listen(
        "What are you currently working on? You can name one or two projects.",
        speak_fn, listen_fn, timeout=10
    )
    if projects_raw and "skip" not in projects_raw.lower():
        projects = [p.strip() for p in projects_raw.replace(" and ", ",").split(",") if p.strip()]
        mem["projects"] = projects[:4]
        speak_fn(f"I'll keep track of {', '.join(mem['projects'])} for you.")
    time.sleep(0.5)

    # Question 4 — Location
    location = _ask_and_listen(
        "And what city are you in?",
        speak_fn, listen_fn, timeout=6
    )
    if location and "skip" not in location.lower():
        mem["location"] = location.strip(" .,")

    # Save
    mem_path.write_text(json.dumps(mem, indent=2, ensure_ascii=False), encoding="utf-8")
    logger.info("Setup wizard complete. Saved memory: %s", mem_path)

    speak_fn(
        f"Perfect. I'm all set up for you, {name}. "
        "I'll remember your preferences going forward. "
        "Just say 'Jarvis' any time you need me."
    )
    time.sleep(1)
