"""
jarvis_persona.py — Voice line library for Jarvis.
All spoken phrases live here. Each category returns a random line so
responses feel varied rather than robotic.
"""

import random
from datetime import datetime


def _r(lines: list[str]) -> str:
    return random.choice(lines)


def _name() -> str:
    """Load the user's name from memory.json at call time."""
    try:
        import json
        from pathlib import Path
        data = json.loads((Path(__file__).parent / "data" / "memory.json").read_text())
        return data.get("name", "").split()[0] or "Samaira"
    except Exception:
        return "Samaira"


def _time_of_day() -> str:
    h = datetime.now().hour
    if h < 12:  return "morning"
    if h < 18:  return "afternoon"
    return "evening"


# ---------------------------------------------------------------------------
# 1. Wake word acknowledgements
# ---------------------------------------------------------------------------

def wake() -> str:
    name = _name()
    return _r([
        f"Yes, {name}.",
        "I'm listening.",
        f"How may I assist you, {name}?",
        "At your service.",
        f"Go ahead, {name}.",
    ])


# ---------------------------------------------------------------------------
# 2. System startup
# ---------------------------------------------------------------------------

def startup() -> str:
    name = _name()
    tod  = _time_of_day()
    return _r([
        f"System online. Good {tod}, {name}. All functions are operating within optimal parameters.",
        f"Jarvis activated. Good {tod}, {name}. Standing by for your command.",
        f"Initialization complete. Good {tod}, {name}. Ready when you are.",
    ])


# ---------------------------------------------------------------------------
# 3. Acknowledgements (spoken before a long LLM response)
# ---------------------------------------------------------------------------

def ack() -> str:
    name = _name()
    return _r([
        f"Certainly, {name}.",
        "Right away.",
        "As you wish.",
        "Understood.",
        "Processing your request.",
        "On it.",
    ])


# ---------------------------------------------------------------------------
# 4. Thinking / processing (spoken while LLM works)
# ---------------------------------------------------------------------------

def thinking() -> str:
    return _r([
        "Allow me a moment to analyse that.",
        "Compiling the necessary data.",
        "Evaluating the most efficient solution.",
        "Running a quick assessment.",
        "One moment.",
    ])


# ---------------------------------------------------------------------------
# 5. Status — task done
# ---------------------------------------------------------------------------

def done() -> str:
    return _r([
        "Your request has been completed.",
        "The task is now finished.",
        "Done.",
        "All systems remain stable.",
        "I've taken the liberty of handling that.",
    ])


# ---------------------------------------------------------------------------
# 6. Error / warning
# ---------------------------------------------------------------------------

def error(detail: str = "") -> str:
    base = _r([
        "I'm afraid that function is currently unavailable.",
        "There appears to be a minor issue.",
        "That action cannot be completed at this time.",
        "I'm detecting an inconsistency. Please confirm your request.",
    ])
    return f"{base} {detail}".strip()


# ---------------------------------------------------------------------------
# 7. Protective / system guardian
# ---------------------------------------------------------------------------

def system_ok() -> str:
    name = _name()
    return _r([
        f"Your system integrity remains uncompromised, {name}.",
        "All systems remain stable.",
        f"I'll ensure everything continues to run smoothly, {name}.",
    ])


# ---------------------------------------------------------------------------
# 8. Conversational
# ---------------------------------------------------------------------------

def suggest() -> str:
    return _r([
        "If I may suggest, there is a faster method available.",
        "I've taken the liberty of preparing a more efficient approach.",
        "Would you like me to proceed with the next task?",
    ])


def compliment() -> str:
    name = _name()
    return _r([
        f"Your productivity levels are impressive today, {name}.",
        f"Excellent decision, {name}.",
        f"A wise choice, {name}.",
    ])


# ---------------------------------------------------------------------------
# 9. Shutdown
# ---------------------------------------------------------------------------

def shutdown() -> str:
    name = _name()
    return _r([
        f"Powering down. I'll be here when you need me again, {name}.",
        f"Deactivating systems. Have a pleasant rest, {name}.",
        "Jarvis offline. Awaiting your return.",
    ])


# ---------------------------------------------------------------------------
# 10. Ollama / service offline
# ---------------------------------------------------------------------------

def llm_offline() -> str:
    return _r([
        "I'm afraid the language model is offline. Please start Ollama to restore full functionality.",
        "The neural core is currently unreachable. Ollama needs to be running.",
        "Language processing is unavailable. Please start Ollama.",
    ])
