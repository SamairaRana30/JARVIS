"""
shortcuts_engine.py — Execute multi-step voice macros from shortcuts.yaml.

Users define their own shortcuts without editing Python.
Each shortcut runs a sequence of commands through the full intent router.
"""

import logging
import re
import time
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR      = Path(__file__).parent.resolve()
SHORTCUTS_FILE = BASE_DIR / "shortcuts.yaml"


def _load_shortcuts() -> dict[str, list[str]]:
    """Load from both shortcuts.yaml AND data/macros.json."""
    result = {}

    # Load shortcuts.yaml
    try:
        with open(SHORTCUTS_FILE, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for trigger, commands in raw.items():
            if isinstance(commands, list):
                result[trigger.lower().strip()] = commands
            elif isinstance(commands, str):
                result[trigger.lower().strip()] = [c.strip() for c in commands.split("|")]
    except Exception as e:
        logger.warning("Could not load shortcuts.yaml: %s", e)

    # Load macros.json
    try:
        import json
        macros_path = BASE_DIR / "data" / "macros.json"
        if macros_path.exists():
            data = json.loads(macros_path.read_text(encoding="utf-8"))
            for macro in data.get("macros", []):
                trigger   = macro.get("trigger", "").lower().strip()
                commands  = macro.get("commands", [])
                if trigger and commands:
                    result[trigger] = commands
    except Exception as e:
        logger.warning("Could not load macros.json: %s", e)

    return result


def add_macro(name: str, trigger: str, commands: list[str],
              description: str = "") -> str:
    """Add a new macro to macros.json."""
    import json
    macros_path = BASE_DIR / "data" / "macros.json"
    try:
        data = json.loads(macros_path.read_text(encoding="utf-8"))
    except Exception:
        data = {"macros": []}

    # Remove existing macro with same trigger
    data["macros"] = [m for m in data["macros"] if m.get("trigger", "").lower() != trigger.lower()]
    data["macros"].append({
        "name":        name,
        "trigger":     trigger.lower(),
        "commands":    commands,
        "description": description,
    })
    macros_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return f"Macro '{name}' saved. Say '{trigger}' to run it."


def delete_macro(name: str) -> str:
    """Delete a macro by name or trigger from macros.json."""
    import json
    macros_path = BASE_DIR / "data" / "macros.json"
    try:
        data = json.loads(macros_path.read_text(encoding="utf-8"))
        before = len(data["macros"])
        data["macros"] = [
            m for m in data["macros"]
            if name.lower() not in m.get("name", "").lower()
            and name.lower() not in m.get("trigger", "").lower()
        ]
        if len(data["macros"]) == before:
            return f"No macro found matching '{name}'."
        macros_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return f"Deleted macro '{name}'."
    except Exception as e:
        return f"Could not delete macro: {e}"


def match_shortcut(text: str) -> str | None:
    """Return the trigger key if text matches a shortcut, else None."""
    shortcuts = _load_shortcuts()
    text_l    = text.lower().strip()
    # Exact match first
    if text_l in shortcuts:
        return text_l
    # Partial match
    for trigger in shortcuts:
        if trigger in text_l or text_l in trigger:
            return trigger
    return None


def run_shortcut(trigger: str, speak_fn=None, llm_caller=None) -> str:
    """
    Execute all commands in a shortcut sequence.
    Returns a summary of what was run.
    """
    import intent_router as _ir

    shortcuts = _load_shortcuts()
    commands  = shortcuts.get(trigger.lower(), [])
    if not commands:
        return f"No shortcut found for '{trigger}'."

    results = []
    for cmd in commands:
        logger.info("Shortcut '%s': running '%s'", trigger, cmd)
        try:
            response = _ir.route(cmd, llm_caller=llm_caller)
            if response:
                results.append(response)
                if speak_fn:
                    speak_fn(response)
                    time.sleep(0.5)   # brief gap between commands
        except Exception as e:
            logger.warning("Shortcut command '%s' failed: %s", cmd, e)

    return f"Shortcut '{trigger}' complete — ran {len(commands)} commands."


def list_shortcuts() -> str:
    """Return a spoken list of available shortcuts."""
    shortcuts = _load_shortcuts()
    if not shortcuts:
        return "No shortcuts defined. Edit shortcuts.yaml to add your own."
    names = list(shortcuts.keys())
    return f"You have {len(names)} shortcuts: {', '.join(names)}."
