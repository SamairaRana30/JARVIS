"""
closet_tool.py — Wardrobe manager and AI stylist for Jarvis.

Manages clothing items, suggests outfits based on weather/schedule/occasion,
tracks wear history, and identifies closet gaps.

Data files:
  data/closet.json      — all clothing items
  data/outfits.json     — saved outfit combinations
  data/color_rules.json — color matching rules
"""

import json
import logging
import re
import shutil
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()

CATEGORIES = ("tops", "bottoms", "shoes", "outerwear", "accessories", "dresses")

SEASON_MAP = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring",  4: "spring", 5: "spring",
    6: "summer",  7: "summer", 8: "summer",
    9: "autumn",  10: "autumn", 11: "autumn",
}

OCCASION_FROM_SCHEDULE = {
    "lecture":  "smart casual",
    "seminar":  "smart casual",
    "lab":      "casual",
    "study":    "casual",
    "meeting":  "smart",
    "evening":  "smart casual",
    "gym":      "sport",
    "errands":  "casual",
}


# ---------------------------------------------------------------------------
# Config + JSON helpers
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _closet_path() -> Path:
    return BASE_DIR / "data" / "closet.json"


def _outfits_path() -> Path:
    return BASE_DIR / "data" / "outfits.json"


def _color_rules_path() -> Path:
    return BASE_DIR / "data" / "color_rules.json"


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, data: Any) -> None:
    bak = path.with_suffix(".bak")
    if path.exists():
        shutil.copy(path, bak)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _next_item_id(items: list) -> str:
    existing = [int(i["id"].split("_")[1]) for i in items if i.get("id", "").startswith("item_")]
    return f"item_{(max(existing, default=0) + 1):03d}"


def _next_outfit_id(outfits: list) -> str:
    existing = [int(o["id"].split("_")[1]) for o in outfits if o.get("id", "").startswith("outfit_")]
    return f"outfit_{(max(existing, default=0) + 1):03d}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _active_items() -> list[dict]:
    return [i for i in _read(_closet_path()).get("items", []) if i.get("active", True)]


def _find_item(query: str) -> dict | None:
    items = _active_items()
    q = query.lower()
    # Exact id match
    for i in items:
        if i["id"] == q:
            return i
    # Name match
    for i in items:
        if q in i.get("name", "").lower():
            return i
    # Color + category match
    for i in items:
        if any(q in c for c in i.get("colors", [])):
            return i
    return None


def _current_season() -> str:
    return SEASON_MAP.get(datetime.now().month, "spring")


def _get_weather_summary() -> tuple[str, float]:
    """Return (description, temp_c) from wttr.in or cache."""
    try:
        cfg = _cfg()
        city = cfg.get("weather", {}).get("default_location", "Berlin")
        import requests
        resp = requests.get(
            f"https://wttr.in/{city}?format=j1",
            timeout=5, headers={"User-Agent": "Jarvis/1.0"}
        )
        data = resp.json()
        current = data.get("current_condition", [{}])[0]
        temp = int(current.get("temp_C", 18))
        desc = current.get("weatherDesc", [{}])[0].get("value", "mild").lower()
        # Simplify
        if temp < 10:
            weather_cat = "cold"
        elif temp < 18:
            weather_cat = "mild"
        elif temp < 25:
            weather_cat = "warm"
        else:
            weather_cat = "hot"
        return weather_cat, temp
    except Exception:
        return "mild", 18


def _color_matches(color: str, target_colors: list[str]) -> bool:
    """Check if color goes with any of target_colors using color_rules.json."""
    try:
        rules = _read(_color_rules_path())
        allowed = rules.get(color.lower(), [])
        if "everything" in allowed:
            return True
        for tc in target_colors:
            tc_l = tc.lower()
            if tc_l in allowed or "everything" in rules.get(tc_l, []):
                return True
    except Exception:
        pass
    return False


def _days_since_worn(item: dict) -> int:
    last = item.get("last_worn")
    if not last:
        return 9999
    try:
        return (date.today() - date.fromisoformat(last)).days
    except Exception:
        return 9999


