"""
scheduler.py -- Scheduled events for Jarvis.
4 independent daemon threads to prevent timing conflicts:
  Thread 1: Deadline checker (every 30 min)
  Thread 2: Calendar checker (every 15 min)
  Thread 3: Alarm/proactive checker (every 60 sec)
  Thread 4: Daily/weekly events (morning, evening, weekly, etc.)
"""

import logging
import threading
import time
from datetime import date, datetime, timedelta

import schedule as _schedule   # alias to avoid conflicts between thread instances
import yaml

import tools

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_speak_fn     = None
_stop_event   = threading.Event()
_paused_event = threading.Event()

# Notification de-duplication sets — reset daily
_deadline_notified: set[str] = set()
_calendar_notified: set[str] = set()

# Proactive throttling: {condition_id: last_fired_datetime}
_proactive_last_fired: dict[str, datetime] = {}


def _load_cfg() -> dict:
    from pathlib import Path
    with open(Path(__file__).parent / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def set_speak(fn) -> None:
    global _speak_fn
    _speak_fn = fn


def set_paused(paused: bool) -> None:
    if paused:
        _paused_event.set()
        logger.info("Scheduler paused (sleep mode).")
    else:
        _paused_event.clear()
        logger.info("Scheduler resumed.")


def _say(text: str) -> None:
    logger.info("Scheduled say: %s", text[:80])
    if _speak_fn:
        _speak_fn(text)


def _is_suppressed() -> bool:
    try:
        import jarvis as _j
        if _j.is_sleeping():
            return True
    except Exception:
        pass
    try:
        from meeting_mode import is_in_meeting
        if is_in_meeting():
            return True
    except Exception:
        pass
    return False


# ---------------------------------------------------------------------------
# Thread 1 -- Deadline checker (tasks only, NOT calendar)
# ---------------------------------------------------------------------------

def _check_deadlines() -> None:
    """Check task deadlines at 24h, 2h, and 30min thresholds."""
    if _is_suppressed():
        return
    try:
        cfg   = _load_cfg()
        tasks = tools._read_json(tools._p("tasks"))
        now   = datetime.now()

        for task in tasks:
            if task.get("done"):
                continue
            dl_str = task.get("deadline")
            if not dl_str:
                continue
            try:
                deadline = datetime.fromisoformat(dl_str)
                delta    = deadline - now
                hours    = delta.total_seconds() / 3600
                tid      = task["id"]

                if 23.5 <= hours <= 24.5:
                    key = f"{tid}_24h"
                    if key not in _deadline_notified:
                        _say(f"Reminder: '{task['title']}' is due in 24 hours.")
                        _deadline_notified.add(key)

                elif 1.75 <= hours <= 2.25:
                    key = f"{tid}_2h"
                    if key not in _deadline_notified:
                        _say(f"Heads up: '{task['title']}' is due in 2 hours.")
                        try:
                            from notification_tool import send_notification
                            send_notification("Deadline Soon", f"{task['title']} due in 2h",
                                              priority="high", tags=["alarm_clock"])
                        except Exception:
                            pass
                        _deadline_notified.add(key)

                elif 0.4 <= hours <= 0.6:
                    key = f"{tid}_30m"
                    if key not in _deadline_notified:
                        _say(f"Final warning: '{task['title']}' is due in 30 minutes!")
                        try:
                            from notification_tool import send_notification
                            send_notification("Due in 30 Min", task["title"],
                                              priority="urgent", tags=["rotating_light"])
                        except Exception:
                            pass
                        _deadline_notified.add(key)

            except Exception:
                pass

        # Also check goal deadlines (30-day warning)
        try:
            g_data = tools._read_json(tools._p("goals"))
            for g in g_data.get("long_term", []) + g_data.get("short_term", []):
                if not g.get("deadline"):
                    continue
                try:
                    dl = datetime.strptime(g["deadline"], "%Y-%m")
                    days_left = (dl - now).days
                    key = f"goal_{g['goal']}_30d"
                    if days_left <= 30 and key not in _deadline_notified:
                        _deadline_notified.add(key)
                        _say(
                            f"Goal reminder: '{g['goal']}' deadline is in "
                            f"{days_left} days at {g.get('progress', 0)}% progress."
                        )
                except Exception:
                    pass
        except Exception:
            pass

    except Exception as e:
        logger.error("Deadline check error: %s", e)


def _deadline_thread() -> None:
    sched = _schedule.Scheduler()
    sched.every(30).minutes.do(_check_deadlines)
    logger.info("Deadline thread started.")
    while not _stop_event.is_set():
        sched.run_pending()
        time.sleep(60)


# ---------------------------------------------------------------------------
# Thread 2 -- Calendar checker (every 15 min, separate from deadlines)
# ---------------------------------------------------------------------------

def _check_calendar_events() -> None:
    """Check for calendar events starting in ~15 minutes."""
    try:
        cfg = _load_cfg()
        if not cfg.get("google_calendar", {}).get("email"):
            return
        from calendar_tool import get_upcoming_events_raw
        events = get_upcoming_events_raw(minutes_ahead=17)
        for ev in events:
            ev_id = ev.get("id", ev.get("summary", ""))
            if ev_id in _calendar_notified:
                continue
            _calendar_notified.add(ev_id)
            start = ev.get("start_str", "soon")
            title = ev.get("summary", "Event")
            msg   = f"Heads up -- {title} starts in about 15 minutes. {start}."
            if not _is_suppressed():
                _say(msg)
            try:
                from notification_tool import send_notification
                send_notification(f"Calendar: {title}", msg, priority="high",
                                  tags=["calendar"])
            except Exception:
                pass
    except Exception as e:
        logger.debug("Calendar check error: %s", e)


def _calendar_thread() -> None:
    sched = _schedule.Scheduler()
    sched.every(15).minutes.do(_check_calendar_events)
    # Reset notification set at midnight
    sched.every().day.at("00:01").do(_calendar_notified.clear)
    logger.info("Calendar thread started.")
    while not _stop_event.is_set():
        sched.run_pending()
        time.sleep(30)


# ---------------------------------------------------------------------------
# Thread 3 -- Alarm + proactive checker (every 60 sec)
# ---------------------------------------------------------------------------

def _check_alarms() -> None:
    """Fire due reminders/alarms."""
    try:
        rem_path = tools._p("reminders")
        reminders = tools._read_json(rem_path)
        now = datetime.now()
        for reminder in reminders:
            if reminder.get("done"):
                continue
            try:
                trigger = datetime.fromisoformat(reminder["trigger_at"])
            except Exception:
                continue
            if trigger <= now:
                tools.fire_reminder(reminder, speak_fn=_speak_fn)
    except Exception as e:
        logger.error("Alarm check error: %s", e)


def _check_proactive() -> None:
    """Proactive suggestions with per-condition throttling."""
    if _is_suppressed():
        return

    # Check if Jarvis has spoken recently (silence window)
    try:
        from proactive_engine import run_proactive_check
        run_proactive_check()
    except Exception as e:
        logger.debug("Proactive check error: %s", e)


def _alarm_thread() -> None:
    logger.info("Alarm/proactive thread started.")
    while not _stop_event.is_set():
        _check_alarms()
        _check_proactive()
        _stop_event.wait(timeout=60)


# ---------------------------------------------------------------------------
# Thread 4 -- Daily/weekly scheduled events
# ---------------------------------------------------------------------------

def _morning_briefing_job() -> None:
    if _is_suppressed():
        logger.info("Morning briefing suppressed.")
        return
    logger.info("Morning briefing triggered.")
    briefing = tools.morning_briefing()
    try:
        from whatsapp_tool import check_whatsapp_for_briefing
        wa = check_whatsapp_for_briefing()
        if wa:
            briefing += " " + wa
    except Exception:
        pass
    _say(briefing)


def _evening_checkin_job() -> None:
    if _is_suppressed():
        return
    logger.info("Evening check-in triggered.")
    _say(tools.evening_checkin())


def _weekly_review_job() -> None:
    if _is_suppressed():
        return
    logger.info("Weekly review triggered.")
    _say(tools.weekly_review())
    try:
        from budget_tool import summary as _budget_summary
        msg = _budget_summary("week")
        if msg:
            _say(msg)
    except Exception:
        pass


def _auto_backup_job() -> None:
    try:
        result = tools.backup_everything(silent=True)
        logger.info("Auto-backup: %s", result)
    except Exception as e:
        logger.error("Auto-backup failed: %s", e)


def _auto_sleep_job() -> None:
    try:
        import jarvis as _j
        if not _j.is_sleeping():
            _j.go_to_sleep()
            _say("Going to sleep. Good night.")
    except Exception:
        pass


def _auto_wake_job() -> None:
    try:
        import jarvis as _j
        if _j.is_sleeping():
            response = _j.wake_from_sleep(good_morning=True)
            _say(response)
    except Exception:
        pass


def _deadline_notified_reset() -> None:
    _deadline_notified.clear()
    logger.debug("Deadline notification set reset.")


def _daily_thread() -> None:
    cfg  = _load_cfg()
    br   = cfg.get("briefing", {})
    bak  = cfg.get("backup", {})
    slp  = cfg.get("sleep", {})
    sched = _schedule.Scheduler()

    morning_t  = br.get("morning_time",       "08:00")
    evening_t  = br.get("evening_time",       "20:00")
    weekly_day = br.get("weekly_review_day",  "saturday").lower()
    weekly_t   = br.get("weekly_review_time", "10:00")
    sleep_t    = slp.get("auto_sleep_time")
    wake_t     = slp.get("auto_wake_time")
    bak_day    = bak.get("auto_day",  "sunday").lower()
    bak_t      = bak.get("auto_time", "00:00")

    sched.every().day.at(morning_t).do(_morning_briefing_job)
    sched.every().day.at(evening_t).do(_evening_checkin_job)
    getattr(sched.every(), weekly_day).at(weekly_t).do(_weekly_review_job)
    getattr(sched.every(), bak_day).at(bak_t).do(_auto_backup_job)
    sched.every().day.at("00:01").do(_deadline_notified_reset)

    if sleep_t:
        sched.every().day.at(sleep_t).do(_auto_sleep_job)
    if wake_t:
        sched.every().day.at(wake_t).do(_auto_wake_job)

    logger.info(
        "Daily thread started: morning %s, evening %s, "
        "weekly %s %s, backup %s %s.",
        morning_t, evening_t, weekly_day, weekly_t, bak_day, bak_t,
    )

    # Run deadline check immediately on startup
    _check_deadlines()
    _check_alarms()

    while not _stop_event.is_set():
        if not _paused_event.is_set():
            sched.run_pending()
        else:
            _check_alarms()   # alarms fire even in sleep/meeting
        time.sleep(30)

    logger.info("Daily thread stopped.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def start_scheduler_thread(stop_event: threading.Event | None = None) -> list[threading.Thread]:
    """Start all 4 scheduler threads. Returns the thread list."""
    global _stop_event
    if stop_event:
        _stop_event = stop_event

    threads = [
        threading.Thread(target=_deadline_thread, daemon=True, name="SchedDeadlines"),
        threading.Thread(target=_calendar_thread, daemon=True, name="SchedCalendar"),
        threading.Thread(target=_alarm_thread,    daemon=True, name="SchedAlarms"),
        threading.Thread(target=_daily_thread,    daemon=True, name="SchedDaily"),
    ]
    for t in threads:
        t.start()
    logger.info("4 scheduler threads started.")
    return threads


# ---------------------------------------------------------------------------
# Legacy aliases (used by existing code)
# ---------------------------------------------------------------------------

def run_scheduler(stop_event=None):
    """Legacy entry point — starts all 4 threads and blocks."""
    threads = start_scheduler_thread(stop_event)
    for t in threads:
        t.join()


# ---------------------------------------------------------------------------
# Pomodoro (unchanged from original)
# ---------------------------------------------------------------------------

_pomodoro_active = False
_pomodoro_thread: threading.Thread | None = None


def start_pomodoro(work_minutes: int = 25, break_minutes: int = 5) -> None:
    global _pomodoro_active, _pomodoro_thread
    def _run():
        global _pomodoro_active
        _pomodoro_active = True
        logger.info("Pomodoro started: %d min focus.", work_minutes)
        time.sleep(work_minutes * 60)
        if _pomodoro_active:
            _say(f"Focus block complete! Take a {break_minutes}-minute break.")
            time.sleep(break_minutes * 60)
            if _pomodoro_active:
                _say("Break over. Ready for the next focus block.")
        _pomodoro_active = False

    if _pomodoro_active and _pomodoro_thread and _pomodoro_thread.is_alive():
        return
    _pomodoro_thread = threading.Thread(target=_run, daemon=True)
    _pomodoro_thread.start()


def stop_pomodoro() -> None:
    global _pomodoro_active
    _pomodoro_active = False
