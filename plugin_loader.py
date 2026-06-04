"""
plugin_loader.py — Simple plugin system for Jarvis.
Place Python files in plugins/ and they are auto-loaded on startup.

Plugin structure (plugins/my_plugin.py):
---
PLUGIN_NAME = "my_plugin"
PLUGIN_VERSION = "1.0"
PLUGIN_DESCRIPTION = "What this plugin does"

ROUTES = [
    # (regex_pattern, handler_function)
    (r"do the thing", handle_do_thing),
]

def handle_do_thing(text: str, low: str, llm_caller=None) -> str:
    return "Did the thing."

def on_load():
    # Optional: called once when plugin is loaded
    pass
---

Routes are injected into intent_router at the END of the fast-path
(before the LLM fallback), so they don't interfere with core routes.
"""

import importlib.util
import logging
import re
import sys
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

BASE_DIR    = Path(__file__).parent.resolve()
PLUGINS_DIR = BASE_DIR / "plugins"

# Loaded plugin routes: list of (compiled_regex, handler_fn)
_plugin_routes: list[tuple] = []
_loaded_plugins: list[dict] = []


def load_plugins() -> None:
    """Load all .py files from plugins/ directory."""
    PLUGINS_DIR.mkdir(exist_ok=True)
    (PLUGINS_DIR / "__init__.py").touch()

    for plugin_file in sorted(PLUGINS_DIR.glob("*.py")):
        if plugin_file.name.startswith("_"):
            continue
        _load_plugin(plugin_file)

    if _loaded_plugins:
        logger.info("Loaded %d plugin(s): %s",
                    len(_loaded_plugins),
                    ", ".join(p["name"] for p in _loaded_plugins))
    else:
        logger.debug("No plugins found in %s.", PLUGINS_DIR)


def _load_plugin(path: Path) -> None:
    try:
        spec   = importlib.util.spec_from_file_location(path.stem, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[path.stem] = module
        spec.loader.exec_module(module)

        name    = getattr(module, "PLUGIN_NAME",    path.stem)
        version = getattr(module, "PLUGIN_VERSION", "?")
        desc    = getattr(module, "PLUGIN_DESCRIPTION", "")
        routes  = getattr(module, "ROUTES", [])

        for pattern, handler in routes:
            _plugin_routes.append((re.compile(pattern, re.IGNORECASE), handler))

        on_load = getattr(module, "on_load", None)
        if callable(on_load):
            on_load()

        _loaded_plugins.append({"name": name, "version": version, "description": desc})
        logger.info("Plugin loaded: %s v%s — %s", name, version, desc)
    except Exception as e:
        logger.error("Failed to load plugin %s: %s", path.name, e)


def route_plugins(text: str, llm_caller: Callable | None = None) -> str | None:
    """
    Try all plugin routes against text.
    Returns a response string or None if no plugin matched.
    """
    low = text.lower()
    for pattern, handler in _plugin_routes:
        if pattern.search(low):
            try:
                return handler(text, low, llm_caller=llm_caller)
            except Exception as e:
                logger.error("Plugin route error (%s): %s", pattern.pattern, e)
    return None


def list_plugins() -> str:
    if not _loaded_plugins:
        return "No plugins loaded. Place .py files in the plugins/ folder."
    lines = [f"Loaded {len(_loaded_plugins)} plugin(s):"]
    for p in _loaded_plugins:
        lines.append(f"• {p['name']} v{p['version']} — {p['description']}")
    return "\n".join(lines)