def _get_today_occasion() -> str:
    """Infer occasion from today's schedule."""
    try:
        sched_path = BASE_DIR / "data" / "schedule.json"
        sched = _read(sched_path)
        today_str = datetime.now().strftime("%A").lower()
        for cls in sched.get("classes", []):
            if today_str in [d.lower() for d in cls.get("days", [])]:
                cls_type = cls.get("type", "").lower()
                return OCCASION_FROM_SCHEDULE.get(cls_type, "smart casual")
    except Exception:
        pass
    return "casual"


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def suggest_daily(llm_caller=None) -> str:
    """Suggest a full outfit for today based on weather, schedule, and season."""
    weather_cat, temp_c = _get_weather_summary()
    season    = _current_season()
    occasion  = _get_today_occasion()
    cfg_s     = _cfg().get("stylist", {})
    avoid_days = int(cfg_s.get("avoid_rewear_days", 3))

    items = _active_items()

    # Filter by season
    seasonal = [i for i in items if season in i.get("season", []) or not i.get("season")]

    # Filter by weather (rough)
    if weather_cat in ("cold", "mild"):
        seasonal = [i for i in seasonal if i.get("category") != "dresses"
                    or "winter" in i.get("season", [])]

    # Filter out recently worn
    fresh = [i for i in seasonal if _days_since_worn(i) >= avoid_days]
    if not fresh:
        fresh = seasonal   # fallback if all recently worn

    # Group by category
    groups: dict[str, list] = {}
    for item in fresh:
        cat = item.get("category", "other")
        groups.setdefault(cat, []).append(item)

    # Build candidate list for LLM
    candidates = []
    for cat in ("tops", "bottoms", "dresses", "shoes", "outerwear", "accessories"):
        cat_items = groups.get(cat, [])
        # Sort by occasion match then by least recently worn
        cat_items.sort(key=lambda i: (
            0 if occasion in i.get("occasion", []) else 1,
            _days_since_worn(i) * -1,   # most overdue first
        ))
        candidates.extend(cat_items[:4])

    if not candidates:
        return "Your closet seems empty. Add some items first."

    candidate_text = "\n".join(
        f"- [{i['id']}] {i['name']} ({i['category']}, "
        f"colors: {', '.join(i.get('colors', []))}, "
        f"occasion: {', '.join(i.get('occasion', []))})"
        for i in candidates
    )

    # Get today's schedule summary
    schedule_note = ""
    try:
        sched = _read(BASE_DIR / "data" / "schedule.json")
        today_str = datetime.now().strftime("%A").lower()
        today_classes = [c for c in sched.get("classes", [])
                         if today_str in [d.lower() for d in c.get("days", [])]]
        if today_classes:
            schedule_note = f"Schedule today: {', '.join(c['name'] for c in today_classes)}. "
    except Exception:
        pass

    prompt = (
        f"Suggest a complete, stylish outfit for today. "
        f"Weather: {weather_cat} ({temp_c}°C). Season: {season}. "
        f"Occasion: {occasion}. {schedule_note}"
        f"Choose one top, one bottom or dress, shoes, and optionally outerwear/accessory. "
        f"Prioritise items that complement each other in color and style. "
        f"Available items:\n{candidate_text}\n\n"
        f"Respond naturally in 1-2 sentences explaining the outfit choice, "
        f"mentioning the item names. Example: "
        f"'For today's lecture in mild weather, your white tee with dark jeans and white sneakers would be perfect.'"
    )

    if llm_caller:
        return llm_caller(prompt)

    # Fallback without LLM
    tops   = groups.get("tops", [])
    bots   = groups.get("bottoms", []) or groups.get("dresses", [])
    shoes  = groups.get("shoes", [])
    suggestion = []
    if tops:   suggestion.append(tops[0]["name"])
    if bots:   suggestion.append(bots[0]["name"])
    if shoes:  suggestion.append(shoes[0]["name"])
    return f"Try: {', '.join(suggestion)}." if suggestion else "Add more items to your closet for suggestions."


def suggest_occasion(occasion: str, llm_caller=None) -> str:
    """Suggest an outfit for a specific occasion."""
    items = _active_items()
    occ_l = occasion.lower()
    matched = [i for i in items if any(occ_l in o.lower() for o in i.get("occasion", []))]
    if not matched:
        matched = items   # fallback to everything

    groups: dict[str, list] = {}
    for item in matched:
        groups.setdefault(item.get("category", "other"), []).append(item)

    candidates = []
    for cat in ("tops", "bottoms", "dresses", "shoes", "outerwear"):
        candidates.extend(groups.get(cat, [])[:3])

    if not candidates:
        return f"No items tagged for {occasion} occasions. Update your closet tags."

    candidate_text = "\n".join(
        f"- {i['name']} ({i['category']}, colors: {', '.join(i.get('colors', []))})"
        for i in candidates
    )

    if llm_caller:
        return llm_caller(
            f"Suggest a complete outfit for a {occasion} occasion from these items:\n"
            f"{candidate_text}\nRespond in 1-2 natural sentences."
        )
    return f"For {occasion}: {', '.join(i['name'] for i in candidates[:3])}."


