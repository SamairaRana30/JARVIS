"""
first_run.py — Voice-guided first-run setup for Jarvis.

Triggered when:
  • first_run.flag does not exist in the project root, OR
  • memory.json name field is still the placeholder "your name"

Asks 5 questions by voice, saves answers to memory.json,
then creates first_run.flag so setup never repeats.
"""

import json
import logging
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

BASE_DIR   = Path(__file__).parent.resolve()
FLAG_FILE  = BASE_DIR / "first_run.flag"
MEM_PATH_KEY = "memory"   # key in config.yaml paths section


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _mem_path() -> Path:
    return BASE_DIR / _load_cfg()["paths"][MEM_PATH_KEY]


def _load_mem() -> dict:
    return json.loads(_mem_path().read_text(encoding="utf-8"))


def _save_mem(mem: dict) -> None:
    _mem_path().write_text(
        json.dumps(mem, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _needs_setup() -> bool:
    if not FLAG_FILE.exists():
        return True
    try:
        name = _load_mem().get("name", "").lower().strip()
        return name in ("your name", "", "name", "user")
    except Exception:
        return True


def _parse_apps(text: str) -> list[str]:
    """
    Parse a spoken app list like 'Notion, VS Code and Chrome'
    into ['Notion', 'VS Code', 'Chrome'].
    """
    # Split on commas and the word "and"
    import re
    parts = re.split(r",\s*|\s+and\s+", text, flags=re.IGNORECASE)
    apps = []
    for part in parts:
        cleaned = part.strip(" .,!?")
        if cleaned:
            apps.append(cleaned)
    return apps[:8]   # cap at 8


def _strip_name_filler(text: str) -> str:
    """Remove common filler phrases from a name answer."""
    import re
    text = re.sub(
        r"^(my name is|i.?m|i am|it.?s|its|call me)\s+",
        "", text, flags=re.IGNORECASE
    ).strip(" .,!?")
    return text


def _looks_like_url(text: str) -> bool:
    return "." in text and (text.startswith("http") or "/" in text or ".ac." in text or ".edu" in text)


def _normalise_url(text: str) -> str:
    text = text.strip()
    if not text.startswith("http"):
        text = "https://" + text
    return text


# ---------------------------------------------------------------------------
# Audio listener
# ---------------------------------------------------------------------------

def _listen(speak_fn, sample_rate: int, whisper_cfg: dict,
            duration: float = 6.0, retries: int = 1) -> str:
    """
    Record `duration` seconds of audio and return transcribed text.
    Retries once on empty result. Returns "" if both attempts fail.
    """
    try:
        import sounddevice as sd  # type: ignore
        import numpy as np
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as e:
        logger.error("STT dependency missing: %s", e)
        return ""

    model_size  = whisper_cfg.get("model_size", "base")
    device      = whisper_cfg.get("device", "cpu")
    compute     = whisper_cfg.get("compute_type", "int8")
    model       = WhisperModel(model_size, device=device, compute_type=compute)

    for attempt in range(retries + 1):
        try:
            audio = sd.rec(
                int(sample_rate * duration),
                samplerate=sample_rate,
                channels=1,
                dtype="float32",
            )
            sd.wait()
            flat = audio.flatten()
            segments, _ = model.transcribe(flat, language=None)
            text = " ".join(seg.text for seg in segments).strip()
            if text:
                return text
            if attempt < retries:
                speak_fn("Sorry, I didn't catch that. Please try again.")
                time.sleep(0.3)
        except Exception as e:
            logger.warning("STT attempt %d failed: %s", attempt + 1, e)

    return ""


# ---------------------------------------------------------------------------
# Main setup flow
# ---------------------------------------------------------------------------

def run_first_run_setup(speak_fn, chime_fn=None) -> None:
    """
    Run the voice-guided setup wizard.

    speak_fn(text: str) — blocking TTS
    chime_fn()          — plays the wake chime (optional)
    """
    if not _needs_setup():
        logger.debug("first_run: setup not needed.")
        return

    logger.info("First-run setup starting.")

    cfg        = _load_cfg()
    w_cfg      = cfg.get("whisper", {})
    sample_rate = cfg.get("sample_rate", 16000)
    mem        = _load_mem()

    if chime_fn:
        chime_fn()
    time.sleep(0.3)

    # ── 1. Name ──────────────────────────────────────────────────────────────
    speak_fn(
        "Hi, I'm Jarvis. Let's get you set up. "
        "What's your name?"
    )
    name_raw = _listen(speak_fn, sample_rate, w_cfg, duration=6)
    if name_raw.lower().strip() == "skip" or not name_raw:
        name = "Samaira"
    else:
        name = _strip_name_filler(name_raw)
        if not name:
            name = "Samaira"
    mem["name"] = name
    _save_mem(mem)
    logger.info("Setup: name = %s", name)

    time.sleep(0.4)

    # ── 2. University ─────────────────────────────────────────────────────────
    speak_fn(f"Nice to meet you, {name}. What university are you at?")
    uni = _listen(speak_fn, sample_rate, w_cfg, duration=7)
    if uni and uni.lower().strip() != "skip":
        mem["uni"] = uni.strip(" .,")
    _save_mem(mem)
    logger.info("Setup: uni = %s", mem.get("uni"))

    time.sleep(0.4)

    # ── 3. Current project ───────────────────────────────────────────────────
    speak_fn(
        "What are you currently working on? "
        "For example, a project or assignment."
    )
    project_raw = _listen(speak_fn, sample_rate, w_cfg, duration=8)
    if project_raw and project_raw.lower().strip() != "skip":
        # Store as first element of projects list
        projects = _parse_apps(project_raw)  # handles "X and Y" format
        mem["projects"] = projects if projects else mem.get("projects", [])
    _save_mem(mem)
    logger.info("Setup: projects = %s", mem.get("projects"))

    time.sleep(0.4)

    # ── 4. Study apps ─────────────────────────────────────────────────────────
    speak_fn(
        "What apps do you use for studying? "
        "For example: Notion, VS Code, Chrome."
    )
    apps_raw = _listen(speak_fn, sample_rate, w_cfg, duration=8)
    if apps_raw and apps_raw.lower().strip() != "skip":
        apps = _parse_apps(apps_raw)
        if apps:
            mem["study_apps"] = apps
    _save_mem(mem)
    logger.info("Setup: study_apps = %s", mem.get("study_apps"))

    time.sleep(0.4)

    # ── 5. Uni portal URL ─────────────────────────────────────────────────────
    speak_fn(
        "What's your uni portal URL? "
        "You can say skip to set it up later."
    )
    url_raw = _listen(speak_fn, sample_rate, w_cfg, duration=8)
    uni_url = None
    if url_raw and url_raw.lower().strip() not in ("skip", "", "later"):
        if _looks_like_url(url_raw):
            uni_url = _normalise_url(url_raw)
        else:
            guessed = url_raw.lower().replace(" dot ", ".").replace(" slash ", "/").strip()
            uni_url = _normalise_url(guessed)
        mem.setdefault("quick_links", {})["uni portal"] = uni_url
    _save_mem(mem)
    logger.info("Setup: uni portal = %s", uni_url)

    time.sleep(0.4)

    # ── Persist everything properly ───────────────────────────────────────────
    project_name = ""
    if mem.get("projects"):
        p = mem["projects"][0]
        project_name = p if isinstance(p, str) else p.get("name", "")
    _save_first_run_data(cfg, mem, project_name)

    # ── 6. Done ───────────────────────────────────────────────────────────────
    speak_fn(
        f"Perfect. I'm all set up and ready to go, {name}. "
        "Say Jarvis any time to talk to me. "
        "Say 'Jarvis, what can you do' to see everything I'm capable of."
    )

    # Create flag file so setup doesn't repeat
    FLAG_FILE.write_text("setup_complete", encoding="utf-8")
    logger.info("First-run setup completed. Flag written: %s", FLAG_FILE)


def _save_first_run_data(cfg: dict, mem: dict, project: str) -> None:
    """Persist structured project data to memory.json and goals.json."""
    # Structure the project entry properly
    if project and project.lower() != "skip":
        mem["projects"] = [{
            "name": project,
            "description": "",
            "status": "in progress",
            "notes_folder": f"notes/projects/{project}/",
            "quick_links": {},
        }]
        # Create project notes folder
        folder = BASE_DIR / "notes" / "projects" / project
        folder.mkdir(parents=True, exist_ok=True)
        logger.info("Created project folder: %s", folder)

    _save_mem(mem)

    # Update goals.json short_term[0] with the project
    if project and project.lower() != "skip":
        try:
            goals_path = BASE_DIR / cfg["paths"]["goals"]
            goals = json.loads(goals_path.read_text(encoding="utf-8"))
            st = goals.get("short_term", [])
            if st:
                st[0]["goal"] = f"Make progress on {project}"
            else:
                goals.setdefault("short_term", []).append(
                    {"goal": f"Make progress on {project}", "deadline": "", "progress": 0}
                )
            goals_path.write_text(json.dumps(goals, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("Updated goals.json with project: %s", project)
        except Exception as e:
            logger.warning("Could not update goals.json: %s", e)
