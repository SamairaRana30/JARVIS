"""
intent_router.py — Fast-path intent routing for Jarvis.
Matches voice commands to tools without hitting the LLM where possible.
Returns (tool_fn, args_dict) or None to fall through to the LLM.
"""

import re
from datetime import date, datetime
from typing import Callable

import tools as t

# ---------------------------------------------------------------------------
# Wellbeing fast-path detection (runs before LLM on every message)
# ---------------------------------------------------------------------------

_MOOD_PATTERNS = [
    (r"\bi('m| am) (really |so |very |quite )?(tired|exhausted|sleepy|drained)\b", "tired"),
    (r"\bi('m| am) (really |so |very |quite )?(stressed|overwhelmed|anxious|worried)\b", "stressed"),
    (r"\bi('m| am) (feeling )?(good|great|amazing|fantastic|happy|motivated)\b", "good"),
    (r"\bi('m| am) (feeling )?(bad|awful|terrible|sad|down|low)\b", "bad"),
    (r"\bi('m| am) (feeling )?(sick|ill|unwell|not well)\b", "sick"),
]
_ENERGY_PATTERNS = [
    (r"\bi have (no|zero|low) energy\b", "low"),
    (r"\bi('m| am) (full of |bursting with )?energy\b", "high"),
    (r"\bi feel (really |so |very )?(energetic|productive|focused)\b", "high"),
]
_SLEEP_PATTERNS = [
    (r"\bi (slept|got) ([\d.]+) hours?\b",  lambda m: m.group(2) + "h"),
    (r"\bi (slept|got) (well|badly|poorly|great|okay)\b", lambda m: m.group(2)),
]


def _detect_wellbeing_fast(text: str) -> dict | None:
    result: dict = {}
    for pattern, mood in _MOOD_PATTERNS:
        if re.search(pattern, text, re.I):
            result["mood"] = mood
            break
    for pattern, energy in _ENERGY_PATTERNS:
        if re.search(pattern, text, re.I):
            result["energy"] = energy
            break
    for pattern, sleep_fn in _SLEEP_PATTERNS:
        m = re.search(pattern, text, re.I)
        if m:
            result["sleep"] = sleep_fn(m) if callable(sleep_fn) else sleep_fn
            break
    return result or None


def _save_wellbeing_fast(data: dict) -> None:
    """Persist detected wellbeing fields to today's wellbeing_log entry."""
    try:
        from datetime import date as _date
        today = _date.today().isoformat()
        wb = t._read_json(t._p("wellbeing"))
        for entry in wb:
            if entry.get("date") == today:
                entry.update(data)
                entry["source"] = "auto-detected"
                t._write_json(t._p("wellbeing"), wb)
                return
        wb.append({
            "date": today, "mood": "", "energy": "", "sleep": "",
            "exercise": "", "hydration_L": 0, "notes": "",
            "source": "auto-detected", **data
        })
        t._write_json(t._p("wellbeing"), wb)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Pending confirmation state (for destructive actions)
# ---------------------------------------------------------------------------

_pending_confirm: dict | None = None


def set_pending_confirm(action: dict | None) -> None:
    global _pending_confirm
    _pending_confirm = action