def match_item(item_name: str, llm_caller=None) -> str:
    """Find items that go well with a specific piece."""
    target = _find_item(item_name)
    if not target:
        return f"I couldn't find '{item_name}' in your closet."

    target_colors = target.get("colors", [])
    target_cat    = target.get("category", "")
    items = _active_items()

    # Find complementary items (different category, matching colors)
    matches = []
    for item in items:
        if item["id"] == target["id"]:
            continue
        if item.get("category") == target_cat:
            continue   # same category rarely goes "with" itself
        item_colors = item.get("colors", [])
        if any(_color_matches(c, target_colors) for c in item_colors):
            matches.append(item)

    if not matches:
        return f"I couldn't find good matches for {target['name']} in your closet yet."

    matches.sort(key=lambda i: _days_since_worn(i), reverse=True)

    if llm_caller:
        candidate_text = "\n".join(f"- {i['name']} ({i['category']})" for i in matches[:8])
        return llm_caller(
            f"The user has a {target['name']} ({', '.join(target_colors)}). "
            f"Suggest the best 2-3 outfit combinations from these matching items:\n"
            f"{candidate_text}\nKeep it brief and natural."
        )

    tops = [i for i in matches if i.get("category") == "tops"][:2]
    bots = [i for i in matches if i.get("category") == "bottoms"][:2]
    result_items = (tops + bots)[:4]
    return (
        f"{target['name']} goes well with: "
        + ", ".join(i["name"] for i in result_items)
        + "."
    )


def unworn(days: int = 30) -> str:
    """List items not worn in the last `days` days."""
    items = _active_items()
    neglected = [i for i in items if _days_since_worn(i) >= days]
    neglected.sort(key=_days_since_worn, reverse=True)

    if not neglected:
        return f"Great news — everything in your closet has been worn in the last {days} days!"

    lines = [f"Items you haven't worn in {days}+ days:"]
    for item in neglected[:8]:
        days_ago = _days_since_worn(item)
        worn_str = "never worn" if days_ago == 9999 else f"last worn {days_ago} days ago"
        lines.append(f"• {item['name']} ({item.get('category', '?')}) — {worn_str}")
    return "\n".join(lines)


def gaps(llm_caller=None) -> str:
    """Analyse closet for missing wardrobe essentials."""
    items = _active_items()
    counts: dict[str, int] = {}
    for item in items:
        cat = item.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1

    summary = ", ".join(f"{cat}: {n}" for cat, n in counts.items())
    total   = len(items)

    if llm_caller:
        return llm_caller(
            f"Analyse this wardrobe for gaps and suggest what to add. "
            f"Total items: {total}. Breakdown: {summary}. "
            f"Identify 2-3 missing essentials. Be specific and practical. Keep it brief."
        )
    return f"Your closet has {total} items: {summary}. Consider if you need more variety in under-represented categories."


def log_worn(item_name: str) -> str:
    """Update last_worn and times_worn for an item."""
    data  = _read(_closet_path())
    items = data.get("items", [])
    today = date.today().isoformat()

    for item in items:
        if item_name.lower() in item.get("name", "").lower() or item.get("id") == item_name:
            item["last_worn"]  = today
            item["times_worn"] = int(item.get("times_worn", 0)) + 1
            _write(_closet_path(), data)
            return f"Logged: wore {item['name']} today ({item['times_worn']} times total)."

    return f"Couldn't find '{item_name}' in your closet."


