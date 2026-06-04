"""check_system.py — Full Jarvis system diagnostic."""
import json, sys, yaml
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    ok, warn, fail = [], [], []

    # Memory / name
    try:
        mem  = json.loads((ROOT / "data/memory.json").read_text())
        name = mem.get("name", "")
        if name and name not in ("your name", ""):
            ok.append(f"Name: {name}")
        else:
            fail.append("Name not set in data/memory.json")
    except Exception:
        fail.append("data/memory.json missing")

    # Notion
    notion_token = cfg.get("notion", {}).get("token", "")
    if notion_token and "ntn_" in notion_token:
        ok.append("Notion: token configured")
    else:
        fail.append("Notion: token not set in config.yaml")

    # Google Calendar
    cal_email = cfg.get("google_calendar", {}).get("email", "")
    cal_pass  = cfg.get("google_calendar", {}).get("app_password", "")
    if cal_email and cal_pass:
        ok.append(f"Google Calendar: configured ({cal_email})")
    else:
        fail.append("Google Calendar: email or app_password missing")

    # Timezone
    tz = cfg.get("timezone", "")
    if tz:
        ok.append(f"Timezone: {tz}")
    else:
        warn.append("Timezone not set — defaulting to system time")

    # UI mode
    ok.append(f"UI mode: {cfg.get('ui', {}).get('mode', 'hud')}")

    # Wake word model
    try:
        from setup_models import get_oww_model_path
        p = get_oww_model_path()
        if p:
            ok.append("Wake word model: found")
        else:
            fail.append("Wake word model: missing — restart Jarvis to download")
    except Exception as e:
        warn.append(f"Wake word check: {e}")

    # Ollama
    try:
        import requests
        r     = requests.get("http://localhost:11434/api/tags", timeout=2)
        mods  = [m["name"] for m in r.json().get("models", [])]
        model = cfg.get("model", "llama3")
        if any(model in m for m in mods):
            ok.append(f"Ollama: running, {model} ready")
        else:
            warn.append(f"Ollama: running but {model} not pulled — run: ollama pull {model}")
    except Exception:
        fail.append("Ollama: NOT running — start Ollama app or run: ollama serve")

    # WhatsApp
    try:
        import requests
        for acct, port in [("Personal", 5765), ("Uni", 5766)]:
            try:
                r = requests.get(f"http://localhost:{port}/status", timeout=2)
                d = r.json()
                if d.get("connected"):
                    ok.append(f"WhatsApp {acct}: connected")
                else:
                    warn.append(f"WhatsApp {acct}: bridge running but scan QR to connect")
            except Exception:
                fail.append(f"WhatsApp {acct}: bridge not running — run node server.js in whatsapp_bridge{'_uni' if acct == 'Uni' else ''}/")
    except Exception:
        pass

    # Google Calendar connection test
    try:
        from calendar_tool import calendar_status
        s = calendar_status()
        if "connected" in s.lower():
            ok.append("Google Calendar: connected")
        else:
            warn.append(f"Google Calendar: {s}")
    except Exception as e:
        warn.append(f"Google Calendar test: {e}")

    # Notion connection test
    try:
        from notion_tool import notion_status
        s = notion_status()
        if "connected" in s.lower():
            ok.append("Notion: connected")
        else:
            warn.append(f"Notion: {s}")
    except Exception as e:
        warn.append(f"Notion test: {e}")

    # Budget config
    budget_currency = cfg.get("budget", {}).get("currency", "")
    ok.append(f"Budget: currency = {budget_currency or 'EUR (default)'}")

    # Weather location
    weather_loc = cfg.get("weather", {}).get("default_location", "")
    if weather_loc and weather_loc != "Berlin":
        ok.append(f"Weather: location = {weather_loc}")
    elif weather_loc == "Berlin":
        warn.append("Weather: location still set to Berlin — update in config.yaml if needed")

    # Data files
    required = [
        "data/tasks.json", "data/fridge.json", "data/budget.json",
        "data/closet.json", "data/reminders.json", "data/schedule.json",
        "data/sites.json", "data/transactions.json",
        "memory/sessions.json", "memory/progress.json",
        "memory/long_term.json", "memory/wellbeing_log.json",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    if not missing:
        ok.append(f"Data files: all {len(required)} present")
    else:
        fail.append(f"Missing data files: {', '.join(missing)}")

    # RAG knowledge base
    chroma = ROOT / "data" / "chroma_db"
    if chroma.exists():
        ok.append("RAG knowledge base: indexed")
    else:
        warn.append("RAG: not indexed yet — say 'index my notes' to Jarvis")

    # Shortcuts
    if (ROOT / "shortcuts.yaml").exists():
        ok.append("shortcuts.yaml: exists")
    else:
        warn.append("shortcuts.yaml: missing")

    # first_run.flag
    if (ROOT / "first_run.flag").exists():
        ok.append("First-run setup: complete")
    else:
        warn.append("First-run setup: not completed — will run on next Jarvis start")

    # ntfy
    ntfy_topic = cfg.get("ntfy", {}).get("topic", "")
    if ntfy_topic:
        ok.append(f"Phone notifications (ntfy): topic = {ntfy_topic}")
    else:
        warn.append("Phone notifications: ntfy not configured (optional)")

    # Spotify
    spotify_id = cfg.get("spotify", {}).get("client_id", "")
    if spotify_id:
        ok.append("Spotify: client_id configured")
    else:
        warn.append("Spotify: not configured (optional)")

    # Print
    width = 58
    print()
    print("=" * width)
    print("  JARVIS FULL SYSTEM CHECK")
    print("=" * width)
    for item in ok:   print(f"  OK    {item}")
    for item in warn: print(f"  WARN  {item}")
    for item in fail: print(f"  FAIL  {item}")
    print("=" * width)
    print(f"  {len(ok)} OK  |  {len(warn)} warnings  |  {len(fail)} failures")
    print()

    if fail:
        print("  ACTION REQUIRED:")
        for item in fail:
            print(f"    -> {item}")
        print()

if __name__ == "__main__":
    main()