def get_pending_confirm() -> dict | None:
    return _pending_confirm


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def route(text: str, llm_caller: Callable | None = None) -> str | None:
    """
    Try to match text to a fast-path tool.
    Returns a response string, or None to fall through to the LLM.
    """
    global _pending_confirm
    txt = text.strip()
    low = txt.lower()

    # ── Confirmation handler ────────────────────────────────────────────────
    if _pending_confirm:
        if "yes, confirm" in low:
            action = _pending_confirm
            _pending_confirm = None
            return _execute_confirmed(action)
        else:
            _pending_confirm = None
            return "Action cancelled."

    # ── Datetime ────────────────────────────────────────────────────────────
    if re.search(r"\bwhat\s+time\b", low):
        return datetime.now().strftime("It's %H:%M.")
    if re.search(r"\bwhat\s+day\b", low):
        return datetime.now().strftime("Today is %A.")
    if re.search(r"\bwhat\s+date\b", low):
        return date.today().strftime("Today is %d %B %Y.")

    # ── Config reload ────────────────────────────────────────────────────────
    if "reload config" in low:
        import importlib
        importlib.reload(t)
        return "Config reloaded."

    # ── VOICE OUTPUT TOGGLE ──────────────────────────────────────────────────
    # "Lecture mode" / "go silent" / "voice off" → stops audio, chat only
    if re.search(
        r"\b(lecture\s+mode|go\s+silent|voice\s+off|silent\s+mode|stop\s+speaking|"
        r"i.?m\s+in\s+(a\s+)?lecture|quiet\s+mode|mute\s+voice)\b",
        low,
    ):
        try:
            from tts import set_voice_output
            set_voice_output(False)
        except Exception:
            pass
        # This response goes to chat only (voice is now off)
        return "Silent mode on. I'll respond in the chat panel only. Say 'voice on' to resume speaking."

    # "Voice on" / "speak again" → resume audio
    if re.search(
        r"\b(voice\s+on|speak\s+(again|now|please)|unmute\s+voice|resume\s+speaking|"
        r"lecture\s+(over|done|ended|finished)|stop\s+silent\s+mode)\b",
        low,
    ):
        try:
            from tts import set_voice_output
            set_voice_output(True)
        except Exception:
            pass
        return "Voice output restored. I'll speak normally again."

    if re.search(r"(voice\s+status|are\s+you\s+speaking|is\s+voice\s+on)", low):
        try:
            from tts import voice_status
            return voice_status()
        except Exception:
            return "Voice status unknown."

    # ── NOTE TO APP ───────────────────────────────────────────────────────────
    # "Note this in Notion: [text]"
    m = re.search(r"(?:note|add|save)\s+(?:this\s+)?(?:in|to)\s+(notion|notepad|onenote|one\s+note)[:\s]+(.+)", low)
    if m:
        app  = m.group(1).replace(" ", "")
        text = m.group(2).strip()
        return t.note_to_app(text, app=app)

    # "Open Notion and take a note: [text]" / "Notion note: [text]"
    m = re.search(r"(notion|notepad|onenote|one\s+note)\s+note[:\s]+(.+)", low)
    if m:
        app  = m.group(1).replace(" ", "")
        text = m.group(2).strip()
        return t.note_to_app(text, app=app)

    # "Set my default note app to Notion"
    m = re.search(r"set\s+(?:my\s+)?(?:default\s+)?note\s+app\s+to\s+(notion|notepad|onenote|one\s+note|jarvis)", low)
    if m:
        import yaml
        cfg_path = t.BASE_DIR / "config.yaml"
        try:
            cfg_text = cfg_path.read_text(encoding="utf-8")
            import re as _re2
            new_app = m.group(1).replace(" ", "").lower()
            cfg_text = _re2.sub(
                r'(default_app:\s*)"[^"]*"',
                f'\\1"{new_app}"',
                cfg_text,
            )
            cfg_path.write_text(cfg_text, encoding="utf-8")
            return f"Default note app set to {new_app}. New notes will go there."
        except Exception as e:
            return f"Couldn't update config: {e}"

    # ── LANGUAGE LEARNING ────────────────────────────────────────────────────
    m = re.search(r"(german|deutsch|french|spanish)\s+for\s+(.+)", low)
    if m:
        try:
            from language_learning_tool import translate
            lang_map = {"german": "de", "deutsch": "de", "french": "fr", "spanish": "es"}
            lang = lang_map.get(m.group(1), "de")
            return translate(m.group(2).strip(), to_lang=lang, llm_caller=llm_caller)
        except Exception as e:
            return f"Translation unavailable: {e}"

    m = re.search(r"how\s+do\s+you\s+say\s+(.+?)\s+in\s+(german|french|spanish)", low)
    if m:
        try:
            from language_learning_tool import translate
            lang_map = {"german": "de", "french": "fr", "spanish": "es"}
            lang = lang_map.get(m.group(2), "de")
            return translate(m.group(1).strip(), to_lang=lang, llm_caller=llm_caller)
        except Exception as e:
            return f"Translation unavailable: {e}"

    if re.search(r"quiz\s+me\s+on\s+german\s+(vocab|words?|vocabulary)", low):
        try:
            from language_learning_tool import quiz_vocabulary
            return quiz_vocabulary(n=5)
        except Exception as e:
            return f"Quiz unavailable: {e}"

    if re.search(r"(german|my\s+language)\s+word\s+of\s+the\s+day", low):
        try:
            from language_learning_tool import daily_word
            return daily_word()
        except Exception as e:
            return ""

    m = re.search(r"explain\s+(?:german\s+)?grammar[:\s]+(.+)", low)
    if m:
        try:
            from language_learning_tool import explain_grammar
            return explain_grammar(m.group(1).strip(), llm_caller)
        except Exception as e:
            return f"Grammar explanation unavailable: {e}"

    m = re.search(r"(?:that|it)\s+should\s+be\s+(.+?)\s+not\s+(.+)", low)
    if m:
        try:
            from language_learning_tool import add_correction
            return add_correction(heard=m.group(2).strip(), correct=m.group(1).strip())
        except Exception as e:
            return f"Correction unavailable: {e}"

    if re.search(r"(my\s+)?vocabulary\s+stats?|how\s+many\s+words\s+do\s+i\s+know", low):
        try:
            from language_learning_tool import get_vocab_stats
            return get_vocab_stats()
        except Exception as e:
            return ""

    # ── STUDY SESSIONS ────────────────────────────────────────────────────────
    m = re.search(r"i\s+studied\s+(.+?)\s+for\s+(\d+)\s*(hour|hr|minute|min)", low)
    if m:
        try:
            from study_tracker import log_session_manual
            subject  = m.group(1).strip()
            duration = int(m.group(2))
            if "hour" in m.group(3) or "hr" in m.group(3):
                duration *= 60
            return log_session_manual(subject, duration)
        except Exception as e:
            return f"Study tracker unavailable: {e}"

    m = re.search(r"how\s+long\s+(?:have\s+i\s+)?studied?\s+(.+?)(?:\s+this\s+(week|month|today))?$", low)
    if m:
        try:
            from study_tracker import subject_stats
            period = m.group(2) or "week"
            return subject_stats(m.group(1).strip(), period)
        except Exception as e:
            return f"Study tracker unavailable: {e}"

    if re.search(r"(study\s+report|what\s+subject\s+needs\s+more\s+time|study\s+gaps?)", low):
        try:
            from study_tracker import gaps_analysis
            return gaps_analysis()
        except Exception as e:
            return f"Study tracker unavailable: {e}"

    # ── MACROS ────────────────────────────────────────────────────────────────
    if re.search(r"(add|create|new)\s+macro", low):
        return "To add a macro, edit shortcuts.yaml or data/macros.json directly. Say the trigger phrase to run it."

    m = re.search(r"delete\s+macro\s+(.+)", low)
    if m:
        try:
            from shortcuts_engine import delete_macro
            return delete_macro(m.group(1).strip())
        except Exception as e:
            return f"Could not delete macro: {e}"

    if re.search(r"(list|show|what)\s+(my\s+)?macros?", low):
        try:
            from shortcuts_engine import list_shortcuts
            return list_shortcuts()
        except Exception as e:
            return ""

    # ── PROJECT STATUS ────────────────────────────────────────────────────────
    m = re.search(r"(?:stylemate|project)\s+status|status\s+of\s+(.+)", low)
    if m:
        project = m.group(1).strip() if m.group(1) else "StyleMate"
        return t.project_status(project)

    if re.search(r"all\s+projects?\s+status|show\s+(?:my\s+)?projects?", low):
        return t.project_status()

    # ── LANGUAGE SWITCHING ───────────────────────────────────────────────────
    if re.search(r"(switch\s+to\s+german|auf\s+deutsch|sprich\s+deutsch|speak\s+german)", low):
        import jarvis as _j
        return _j.set_language("de")

    if re.search(r"(switch\s+to\s+english|back\s+to\s+english|speak\s+english|auf\s+englisch)", low):
        import jarvis as _j
        return _j.set_language("en")

    # Generic: "switch to [language]"
    m = re.search(r"switch\s+to\s+(french|spanish|italian|dutch|german|english)", low)
    if m:
        lang_map = {"french": "fr", "spanish": "es", "italian": "it",
                    "dutch": "nl", "german": "de", "english": "en"}
        code = lang_map[m.group(1)]
        import jarvis as _j
        return _j.set_language(code)

    if re.search(r"what\s+language\s+(are\s+you|do\s+you|is\s+jarvis)", low):
        import jarvis as _j
        return _j.language_status()

    # ── App index ────────────────────────────────────────────────────────────
    if re.search(r"(refresh|update|rebuild|rescan)\s+(app|apps|application)\s+(list|index|cache)", low):
        return t.refresh_app_index()

    if re.search(r"(how many|what|which)\s+apps?\s+(do you know|can you open|are available)", low):
        idx = t.get_app_index()
        return f"I can open {len(idx)} apps on this device. Just say 'open' and the app name."

    # ── STOP / QUIT ──────────────────────────────────────────────────────────
    # Require explicit target so "stop pomodoro" / "stop the music" don't match
    if re.search(
        r"\b(quit|exit|shutdown|goodbye|bye)\b"
        r"|\b(stop|turn off|shut down)\s+(jarvis|yourself|listening)\b",
        low,
    ):
        import jarvis as _j
        _j.request_quit()
        return "Goodbye."

    # ── ALARMS & REMINDERS ───────────────────────────────────────────────────

    # "What reminders do I have?" / "List my reminders"
    if re.search(r"(what|list|show)\s+(reminders?|alarms?)", low) or \
       re.search(r"(reminders?|alarms?)\s+(do\s+i\s+have|i\s+have)", low):
        return t.list_reminders()

    # "Move / reschedule / change / edit my [x] reminder to [time]"
    m = re.search(
        r"(?:move|reschedule|change|edit|update|set)\s+(?:my\s+)?(.+?)\s+"
        r"(?:reminder|alarm)\s+to\s+(.+)",
        low,
    )
    if m:
        return t.edit_reminder(m.group(1).strip(), m.group(2).strip())

    # "Remind me for Thursday" / "Change [x] to Thursday" with a pending reminder context
    m = re.search(
        r"remind\s+me\s+(?:for|on)\s+((?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today).+?)(?:\s+to\s+(.+))?$",
        low,
    )
    if m:
        when_str = m.group(1).strip()
        msg      = m.group(2).strip() if m.group(2) else None
        if msg:
            dt = t.parse_reminder_time(when_str)
            if dt:
                return t.create_reminder(msg, dt)
        else:
            # No message — assume they want to reschedule the most recent reminder
            reminders = t._read_json(t._p("reminders"))
            pending = [r for r in reminders if not r.get("done")]
            if pending:
                latest = sorted(pending, key=lambda r: r.get("created", ""), reverse=True)[0]
                return t.edit_reminder(latest["message"], when_str)

    # "Cancel my [x] reminder"
    m = re.search(r"cancel\s+(my\s+)?(.+?)\s+(reminder|alarm)", low)
    if m:
        return t.cancel_reminder(m.group(2).strip())

    # "Set an alarm for [time]"
    m = re.search(r"set\s+an?\s+alarm\s+for\s+(.+)", low)
    if m:
        dt = t.parse_reminder_time(m.group(1).strip())
        if dt:
            return t.create_reminder("Alarm", dt, kind="alarm")
        return "I couldn't understand that time. Try 'set an alarm for 7:30am'."

    # "Remind me every day at [time] to [message]"
    m = re.search(r"remind\s+me\s+every\s+day\s+at\s+(.+?)\s+to\s+(.+)", low)
    if m:
        dt = t.parse_reminder_time(f"at {m.group(1).strip()}")
        if dt:
            return t.create_reminder(m.group(2).strip(), dt, repeat="daily")
        return "I couldn't parse that time."

    # "Remind me every week on [day] at [time] to [message]"
    m = re.search(r"remind\s+me\s+every\s+week.+?to\s+(.+)", low)
    if m:
        time_part = re.search(r"at\s+([\w\s:]+?)\s+to", low)
        if time_part:
            dt = t.parse_reminder_time(f"next week at {time_part.group(1)}")
            if dt:
                return t.create_reminder(m.group(1).strip(), dt, repeat="weekly")

    # "Remind me in [X] minutes/hours to [message]"
    m = re.search(r"remind\s+me\s+(in\s+[\d]+\s+(?:minutes?|hours?|secs?))\s+to\s+(.+)", low)
    if m:
        dt = t.parse_reminder_time(m.group(1).strip())
        if dt:
            return t.create_reminder(m.group(2).strip(), dt)
        return "I couldn't understand that time."

    # "Remind me at [time] to [message]"
    m = re.search(r"remind\s+me\s+(.+?)\s+to\s+(.+)", low)
    if m:
        time_str = m.group(1).strip()
        msg      = m.group(2).strip()
        dt = t.parse_reminder_time(time_str)
        if dt:
            repeat = t._detect_repeat(low)
            return t.create_reminder(msg, dt, repeat=repeat)
        return f"I couldn't understand '{time_str}'. Try 'at 3pm', 'in 30 minutes', or 'tomorrow at 9am'."

    # ── MODES/STUDY — check before PC control so "start study mode" isn't treated as an app ──
    if re.search(r"start\s+study\s+mode", low):
        _pending_confirm = {"action": "start_study_mode"}
        return "Study mode will block distracting sites. Say 'yes, confirm' to proceed."
    if re.search(r"end\s+study\s+mode", low):
        return t.end_study_mode()

    # ── POMODORO — check before PC control so "start pomodoro" isn't treated as an app ──
    if re.search(r"start\s+pomodoro", low):
        return t.start_pomodoro()

    m = re.search(r"start\s+(?:a\s+)?(\d+)[- ]?minute\s+(?:timer|pomodoro|session)", low)
    if m:
        return t.start_pomodoro(work_minutes=float(m.group(1)))

    # ── PC CONTROL — explicit app routes ────────────────────────────────────
    # "open my notes" → ask which app
    if re.search(r"open\s+(my\s+)?notes?$", low):
        return "Which app would you like? Say Notion, OneNote, or Notepad."

    # Direct named-app shortcuts (bypass LLM entirely)
    _DIRECT_APPS = {
        r"notion":        "notion",
        r"one\s*note":    "onenote",
        r"notepad\+\+":   "notepad++",
        r"notepad":       "notepad",
        r"calculator|calc": "calculator",
        r"chrome":        "chrome",
        r"firefox":       "firefox",
        r"edge":          "edge",
        r"vs\s*code|vscode": "vscode",
        r"spotify":       "spotify",
        r"discord":       "discord",
        r"file\s*explorer|explorer": "explorer",
        r"task\s*manager": "task manager",
        r"paint":         "paint",
        r"word":          "word",
        r"excel":         "excel",
        r"powerpoint":    "powerpoint",
        r"teams":         "teams",
        r"zoom":          "zoom",
        r"whatsapp":      "whatsapp",
        r"telegram":      "telegram",
        r"obs":           "obs",
        r"spotify":       "spotify",
    }
    for pattern, app_key in _DIRECT_APPS.items():
        if re.search(r"open\s+" + pattern, low) or re.search(r"launch\s+" + pattern, low) or re.search(r"start\s+" + pattern, low):
            return t.open_app_or_site(app_key)

    # Generic "open [anything]"
    m = re.match(r"(?:open|launch|start)\s+(.+)", low)
    if m:
        target = m.group(1).strip()
        return t.open_app_or_site(target)

    # ── TASKS ───────────────────────────────────────────────────────────────
    m = re.match(r"add\s+task\s+(.+)", low)
    if m:
        title = m.group(1).strip()
        deadline = _extract_deadline(txt)
        return t.add_task(title, deadline)

    if re.search(r"(what are|list|show)\s+(my\s+)?tasks?\s+(today|for today)", low):
        return t.list_tasks(today_only=True)

    if re.search(r"(what are|list|show)\s+(my\s+)?tasks?", low):
        return t.list_tasks()

    m = re.match(r"mark\s+(.+?)\s+(as\s+)?done", low)
    if m:
        return t.mark_task_done(m.group(1).strip())

    m = re.search(r"how\s+many\s+hours\s+until\s+(.+)", low)
    if m:
        return t.hours_until_deadline(m.group(1).strip())

    # ── NOTES ───────────────────────────────────────────────────────────────
    def _default_note(text: str, folder: str = "quick") -> str:
        """Route note to default_app from config."""
        try:
            import yaml
            cfg = yaml.safe_load((t.BASE_DIR / "config.yaml").read_text())
            default_app = cfg.get("notes", {}).get("default_app", "jarvis")
            if default_app != "jarvis":
                return t.note_to_app(text, app=default_app)
        except Exception:
            pass
        return t.save_note(text, folder=folder)

    m = re.match(r"note\s+this[:\s]+(.+)", low)
    if m:
        return _default_note(m.group(1).strip())

    m = re.match(r"study\s+note[:\s]+(.+)", low)
    if m:
        return t.save_note(m.group(1).strip(), folder="study")

    m = re.match(r"project\s+note\s+for\s+(\w+)[:\s]+(.+)", low)
    if m:
        return t.save_note(m.group(2).strip(), folder="projects", project=m.group(1))

    m = re.match(r"idea[:\s]+(.+)", low)
    if m:
        return t.save_note(m.group(1).strip(), folder="ideas")

    m = re.search(r"find\s+(my\s+)?notes?\s+about\s+(.+)", low)
    if m:
        return t.search_notes(m.group(2).strip())

    m = re.search(r"read\s+(my\s+)?note\s+about\s+(.+)", low)
    if m:
        return t.read_note(m.group(2).strip())

    m = re.search(r"summarise\s+(my\s+)?notes?\s+about\s+(.+)", low)
    if m:
        return t.summarise_notes(m.group(2).strip(), llm_caller)

    if re.search(r"summarise\s+today.?s\s+notes?", low):
        return t.summarise_notes("today", llm_caller)

    if re.search(r"organise\s+(my\s+)?notes?", low):
        return t.organise_notes()

    m = re.search(r"show\s+(me\s+)?(all\s+)?my\s+(\w+)\s+notes?", low)
    if m:
        return t.list_notes(m.group(3))

    # "show me my notes" / "list my notes" / "show notes" (no topic)
    if re.search(r"(show|list|see)\s+(me\s+)?(my\s+)?notes?", low):
        return t.list_notes("quick") or t.search_notes("")

    # "make a note" / "note that" / "take a note"
    m = re.search(r"(?:make|take)\s+a\s+note(?:\s+(?:of|that|about))?\s*[:\-]?\s*(.+)", low)
    if m:
        return _default_note(m.group(1).strip())

    # ── FRIDGE ──────────────────────────────────────────────────────────────
    if re.search(r"what.?s\s+(in\s+my\s+|my\s+)?fridge", low):
        return t.fridge_list()

    if re.search(r"(what.?s\s+)?expir(ing|ed)\s+soon", low):
        return t.fridge_expiry_check()

    m = re.match(r"add\s+(.+?)\s+expir(?:ing|es)\s+(.+)", low)
    if m:
        name = m.group(1).strip()
        expires_raw = m.group(2).strip()
        expires = _parse_date_str(expires_raw)
        return t.fridge_add(name, expires=expires)

    m = re.match(r"i\s+used\s+(.+)", low)
    if m:
        return t.fridge_remove(m.group(1).strip())

    m = re.match(r"add\s+(.+?)\s+to\s+grocery\s+list", low)
    if m:
        return t.grocery_add(m.group(1).strip())

    # "What's on my grocery list?"
    if re.search(r"(what.?s\s+on|read|show|list)\s+(my\s+)?grocery\s+list", low):
        return t.grocery_list_read()

    # "Clear my grocery list"
    if re.search(r"clear\s+(my\s+)?grocery\s+list", low):
        _pending_confirm = {"action": "grocery_clear"}
        return "Clear your entire grocery list? Say 'yes, confirm' to proceed."

    # "Remove [item] from grocery list"
    m = re.match(r"remove\s+(.+?)\s+from\s+(my\s+)?grocery", low)
    if m:
        return t.grocery_remove_item(m.group(1).strip())

    if re.search(r"what\s+can\s+i\s+make", low):
        return t.suggest_recipe(llm_caller)

    # "What am I missing for [recipe]?" / "What do I need for [recipe]?"
    m = re.search(
        r"what\s+(am\s+i\s+missing|do\s+i\s+need|ingredients?\s+do\s+i\s+need)\s+for\s+(.+)",
        low,
    )
    if m:
        return t.check_missing_for_recipe(m.group(2).strip(), llm_caller)

    # "Yes" / "Add it" / "Add all" after a recipe suggestion with missing ingredients
    if re.search(r"^(yes|add\s+it|add\s+all|add\s+them)$", low.strip()):
        if t._last_missing_ingredients:
            return t.add_missing_to_grocery()

    # ── SITES ───────────────────────────────────────────────────────────────
    if re.search(r"what\s+sites\s+are\s+blocked", low):
        return t.sites_list("distracting")

    if re.search(r"(what are|show|list)\s+(my\s+)?study\s+sites?", low):
        return t.sites_list("study")

    m = re.match(r"add\s+(.+?)\s+to\s+distracting\s+sites?", low)
    if m:
        return t.sites_add(m.group(1).strip(), "distracting")

    m = re.match(r"add\s+(.+?)\s+to\s+study\s+sites?", low)
    if m:
        return t.sites_add(m.group(1).strip(), "study")

    m = re.match(r"remove\s+(.+?)\s+from\s+(distracting|study)\s+sites?", low)
    if m:
        site = m.group(1).strip()
        cat  = m.group(2).strip()
        _pending_confirm = {"action": "sites_remove", "site": site, "category": cat}
        return f"Are you sure you want to remove {site} from {cat} sites? Say 'yes, confirm' to proceed."

    # ── SYSTEM INFO ─────────────────────────────────────────────────────────
    if re.search(r"\bbattery\b", low):
        return t.get_system_info("battery")
    if re.search(r"\bcpu\b", low):
        return t.get_system_info("cpu")
    if re.search(r"\bram\b|\bmemory\s+usage\b", low):
        return t.get_system_info("ram")
    if re.search(r"\bstorage\b|\bdisk\b", low):
        return t.get_system_info("storage")
    if re.search(r"\bwifi\b|\bnetwork\b", low):
        return t.get_system_info("wifi")

    # ── MODES / PROFILES ────────────────────────────────────────────────────
    m = re.search(r"switch\s+to\s+(study|work|chill)\s+mode", low)
    if m:
        return t.switch_profile(m.group(1))

    m = re.search(r"(study|work|chill)\s+mode", low)
    if m:
        profile = m.group(1)
        if "end" in low or "stop" in low or "exit" in low:
            if profile == "study":
                return t.end_study_mode()
        return t.launch_routine(profile)

    if re.search(r"start\s+study\s+mode", low):
        _pending_confirm = {"action": "start_study_mode"}
        return "Study mode will block distracting sites. Say 'yes, confirm' to proceed."

    if re.search(r"end\s+study\s+mode", low):
        return t.end_study_mode()

    # ── BACKGROUND SOUND ────────────────────────────────────────────────────
    # "switch to rain sounds" / "switch to lofi" / "put on white noise"
    m = re.search(
        r"(?:switch\s+to|put\s+on|play)\s+(lofi|lo.?fi|rain|white\s+noise|white_noise)\s*(?:sounds?)?",
        low,
    )
    if m:
        raw = m.group(1).strip().replace(" ", "_").replace("-", "_")
        name = "lofi" if "lofi" in raw or "lo_fi" in raw else raw
        return t.switch_sound(name)

    if re.search(r"turn\s+off\s+(background\s+)?sound|stop\s+(the\s+)?(music|sound)", low):
        return t.stop_background_sound()

    if re.search(r"what\s+sound\s+(is\s+)?(playing|on)", low):
        return t.get_current_sound()

    # ── POMODORO ─────────────────────────────────────────────────────────────
    # "Start Pomodoro"
    if re.search(r"start\s+pomodoro", low):
        return t.start_pomodoro()

    # "Start 45 minute timer" / "Start a 30-minute Pomodoro"
    m = re.search(r"start\s+(?:a\s+)?(\d+)[- ]?minute\s+(?:timer|pomodoro|session)", low)
    if m:
        return t.start_pomodoro(work_minutes=float(m.group(1)))

    # "How long left?" / "How much time left?"
    if re.search(r"how\s+(long|much\s+time)\s+(is\s+)?(left|remaining)", low):
        return t.pomodoro_time_left()

    # "Skip this break" / "Skip the break"
    if re.search(r"skip\s+(this\s+|the\s+)?break", low):
        return t.pomodoro_skip_break()

    # "Stop Pomodoro" / "Cancel Pomodoro" / "Stop the timer"
    if re.search(r"(stop|cancel|end)\s+(the\s+)?pomodoro|(stop|cancel)\s+(the\s+)?timer", low):
        return t.stop_pomodoro()

    # "How many Pomodoros today?" / "How many cycles today?"
    if re.search(r"how\s+many\s+(pomodoros?|cycles?)\s+(today|this\s+session)", low):
        return t.pomodoro_count()

    # ── LIFE SUMMARY ────────────────────────────────────────────────────────
    if re.search(
        r"how\s+am\s+i\s+doing"
        r"|give\s+me\s+a\s+(life\s+)?summary"
        r"|how.?s\s+everything(\s+going)?"
        r"|how\s+have\s+i\s+been"
        r"|life\s+update",
        low,
    ):
        return t.life_summary()

    # ── MEMORY ──────────────────────────────────────────────────────────────
    m = re.search(r"what\s+did\s+we\s+talk\s+about\s+(.+)", low)
    if m:
        return t.get_session_summary(m.group(1).strip())

    if re.search(r"(what\s+were\s+we|what\s+was\s+i)\s+working\s+on\s+last\s+time", low):
        return t.get_session_summary()

    if re.search(r"what\s+did\s+i\s+leave\s+unfinished", low):
        return t.get_session_summary()

    m = re.search(r"search\s+(our\s+)?conversations?\s+for\s+(.+)", low)
    if m:
        return t.search_transcripts(m.group(2).strip())

    m = re.search(r"what\s+decisions\s+(have\s+i\s+made\s+)?about\s+(.+)", low)
    if m:
        return t.get_decisions(m.group(2).strip())

    if re.search(r"(why\s+did\s+i\s+decide|what\s+did\s+you\s+say\s+you.?d\s+follow\s+up)", low):
        return t.get_followups()

    m = re.search(r"how\s+(have\s+i\s+been\s+feeling|am\s+i\s+feeling)\s*(this\s+week|this\s+month)?", low)
    if m:
        return t.get_wellbeing()

    m = re.search(r"how\s+much\s+progress\s+(have\s+we\s+made\s+on|on)\s+(.+)", low)
    if m:
        return t.get_progress(m.group(2).strip())

    m = re.search(r"update\s+(.+?)\s+progress\s+to\s+(\d+)%?", low)
    if m:
        return t.update_progress(m.group(1).strip(), int(m.group(2)))

    if re.search(r"what\s+do\s+you\s+know\s+about\s+me", low):
        return t.get_long_term_facts()

    m = re.search(r"forget\s+that\s+i\s+said\s+(.+)", low)
    if m:
        fragment = m.group(1).strip()
        _pending_confirm = {"action": "forget_fact", "fragment": fragment}
        return f"Remove all memory of '{fragment}'? Say 'yes, confirm' to proceed."

    if re.search(r"(what\s+did\s+i\s+complete|what\s+have\s+i\s+completed)\s+(this\s+week|today)?", low):
        return t.get_progress()

    # ── WEATHER ─────────────────────────────────────────────────────────────
    # "What's the weather in London?"
    m = re.search(r"weather\s+in\s+([a-zA-Z\s]+?)(?:\?|$)", low)
    if m:
        return t.get_weather(location=m.group(1).strip())

    # "Will it rain today?"
    if re.search(r"\b(rain|raining|umbrella|precipitation)\b", low):
        loc = None
        m2 = re.search(r"in\s+([a-zA-Z\s]+?)(?:\?|$)", low)
        if m2:
            loc = m2.group(1).strip()
        return t.get_weather(location=loc, query="rain")

    # "What's the forecast this week?"
    if re.search(r"\bforecast\b|\bweather\s+(this\s+week|tomorrow|next\s+few)", low):
        return t.get_weather(query="forecast")

    # "What should I wear today?"
    if re.search(r"(what\s+should\s+i\s+wear|what\s+to\s+wear|dress\s+for\s+today)", low):
        return t.get_weather(query="outfit")

    # Generic "what's the weather?"
    if re.search(r"\bweather\b", low):
        return t.get_weather()

    # ── CALCULATOR ──────────────────────────────────────────────────────────
    if re.search(r"\bcalculate\b|\bcompute\b|\bwhat\s+is\s+[\d]", low):
        expr = re.sub(r"(calculate|compute|what\s+is)\s*", "", txt, flags=re.IGNORECASE).strip()
        return t.calculate(expr)

    # ── CLIPBOARD ───────────────────────────────────────────────────────────
    # Flow: user copies something (Ctrl+C) → says one of these → Jarvis reads + explains
    if re.search(
        r"(explain|what\s+is|what.?s|summarise|read)\s+(my\s+|the\s+)?clipboard"
        r"|\bexplain\s+this\b"
        r"|\bwhat\s+did\s+i\s+copy\b"
        r"|\bread\s+what.?s?\s+(copied|in\s+my\s+clipboard)\b"
        r"|\bclipboard\b",
        low,
    ):
        return t.explain_clipboard(llm_caller)

    # ── CALENDAR ─────────────────────────────────────────────────────────────
    if re.search(r"(what.?s\s+on\s+my\s+calendar\s+today|today.?s\s+(events?|schedule|calendar))", low):
        try:
            from calendar_tool import get_today_events
            return get_today_events()
        except Exception as e:
            return f"Calendar unavailable: {e}"

    if re.search(r"(tomorrow.?s\s+(events?|schedule|calendar)|what.?s\s+on\s+tomorrow)", low):
        try:
            from calendar_tool import get_tomorrow_events
            return get_tomorrow_events()
        except Exception as e:
            return f"Calendar unavailable: {e}"

    if re.search(r"(this\s+week.?s?\s+(events?|schedule|calendar)|what.?s\s+(on\s+)?this\s+week)", low):
        try:
            from calendar_tool import get_week_events
            return get_week_events()
        except Exception as e:
            return f"Calendar unavailable: {e}"

    if re.search(r"(upcoming\s+events?|what.?s\s+coming\s+up|any\s+(events?|meetings?)\s+(soon|this\s+week))", low):
        try:
            from calendar_tool import get_upcoming_events
            return get_upcoming_events()
        except Exception as e:
            return f"Calendar unavailable: {e}"

    # "add event [title] on [date] at [time]"
    m = re.search(r"add\s+(?:a\s+)?(?:calendar\s+)?event\s+['\"]?(.+?)['\"]?\s+on\s+(.+)", low)
    if m:
        try:
            from calendar_tool import add_calendar_event
            return add_calendar_event(m.group(1).strip(), m.group(2).strip())
        except Exception as e:
            return f"Calendar unavailable: {e}"

    if re.search(r"(is\s+calendar\s+connected|calendar\s+status)", low):
        try:
            from calendar_tool import calendar_status
            return calendar_status()
        except Exception as e:
            return f"Calendar unavailable: {e}"

    # ── NOTION ───────────────────────────────────────────────────────────────
    if re.search(r"(show|list|what.?s\s+in)\s+(my\s+)?notion\s+pages?", low):
        try:
            from notion_tool import notion_list_pages
            return notion_list_pages()
        except Exception as e:
            return f"Notion unavailable: {e}"

    m = re.search(r"search\s+notion\s+(for\s+)?(.+)", low)
    if m:
        try:
            from notion_tool import notion_search
            return notion_search(m.group(2).strip())
        except Exception as e:
            return f"Notion unavailable: {e}"

    m = re.search(r"read\s+(my\s+)?notion\s+page\s+(?:about\s+|called\s+)?(.+)", low)
    if m:
        try:
            from notion_tool import notion_read_page
            return notion_read_page(m.group(2).strip())
        except Exception as e:
            return f"Notion unavailable: {e}"

    m = re.search(r"create\s+(?:a\s+)?notion\s+page\s+(?:called\s+)?['\"]?(.+?)['\"]?(?:\s+with\s+(.+))?$", low)
    if m:
        try:
            from notion_tool import notion_create_page
            return notion_create_page(m.group(1).strip(), m.group(2) or "")
        except Exception as e:
            return f"Notion unavailable: {e}"

    m = re.search(r"add\s+to\s+(?:my\s+)?notion\s+(?:page\s+)?['\"]?(.+?)['\"]?\s*[:\-]\s*(.+)", low)
    if m:
        try:
            from notion_tool import notion_append_to_page
            return notion_append_to_page(m.group(1).strip(), m.group(2).strip())
        except Exception as e:
            return f"Notion unavailable: {e}"

    m = re.search(r"add\s+(?:a\s+)?(?:notion\s+)?todo\s+(?:to\s+)?['\"]?(.+?)['\"]?\s*[:\-]\s*(.+)", low)
    if m:
        try:
            from notion_tool import notion_add_todo
            return notion_add_todo(m.group(1).strip(), m.group(2).strip())
        except Exception as e:
            return f"Notion unavailable: {e}"

    if re.search(r"(analyse|analyze|check|organise|organize)\s+(my\s+)?notion", low):
        try:
            from notion_tool import notion_analyse_workspace
            return notion_analyse_workspace(llm_caller)
        except Exception as e:
            return f"Notion unavailable: {e}"

    if re.search(r"(is\s+notion\s+connected|notion\s+status)", low):
        try:
            from notion_tool import notion_status
            return notion_status()
        except Exception as e:
            return f"Notion unavailable: {e}"

    # ── REMINDERS ────────────────────────────────────────────────────────────
    if re.search(r"(what.?s\s+(coming\s+up|due|on)|remind\s+me\s+what.?s\s+due)", low):
        parts = []
        tasks = t.list_tasks()
        if tasks and "No pending" not in tasks:
            parts.append("Pending tasks:\n" + tasks)
        try:
            from calendar_tool import get_upcoming_events
            cal = get_upcoming_events(days=2)
            if cal and "Nothing" not in cal:
                parts.append(cal)
        except Exception:
            pass
        return "\n\n".join(parts) if parts else "Nothing pending at the moment."

    # ── REPEAT ──────────────────────────────────────────────────────────────
    if re.search(
        r"\b(repeat\s+that|say\s+that\s+again|pardon|what\s+did\s+you\s+say"
        r"|i\s+didn.?t\s+hear\s+that|can\s+you\s+repeat|come\s+again)\b",
        low,
    ):
        import jarvis as _j
        return _j.repeat_last()

    # ── VOLUME / SPEED CONTROL ───────────────────────────────────────────────
    if re.search(r"speak\s+(louder|up|volume\s+up|increase\s+volume)|louder\s+please", low):
        return t.voice_settings_tool("louder")
    if re.search(r"speak\s+(quieter|softer|lower|quieter|down|volume\s+down|decrease\s+volume)|quieter\s+please", low):
        return t.voice_settings_tool("quieter")
    if re.search(r"speak\s+(faster|quicker|speed\s+up)|faster\s+please", low):
        return t.voice_settings_tool("faster")
    if re.search(r"speak\s+(slower|more\s+slowly|slow\s+down)|slower\s+please", low):
        return t.voice_settings_tool("slower")
    if re.search(r"\b(normal\s+speed|normal\s+volume|reset\s+voice|default\s+speed)\b", low):
        return t.voice_settings_tool("reset")
    if re.search(r"(what\s+volume|how\s+loud|what\s+speed|how\s+fast)\s+(are\s+you|is\s+your\s+voice)", low):
        return t.voice_settings_tool("status")

    # ── SLEEP MODE ───────────────────────────────────────────────────────────
    if re.search(
        r"\b(go\s+to\s+sleep|sleep\s+mode|jarvis\s+sleep|goodnight|good\s+night)\b",
        low,
    ):
        import jarvis as _j
        return _j.go_to_sleep()

    if re.search(r"\bgood\s+morning\b", low):
        import jarvis as _j
        return _j.wake_from_sleep(good_morning=True)

    if re.search(r"\b(wake\s+up|resume\s+jarvis)\b", low):
        import jarvis as _j
        if _j.is_sleeping():
            return _j.wake_from_sleep(good_morning=False)

    # ── NEW SESSION ──────────────────────────────────────────────────────────
    if re.search(
        r"\b(start\s+a?\s*new\s+session"
        r"|fresh\s+start"
        r"|clear\s+(our\s+)?conversation"
        r"|reset\s+(jarvis|conversation|history)"
        r"|\breset\b)\b",
        low,
    ):
        import jarvis as _j
        return _j.start_new_session()

    # ── BACKUP ───────────────────────────────────────────────────────────────
    if re.search(r"\b(back\s*up\s+everything|export\s+(my\s+)?data|backup\s+data|save\s+a\s+backup)\b", low):
        return t.backup_everything()

    if re.search(r"when\s+(was|did)\s+(my\s+)?(last|latest)\s+backup", low):
        return t.last_backup_time()

    # ── TASK PRIORITY ────────────────────────────────────────────────────────
    # "what's my most important task"
    if re.search(r"(what.?s\s+my\s+)?(most\s+important|top\s+priority|highest\s+priority)\s+task", low):
        return t.get_top_task()

    # "change [task] to high priority"
    m = re.search(r"(change|set|update|mark)\s+(.+?)\s+(?:to|as)\s+(high|medium|low)\s+priority", low)
    if m:
        return t.update_task_priority(m.group(2).strip(), m.group(3))

    m = re.search(r"add\s+(high|medium|low)\s+priority\s+task\s+(.+)", low)
    if m:
        priority, title = m.group(1), m.group(2).strip()
        deadline = _extract_deadline(txt)
        return t.add_task(title, deadline, priority=priority)

    # "add urgent task: [x]" → high priority
    m = re.search(r"add\s+(?:urgent|critical|important)\s+task[:\s]+(.+)", low)
    if m:
        deadline = _extract_deadline(txt)
        return t.add_task(m.group(1).strip(), deadline, priority="high")

    # ── DOCTOR / DIAGNOSTICS ─────────────────────────────────────────────────
    if re.search(
        r"\b(run\s+diagnostics|are\s+you\s+healthy|jarvis\s+doctor"
        r"|doctor|check\s+yourself|self\s+check|system\s+check)\b",
        low,
    ):
        return t.jarvis_doctor()

    # ── HELP ─────────────────────────────────────────────────────────────────
    if re.search(
        r"\b(what\s+can\s+you\s+do"
        r"|help"
        r"|show\s+(me\s+)?(your\s+)?commands?"
        r"|what\s+do\s+you\s+know"
        r"|list\s+(commands?|capabilities|features)"
        r"|what\s+are\s+you\s+capable\s+of)\b",
        low,
    ):
        return t.help_tool()

    # ── NOTES EDIT ───────────────────────────────────────────────────────────
    m = re.search(r"add\s+to\s+my\s+(.+?)\s+note[:\s]+(.+)", low)
    if m:
        return t.append_to_note(m.group(1).strip(), m.group(2).strip())

    m = re.search(r"edit\s+my\s+note\s+about\s+(.+)", low)
    if m:
        return t.open_note_in_editor(m.group(1).strip())

    # ── EXERCISE & WATER TRACKING ────────────────────────────────────────────
    # "I went for a 30 min walk" / "I did 45 minutes of yoga" / "I exercised today"
    m = re.search(
        r"i\s+(?:went\s+(?:for\s+(?:a\s+)?)?|did\s+(?:a\s+)?|went\s+to\s+the\s+)?"
        r"((?:[\d]+\s*(?:min|minute|hour|km|k)?\s*)?"
        r"(?:run|walk|jog|swim|gym|yoga|workout|exercise|cycling|hike|football|tennis|basketball)[^.]*)",
        low,
    )
    if m:
        activity = m.group(1).strip()
        return t.log_exercise(activity)

    if re.search(r"\b(i\s+exercised|log\s+(my\s+)?exercise|exercised\s+today)\b", low):
        m2 = re.search(r"([\d]+\s*(?:min|minute|hour))", low)
        duration = m2.group(1) if m2 else ""
        return t.log_exercise("exercised", duration)

    if re.search(r"\b(worked\s+out|hit\s+the\s+gym)\b", low):
        return t.log_exercise("worked out")

    # Hydration — handles litres, glasses, cups, ml
    m = re.search(
        r"(?:drank?|had|drunk|consumed|log(?:ged)?)\s+"
        r"([\d.]+\s*(?:litre|liter|L|l|glass|glasses|cup|cups|ml|millil))",
        low,
    )
    if m:
        amount = t.parse_hydration_amount(m.group(1))
        return t.log_hydration(amount)

    if re.search(r"\b(log\s+(?:my\s+)?(?:water|hydration)|drank?\s+water)\b", low):
        m2 = re.search(r"([\d.]+)", low)
        amount = t.parse_hydration_amount(m2.group(0)) if m2 else 1.0
        return t.log_hydration(amount)

    # ── EMAIL ────────────────────────────────────────────────────────────────
    if re.search(r"\b(check|read|show|any)\s+(my\s+)?emails?\b", low):
        try:
            from email_tool import get_unread_emails
            return get_unread_emails()
        except Exception as e:
            return f"Email unavailable: {e}"

    if re.search(r"read\s+(the\s+)?latest\s+email", low):
        try:
            from email_tool import read_latest_email
            return read_latest_email(llm_caller)
        except Exception as e:
            return f"Email unavailable: {e}"

    if re.search(r"how\s+many\s+(unread\s+)?emails?", low):
        try:
            from email_tool import get_email_count
            return get_email_count()
        except Exception as e:
            return f"Email unavailable: {e}"

    # ── NEWS ─────────────────────────────────────────────────────────────────
    if re.search(r"(what.?s\s+in\s+the\s+news|latest\s+news|news\s+headlines?|top\s+stories?)", low):
        try:
            from news_tool import get_headlines
            src = "tech" if "tech" in low else "world" if "world" in low else "bbc"
            return get_headlines(src)
        except Exception as e:
            return f"News unavailable: {e}"

    # ── FLASHCARDS ───────────────────────────────────────────────────────────
    if re.search(r"quiz\s+me\s+on\s+(.+)", low):
        m2 = re.search(r"quiz\s+me\s+on\s+(.+)", low)
        if m2:
            try:
                from flashcard_tool import start_quiz
                return start_quiz(m2.group(1).strip(), llm_caller)
            except Exception as e:
                return f"Flashcard error: {e}"

    if re.search(r"\b(end\s+quiz|stop\s+quiz|quit\s+quiz)\b", low):
        try:
            from flashcard_tool import end_quiz
            return end_quiz()
        except Exception as e:
            return f"Quiz error: {e}"

    if re.search(r"quiz\s+status", low):
        try:
            from flashcard_tool import quiz_status
            return quiz_status()
        except Exception as e:
            return ""

    # ── MEETING MODE ─────────────────────────────────────────────────────────
    if re.search(r"\b(i.?m\s+in\s+a\s+meeting|meeting\s+mode|start\s+(?:a\s+)?meeting)\b", low):
        m2 = re.search(r"(\d+)\s+minute", low)
        dur = int(m2.group(1)) if m2 else None
        try:
            from meeting_mode import start_meeting
            return start_meeting(dur)
        except Exception as e:
            return f"Meeting mode error: {e}"

    if re.search(r"\b(end\s+meeting|meeting\s+over|meeting\s+done|i.?m\s+out\s+of\s+the\s+meeting)\b", low):
        try:
            from meeting_mode import end_meeting
            return end_meeting()
        except Exception as e:
            return ""

    if re.search(r"(meeting\s+summary|summarise\s+(the\s+)?meeting|last\s+meeting)", low):
        try:
            from meeting_mode import get_last_meeting_summary
            return get_last_meeting_summary(llm_caller)
        except Exception as e:
            return f"Meeting summary unavailable: {e}"

    # ── FOCUS / STUDY REPORT ─────────────────────────────────────────────────
    if re.search(r"(how\s+long|how\s+much\s+time).+(spent|used|been).+(today|screen)", low) or \
       re.search(r"(focus|screen\s+time)\s+report", low):
        try:
            from focus_tool import get_focus_report
            return get_focus_report()
        except Exception as e:
            return f"Focus tracking unavailable: {e}"

    if re.search(r"(what\s+did\s+i\s+study|study\s+breakdown|how\s+much\s+did\s+i\s+study)", low):
        try:
            from focus_tool import get_study_breakdown
            return get_study_breakdown()
        except Exception as e:
            return f"Study tracker unavailable: {e}"

    if re.search(r"(what.?s?\s+my\s+top|which)\s+app.+(today|most)", low):
        try:
            from focus_tool import get_top_app
            return get_top_app()
        except Exception as e:
            return ""

    # ── WIKIPEDIA ────────────────────────────────────────────────────────────
    if re.search(r"\b(wikipedia|look\s+up|what\s+is\s+a\s+|who\s+is\s+|define\s+)\b", low):
        from wikipedia_tool import lookup, is_factual_question
        if is_factual_question(txt):
            q = re.sub(r"^(what is|who is|define|look up|wikipedia)\s+", "", low, flags=re.I).strip()
            return lookup(q)

    # ── NOTIFICATIONS ─────────────────────────────────────────────────────────
    if re.search(r"(send\s+(a\s+)?notification|notify\s+my\s+phone|ping\s+my\s+phone)", low):
        m2 = re.search(r"(?:notification|notify\s+my\s+phone|ping\s+my\s+phone)[\s:]+(.+)", low)
        msg = m2.group(1).strip() if m2 else "Notification from Jarvis"
        try:
            from notification_tool import send_notification
            return send_notification(msg)
        except Exception as e:
            return f"Notification failed: {e}"

    if re.search(r"ntfy\s+status", low):
        try:
            from notification_tool import ntfy_status
            return ntfy_status()
        except Exception as e:
            return ""

    # ── SPOTIFY ──────────────────────────────────────────────────────────────
    if re.search(r"\b(pause|play)\s+spotify\b|\bspotify\s+(pause|play)\b", low):
        try:
            from spotify_tool import play_pause
            return play_pause()
        except Exception as e:
            return f"Spotify unavailable: {e}"

    if re.search(r"\b(next\s+song|next\s+track|skip)\b", low):
        try:
            from spotify_tool import next_track
            return next_track()
        except Exception as e:
            return ""

    if re.search(r"\b(previous|prev|last)\s+(song|track)\b|\bgo\s+back\b", low):
        try:
            from spotify_tool import previous_track
            return previous_track()
        except Exception as e:
            return ""

    if re.search(r"(what.?s\s+playing|now\s+playing|current\s+song)", low):
        try:
            from spotify_tool import now_playing
            return now_playing()
        except Exception as e:
            return ""

    m2 = re.search(r"(?:play|search\s+spotify\s+for)\s+(.+?)(?:\s+on\s+spotify)?$", low)
    if m2 and "spotify" in low:
        try:
            from spotify_tool import search_and_play
            return search_and_play(m2.group(1).strip())
        except Exception as e:
            return f"Spotify unavailable: {e}"

    if re.search(r"spotify\s+(volume|louder|quieter)\s*(\d*)", low):
        m2 = re.search(r"(\d+)", low)
        level = int(m2.group(1)) if m2 else (80 if "louder" in low else 40)
        try:
            from spotify_tool import set_volume
            return set_volume(level)
        except Exception as e:
            return ""

    # ── HABITS REPORT ─────────────────────────────────────────────────────────
    if re.search(r"(weekly\s+habits?\s+report|habits?\s+(this\s+week|summary)|how\s+consistent)", low):
        return t.weekly_habits_report()

    # ── BUDGET ───────────────────────────────────────────────────────────────

    # "I spent €4.50 on coffee" / "I spent 4.50 on coffee"
    m = re.search(r"i\s+spent\s+([\d.,€]+(?:\s*euros?)?)\s+(?:on\s+)?(.+)", low)
    if m:
        try:
            from budget_tool import parse_amount, log_transaction
            amount = parse_amount(m.group(1))
            desc   = m.group(2).strip()
            if amount:
                result = log_transaction(amount, desc, llm_caller=llm_caller)
                # Stylist integration: offer to add clothes to closet
                from budget_tool import auto_detect_category
                detected_cat = auto_detect_category(desc, llm_caller)
                if detected_cat == "clothes":
                    result += " Want me to add this to your closet too? Say 'yes, add to closet'."
                return result
        except Exception as e:
            return f"Budget unavailable: {e}"

    # Stylist ↔ budget: "yes, add to closet" after a clothes purchase
    if re.search(r"yes[,\s]+add\s+(it\s+)?to\s+(my\s+)?closet", low):
        return (
            "Open the Stylist panel in the dashboard to add the item with its details and photo. "
            "Or say 'add [item name] to my closet'."
        )

    # "log 4.50 for food: coffee" — explicit category
    m = re.search(r"log\s+([\d.,€]+)\s+for\s+(\w+)[:\s]+(.+)", low)
    if m:
        try:
            from budget_tool import parse_amount, log_transaction
            amount = parse_amount(m.group(1))
            cat    = m.group(2).strip()
            desc   = m.group(3).strip()
            if amount:
                return log_transaction(amount, desc, category=cat)
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "how much have I spent this week/month/today"
    m = re.search(r"how\s+much\s+have\s+i\s+spent\s+(this\s+)?(week|month|today|year)", low)
    if m:
        try:
            from budget_tool import summary
            return summary(m.group(2))
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "how much have I spent on food this month"
    m = re.search(r"how\s+much\s+have\s+i\s+spent\s+on\s+(\w+)\s+(this\s+)?(week|month|today)?", low)
    if m:
        try:
            from budget_tool import category_summary
            return category_summary(m.group(1).strip(), m.group(3) or "month")
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "what's my budget looking like" / "budget overview"
    if re.search(r"(budget\s+(overview|looking|status)|what.?s\s+my\s+budget)", low):
        try:
            from budget_tool import overview
            return overview()
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "how much do I have left for clothes"
    m = re.search(r"how\s+much\s+(?:do\s+i\s+have\s+)?left\s+(?:for\s+)?(\w+)", low)
    if m:
        try:
            from budget_tool import remaining
            return remaining(m.group(1).strip())
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "can I afford [item] at [price]" / "can I afford a jacket at €89"
    m = re.search(r"can\s+i\s+afford\s+(.+?)\s+(?:at|for)\s+([\d.,€]+)", low)
    if m:
        try:
            from budget_tool import parse_amount, afford_check
            price = parse_amount(m.group(2))
            if price:
                return afford_check(m.group(1).strip(), price, llm_caller)
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "what did I spend today" / "today's spending"
    if re.search(r"(what\s+did\s+i\s+spend\s+(money\s+on\s+)?today|today.?s\s+spending)", low):
        try:
            from budget_tool import today_spending
            return today_spending()
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "show me my biggest expenses this month"
    if re.search(r"(biggest|largest|top)\s+expenses?", low):
        try:
            from budget_tool import top_expenses
            period = "week" if "week" in low else "month"
            return top_expenses(period)
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "set my food budget to 150"
    m = re.search(r"set\s+(?:my\s+)?(\w+)\s+budget\s+to\s+([\d.,€]+)", low)
    if m:
        try:
            from budget_tool import parse_amount, set_limit
            amount = parse_amount(m.group(2))
            if amount:
                return set_limit(m.group(1).strip(), amount)
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "set my monthly income to 800" / "I got paid 800"
    m = re.search(r"(?:set\s+(?:my\s+)?monthly\s+income\s+to|i\s+got\s+paid)\s+([\d.,€]+)", low)
    if m:
        try:
            from budget_tool import parse_amount, set_income
            amount = parse_amount(m.group(1))
            if amount:
                return set_income(amount)
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "add to savings: 50" / "save 50 euros"
    m = re.search(r"(?:add\s+to\s+savings[:\s]+|save\s+)([\d.,€]+)", low)
    if m:
        try:
            from budget_tool import parse_amount, log_savings
            amount = parse_amount(m.group(1))
            if amount:
                return log_savings(amount)
        except Exception as e:
            return f"Budget unavailable: {e}"

    # "how are my savings going"
    if re.search(r"(how\s+are\s+my\s+savings|savings\s+(status|progress|going))", low):
        try:
            from budget_tool import savings_status
            return savings_status()
        except Exception as e:
            return f"Budget unavailable: {e}"

    # ── STYLIST / WARDROBE ────────────────────────────────────────────────────
    if re.search(r"what\s+should\s+i\s+wear\s+today|suggest\s+(an?\s+)?outfit\s+for\s+today", low):
        try:
            from closet_tool import suggest_daily
            return suggest_daily(llm_caller)
        except Exception as e:
            return f"Stylist unavailable: {e}"

    m = re.search(r"what\s+goes\s+with\s+(my\s+)?(.+?)[\?.]?$", low)
    if m:
        try:
            from closet_tool import match_item
            return match_item(m.group(2).strip(), llm_caller)
        except Exception as e:
            return f"Stylist unavailable: {e}"

    m = re.search(r"what\s+should\s+i\s+wear\s+(?:to|for)\s+(?:a?\s*)(.+?)[\?.]?$", low)
    if m:
        try:
            from closet_tool import suggest_occasion
            return suggest_occasion(m.group(1).strip(), llm_caller)
        except Exception as e:
            return f"Stylist unavailable: {e}"

    if re.search(r"what\s+haven.?t\s+i\s+worn|unworn\s+(items?|clothes?)|rarely\s+worn", low):
        try:
            from closet_tool import unworn
            return unworn()
        except Exception as e:
            return f"Stylist unavailable: {e}"

    if re.search(r"(add|log)\s+.+\s+to\s+my\s+closet|add\s+.+\s+to\s+(my\s+)?wardrobe", low):
        m2 = re.search(r"add\s+(.+?)\s+to\s+(my\s+)?(closet|wardrobe)", low)
        if m2:
            item_name = m2.group(1).strip()
            return (
                f"I'll add {item_name} to your closet. "
                "Please open the Stylist panel in the dashboard to set the category, "
                "colors, and upload a photo."
            )

    if re.search(r"i\s+wore\s+(.+?)\s+today|wearing\s+(.+?)\s+today", low):
        m2 = re.search(r"i\s+wore\s+(.+?)(?:\s+today)?[\.\?]?$", low) or \
             re.search(r"wearing\s+(.+?)(?:\s+today)?[\.\?]?$", low)
        if m2:
            try:
                from closet_tool import log_worn
                return log_worn(m2.group(1).strip())
            except Exception as e:
                return f"Stylist unavailable: {e}"

    if re.search(r"(most\s+worn|wear\s+the\s+most|closet\s+stats?|wardrobe\s+stats?)", low):
        try:
            from closet_tool import get_stats
            return get_stats()
        except Exception as e:
            return f"Stylist unavailable: {e}"

    if re.search(r"(what\s+should\s+i\s+buy|closet\s+gaps?|missing\s+in\s+my\s+(closet|wardrobe))", low):
        try:
            from closet_tool import gaps
            gap_result = gaps(llm_caller)
            # Append clothes budget remaining as context
            try:
                from budget_tool import remaining as _remaining
                budget_note = _remaining("clothes")
                gap_result += f" {budget_note}"
            except Exception:
                pass
            return gap_result
        except Exception as e:
            return f"Stylist unavailable: {e}"

    # ── DOCUMENT RAG ─────────────────────────────────────────────────────────
    if re.search(r"\b(index\s+(my\s+)?notes|rebuild\s+knowledge|update\s+knowledge\s+base)\b", low):
        try:
            from rag_tool import index_all
            return index_all()
        except Exception as e:
            return f"RAG unavailable: {e}"

    if re.search(r"(index\s+(this\s+)?pdf|add\s+(this\s+)?pdf\s+to\s+knowledge)", low):
        try:
            import subprocess
            result = subprocess.run(["powershell","-Command","Get-Clipboard"],
                                    capture_output=True, text=True, timeout=3)
            pdf_path = result.stdout.strip().strip('"')
            from rag_tool import index_pdf
            return index_pdf(pdf_path)
        except Exception as e:
            return f"RAG unavailable: {e}"

    m = re.search(r"(what\s+do\s+my\s+(?:notes|documents?)\s+say\s+about|search\s+(?:my\s+)?(?:notes|documents?)\s+for|find\s+in\s+(?:my\s+)?(?:notes|documents?))\s+(.+)", low)
    if m:
        try:
            from rag_tool import ask
            return ask(m.group(2).strip(), llm_caller=llm_caller)
        except Exception as e:
            return f"RAG unavailable: {e}"

    if re.search(r"knowledge\s+base\s+stats?|how\s+many\s+(docs?|notes?)\s+indexed", low):
        try:
            from rag_tool import get_stats
            return get_stats()
        except Exception as e:
            return f"RAG unavailable: {e}"

    # ── MEETING TRANSCRIPTION ─────────────────────────────────────────────────
    if re.search(r"(start\s+)?transcrib(e|ing)\s+(the\s+)?meeting|record\s+(this\s+)?meeting", low):
        try:
            from meeting_transcriber import start_transcription
            return start_transcription()
        except Exception as e:
            return f"Meeting transcription unavailable: {e}"

    if re.search(r"(stop|end)\s+(transcrib(e|ing)|recording)\s+(the\s+)?meeting", low):
        try:
            from meeting_transcriber import stop_transcription
            return stop_transcription(llm_caller)
        except Exception as e:
            return f"Meeting transcription unavailable: {e}"

    if re.search(r"(show|what.?s|read)\s+(the\s+)?live\s+transcript", low):
        try:
            from meeting_transcriber import get_live_transcript
            return get_live_transcript()
        except Exception as e:
            return ""

    # ── WHATSAPP ─────────────────────────────────────────────────────────────
    # "Personal WhatsApp" / "uni WhatsApp" — account-specific
    if re.search(r"personal\s+whatsapp|whatsapp\s+personal", low):
        try:
            from whatsapp_tool import read_account
            return read_account("personal")
        except Exception as e:
            return f"WhatsApp unavailable: {e}"

    if re.search(r"uni\s+whatsapp|whatsapp\s+(uni|university|business)", low):
        try:
            from whatsapp_tool import read_account
            return read_account("uni")
        except Exception as e:
            return f"WhatsApp unavailable: {e}"

    # "WhatsApp from [name]" — search both accounts
    m2 = re.search(r"whatsapp\s+from\s+(.+)", low)
    if m2:
        try:
            from whatsapp_tool import read_all_unread
            return read_all_unread(filter_name=m2.group(1).strip())
        except Exception as e:
            return f"WhatsApp unavailable: {e}"

    # "Any WhatsApp messages?" — both accounts
    if re.search(r"(any\s+|read\s+|check\s+)?whatsapp(\s+messages?)?", low):
        try:
            from whatsapp_tool import read_all_unread
            return read_all_unread()
        except Exception as e:
            return f"WhatsApp unavailable: {e}"

    if re.search(r"whatsapp\s+status|is\s+whatsapp\s+connected", low):
        try:
            from whatsapp_tool import dual_status
            return dual_status()
        except Exception as e:
            return f"WhatsApp unavailable: {e}"

    # ── SCREEN READER ─────────────────────────────────────────────────────────
    if re.search(r"\b(read\s+(this|the\s+screen|what.?s\s+on\s+screen)|screen\s+reader|ocr)\b", low):
        try:
            from screen_reader import read_screen
            return read_screen(llm_caller=llm_caller)
        except Exception as e:
            return f"Screen reader error: {e}"

    # ── PLUGIN ROUTES (runs last before LLM fallback) ────────────────────────
    try:
        from plugin_loader import route_plugins
        plugin_result = route_plugins(txt, llm_caller=llm_caller)
        if plugin_result is not None:
            return plugin_result
    except Exception:
        pass

    # ── JOURNAL ──────────────────────────────────────────────────────────────
    m = re.search(r"(?:dear\s+jarvis[,\s]+|journal[:\s]+|log\s+this[:\s]+)(.+)", low, re.DOTALL)
    if m:
        try:
            from journal_tool import add_entry
            return add_entry(m.group(1).strip(), llm_caller=llm_caller)
        except Exception as e:
            return f"Journal unavailable: {e}"

    if re.search(r"read\s+(my\s+)?(today.?s\s+)?journal|what\s+did\s+i\s+journal\s+today", low):
        try:
            from journal_tool import read_today
            return read_today()
        except Exception as e:
            return f"Journal unavailable: {e}"

    if re.search(r"(read|summarise|summarize)\s+(my\s+)?journal\s+this\s+week|weekly\s+journal", low):
        try:
            from journal_tool import read_week
            return read_week(llm_caller=llm_caller)
        except Exception as e:
            return f"Journal unavailable: {e}"

    # ── WELLBEING FAST-PATH ──────────────────────────────────────────────────
    # Detect mood/energy/sleep statements before hitting the LLM.
    # Data is saved immediately; response still falls through to LLM for
    # a natural conversational reply.
    _wb = _detect_wellbeing_fast(low)
    if _wb:
        _save_wellbeing_fast(_wb)
        # Don't return — let LLM give a natural empathetic response

    # ── SHORTCUTS (user-defined macros) ──────────────────────────────────────
    if re.search(r"\blist\s+(my\s+)?shortcuts?\b", low):
        try:
            from shortcuts_engine import list_shortcuts
            return list_shortcuts()
        except Exception:
            pass

    try:
        from shortcuts_engine import match_shortcut, run_shortcut
        trigger = match_shortcut(txt)
        if trigger:
            return run_shortcut(trigger, llm_caller=llm_caller)
    except Exception:
        pass

    # ── No fast-path match ───────────────────────────────────────────────────
    return None


# ---------------------------------------------------------------------------
# Confirmed actions dispatcher
# ---------------------------------------------------------------------------

def _execute_confirmed(action: dict) -> str:
    name = action.get("action")
    if name == "sites_remove":
        return t.sites_remove(action["site"], action["category"])
    if name == "start_study_mode":
        return t.start_study_mode()
    if name == "forget_fact":
        return t.forget_fact(action["fragment"])
    if name == "grocery_clear":
        return t.grocery_clear()
    return "Unknown action."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_deadline(text: str) -> str | None:
    m = re.search(r"by\s+(\d{4}-\d{2}-\d{2}|\w+\s+\d{1,2})", text, re.IGNORECASE)
    if m:
        return _parse_date_str(m.group(1))
    return None


def _parse_date_str(raw: str) -> str | None:
    raw = raw.strip()
    # ISO format
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    # "June 8", "Jun 8"
    for fmt in ("%B %d", "%b %d"):
        try:
            d = datetime.strptime(raw, fmt)
            return d.replace(year=date.today().year).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return raw
