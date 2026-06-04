"""
calendar_tool.py — Google Calendar via CalDAV (free, no Cloud Console needed).

Setup (one time, ~2 minutes):
  1. Enable 2-Step Verification on your Google account if not already on.
  2. Go to: myaccount.google.com/apppasswords
  3. Create an App Password → App name: "Jarvis" → copy the 16-char password
  4. Fill in config.yaml:
       google_calendar:
         email:        "yourname@gmail.com"
         app_password: "xxxx xxxx xxxx xxxx"

No billing, no Cloud Console, no API key.
"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_credentials() -> tuple[str, str]:
    cfg = _load_cfg()
    cal_cfg = cfg.get("google_calendar", {})
    email    = cal_cfg.get("email", "").strip()
    password = cal_cfg.get("app_password", "").replace(" ", "").strip()
    if not email or not password:
        raise RuntimeError(
            "Google Calendar not configured. Add your email and app password to "
            "config.yaml under google_calendar.email and google_calendar.app_password. "
            "Generate an app password at myaccount.google.com/apppasswords."
        )
    return email, password


def _get_calendar():
    """Connect to Google Calendar via CalDAV."""
    try:
        import caldav  # type: ignore
    except ImportError:
        raise RuntimeError("caldav not installed. Run: pip install caldav icalendar")

    email, password = _get_credentials()
    url = f"https://calendar.google.com/calendar/dav/{email}/events"
    client = caldav.DAVClient(url=url, username=email, password=password)
    principal = client.principal()
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("No calendars found. Check your email and app password.")
    return calendars[0]


def _fmt_event(event) -> str:
    """Format a caldav/icalendar event for speech."""
    try:
        comp = event.icalendar_component
        title    = str(comp.get("SUMMARY", "Untitled event"))
        start    = comp.get("DTSTART")
        location = str(comp.get("LOCATION", ""))

        if start:
            dt = start.dt
            if hasattr(dt, "hour"):
                time_str = dt.strftime("%I:%M %p").lstrip("0")
                date_str = dt.strftime("%A %d %B")
            else:
                time_str = "all day"
                date_str = dt.strftime("%A %d %B")
        else:
            time_str = "unknown time"
            date_str = ""

        loc_str = f" at {location}" if location else ""
        return f"{title} — {date_str} at {time_str}{loc_str}"
    except Exception as e:
        return str(event)


def _fetch_events(start: datetime, end: datetime) -> list:
    cal = _get_calendar()
    return cal.date_search(start=start, end=end, expand=True)


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def get_today_events() -> str:
    try:
        now   = datetime.now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end   = start + timedelta(days=1)
        events = _fetch_events(start, end)
        if not events:
            return "Your calendar is clear today, Samaira."
        lines = ["Here are today's events:"]
        for ev in events:
            lines.append(f"• {_fmt_event(ev)}")
        return "\n".join(lines)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.error("get_today_events: %s", e)
        return f"Couldn't read calendar: {e}"


def get_tomorrow_events() -> str:
    try:
        tomorrow = datetime.now() + timedelta(days=1)
        start    = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
        end      = start + timedelta(days=1)
        events   = _fetch_events(start, end)
        if not events:
            return "Nothing on your calendar tomorrow."
        lines = ["Tomorrow's events:"]
        for ev in events:
            lines.append(f"• {_fmt_event(ev)}")
        return "\n".join(lines)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't read calendar: {e}"


def get_week_events() -> str:
    try:
        now    = datetime.now()
        end    = now + timedelta(days=7)
        events = _fetch_events(now, end)
        if not events:
            return "Nothing on your calendar this week."
        lines = [f"Your next {len(events)} events this week:"]
        for ev in events[:10]:
            lines.append(f"• {_fmt_event(ev)}")
        return "\n".join(lines)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't read calendar: {e}"


def get_upcoming_events(days: int = 3) -> str:
    try:
        now    = datetime.now()
        end    = now + timedelta(days=days)
        events = _fetch_events(now, end)
        if not events:
            return f"Nothing coming up in the next {days} days."
        lines = ["Upcoming events:"]
        for ev in events[:5]:
            lines.append(f"• {_fmt_event(ev)}")
        return "\n".join(lines)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't read calendar: {e}"


def get_upcoming_events_raw(minutes_ahead: int = 15) -> list[dict]:
    """Return raw event dicts for events starting within minutes_ahead. Used by scheduler."""
    try:
        now    = datetime.now()
        end    = now + timedelta(minutes=minutes_ahead)
        events = _fetch_events(now, end)
        result = []
        for ev in events:
            try:
                comp  = ev.icalendar_component
                title = str(comp.get("SUMMARY", "Untitled"))
                start = comp.get("DTSTART")
                start_str = start.dt.strftime("%I:%M %p").lstrip("0") if start and hasattr(start.dt, "hour") else "soon"
                result.append({"summary": title, "start_str": start_str, "id": str(comp.get("UID", title))})
            except Exception:
                pass
        return result
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def add_calendar_event(title: str, start_str: str, duration_hours: float = 1.0,
                       description: str = "") -> str:
    """Add an event to Google Calendar via CalDAV."""
    try:
        from dateutil import parser as dp  # type: ignore
        start_dt = dp.parse(start_str, fuzzy=True)
    except Exception:
        try:
            start_dt = datetime.fromisoformat(start_str)
        except Exception:
            return f"Couldn't understand the date '{start_str}'. Try '10 June at 2pm'."

    end_dt = start_dt + timedelta(hours=duration_hours)

    try:
        from icalendar import Calendar, Event  # type: ignore
        import uuid

        cal = Calendar()
        cal.add("prodid", "-//Jarvis//EN")
        cal.add("version", "2.0")

        ev = Event()
        ev.add("summary", title)
        ev.add("dtstart", start_dt)
        ev.add("dtend", end_dt)
        ev.add("description", description)
        ev.add("uid", str(uuid.uuid4()))
        cal.add_component(ev)

        calendar = _get_calendar()
        calendar.save_event(cal.to_ical().decode())
        date_str = start_dt.strftime("%A %d %B at %I:%M %p").lstrip("0")
        return f"Added '{title}' to your calendar on {date_str}."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.error("add_calendar_event: %s", e)
        return f"Couldn't add event: {e}"


def calendar_status() -> str:
    """Check if Google Calendar is connected."""
    cfg = _load_cfg()
    cal_cfg = cfg.get("google_calendar", {})
    if not cal_cfg.get("email") or not cal_cfg.get("app_password"):
        return (
            "Google Calendar is not set up. "
            "Add your Gmail address and an App Password to config.yaml "
            "under google_calendar.email and google_calendar.app_password. "
            "Generate the App Password at myaccount.google.com/apppasswords."
        )
    try:
        _get_calendar()
        return "Google Calendar is connected."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Calendar connection failed: {e}"