def add_item(name: str, category: str, colors: list[str],
             occasion: list[str] | None = None, season: list[str] | None = None,
             brand: str = "", size: str = "", cost: float | None = None) -> str:
    """Add a new item to the closet."""
    data  = _read(_closet_path())
    items = data.setdefault("items", [])
    new_id = _next_item_id(items)

    cat_l = category.lower()
    if cat_l not in CATEGORIES:
        cat_l = "tops"   # default

    item = {
        "id":         new_id,
        "name":       name,
        "category":   cat_l,
        "subcategory":"",
        "colors":     [c.lower() for c in colors],
        "brand":      brand,
        "size":       size,
        "material":   "",
        "style_tags": [],
        "occasion":   occasion or ["casual"],
        "season":     season or ["spring", "summer", "autumn", "winter"],
        "photo":      None,
        "date_added": date.today().isoformat(),
        "last_worn":  None,
        "times_worn": 0,
        "cost":       cost,
        "currency":   "EUR",
        "notes":      "",
        "favorite":   False,
        "active":     True,
    }
    items.append(item)
    _write(_closet_path(), data)
    return (
        f"Added {name} to your closet as {new_id}. "
        "Open the dashboard to add a photo."
    )


def get_stats() -> str:
    """Return closet statistics as a spoken string."""
    items = _active_items()
    if not items:
        return "Your closet is empty. Start adding items."

    total     = len(items)
    total_val = sum(float(i.get("cost", 0) or 0) for i in items)
    currency  = items[0].get("currency", "EUR") if items else "EUR"

    # Most worn
    by_worn = sorted(items, key=lambda i: i.get("times_worn", 0), reverse=True)

    # Never worn
    never   = [i for i in items if not i.get("times_worn")]
    old     = [i for i in items if _days_since_worn(i) > 90]

    # Category counts
    counts: dict[str, int] = {}
    for item in items:
        cat = item.get("category", "other")
        counts[cat] = counts.get(cat, 0) + 1

    lines = [f"Your closet has {total} items worth approximately {currency} {total_val:.0f}."]

    if by_worn:
        top3 = by_worn[:3]
        lines.append(
            "Most worn: " +
            ", ".join(f"{i['name']} ({i.get('times_worn', 0)}x)" for i in top3) + "."
        )

    if never:
        lines.append(f"{len(never)} item{'s' if len(never) != 1 else ''} never worn.")
    if old:
        lines.append(f"{len(old)} item{'s' if len(old) != 1 else ''} not worn in 90+ days.")

    cat_str = ", ".join(f"{k}: {v}" for k, v in counts.items())
    lines.append(f"Breakdown — {cat_str}.")

    return " ".join(lines)


def save_outfit(name: str, item_ids: list[str], occasion: str = "casual") -> str:
    """Save a named outfit combination."""
    data    = _read(_outfits_path())
    outfits = data.setdefault("outfits", [])
    new_id  = _next_outfit_id(outfits)
    outfits.append({
        "id":        new_id,
        "name":      name,
        "occasion":  occasion,
        "items":     item_ids,
        "weather":   [],
        "times_worn": 0,
        "last_worn": None,
        "rating":    5,
        "photo":     None,
        "created":   date.today().isoformat(),
    })
    _write(_outfits_path(), data)
    return f"Saved outfit '{name}'."


def get_all_items() -> list[dict]:
    return _active_items()


def get_item_by_id(item_id: str) -> dict | None:
    for item in _active_items():
        if item["id"] == item_id:
            return item
    return None


def delete_item(item_id: str) -> str:
    data = _read(_closet_path())
    for item in data.get("items", []):
        if item["id"] == item_id:
            item["active"] = False
            _write(_closet_path(), data)
            return f"Removed {item['name']} from your closet."
    return f"Item {item_id} not found."


def toggle_favorite(item_id: str) -> str:
    data = _read(_closet_path())
    for item in data.get("items", []):
        if item["id"] == item_id:
            item["favorite"] = not item.get("favorite", False)
            _write(_closet_path(), data)
            state = "added to" if item["favorite"] else "removed from"
            return f"{item['name']} {state} favourites."
    return f"Item {item_id} not found."


def attach_photo(item_id: str, source_path: str) -> str:
    """Copy a photo into assets/closet/{category}/ and update closet.json."""
    data = _read(_closet_path())
    for item in data.get("items", []):
        if item["id"] == item_id:
            cat      = item.get("category", "tops")
            dest_dir = BASE_DIR / "assets" / "closet" / cat
            dest_dir.mkdir(parents=True, exist_ok=True)
            src  = Path(source_path)
            ext  = src.suffix.lower() or ".jpg"
            dest = dest_dir / f"{item_id}{ext}"
            shutil.copy2(src, dest)
            rel  = str(dest.relative_to(BASE_DIR))
            item["photo"] = rel
            _write(_closet_path(), data)
            return f"Photo saved for {item['name']}."
    return f"Item {item_id} not found."
