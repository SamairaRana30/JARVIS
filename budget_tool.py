"""
budget_tool.py — Local spending tracker for Jarvis.

No bank connections. Everything manual or voice-logged.
Data files:
  data/budget.json       — monthly limits, income, savings goal
  data/transactions.json — all spending entries
"""

import json
import logging
import re
import shutil
from calendar import monthrange
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()

CATEGORY_ICONS = {
    "food":          "🍕",
    "transport":     "🚌",
    "uni":           "📚",
    "clothes":       "👗",
    "health":        "💊",
    "entertainment": "🎬",
    "personal":      "💇",
    "tech":          "💻",
    "other":         "📦",
    "income":        "💰",
    "savings":       "🏦",
}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "food":          ["coffee", "lunch", "dinner", "breakfast", "grocery", "groceries",
                      "lidl", "rewe", "aldi", "netto", "edeka", "restaurant", "takeaway",
                      "pizza", "kebab", "bakery", "cafe", "snack", "food", "drink",
                      "supermarket", "burger", "sushi", "döner", "mensa", "canteen"],
    "transport":     ["bvg", "ticket", "uber", "taxi", "bus", "train", "sbahn", "ubahn",
                      "metro", "tram", "fuel", "petrol", "parking", "flight", "db",
                      "transport", "monthly pass", "weekly pass", "transit"],
    "uni":           ["book", "textbook", "printing", "print", "supplies", "stationery",
                      "software", "library", "course", "study", "university", "uni",
                      "lecture", "exam", "tuition", "subscription", "adobe", "overleaf"],
    "clothes":       ["zara", "h&m", "hm", "nike", "adidas", "shoes", "jacket", "dress",
                      "shirt", "trousers", "jeans", "coat", "clothes", "clothing",
                      "fashion", "primark", "uniqlo", "cos", "asos", "top", "skirt"],
    "health":        ["pharmacy", "doctor", "dentist", "gym", "sports", "medicine",
                      "prescription", "appointment", "clinic", "hospital", "vitamin",
                      "supplement", "fitness", "drugstore", "dm", "rossmann"],
    "entertainment": ["cinema", "movie", "concert", "museum", "game", "games", "netflix",
                      "spotify", "youtube", "amazon prime", "disney", "streaming",
                      "ticket", "event", "club", "bar", "pub", "theatre"],
    "personal":      ["haircut", "hair", "salon", "cosmetics", "makeup", "skincare",
                      "beauty", "nails", "waxing", "shampoo", "perfume", "deodorant"],
    "tech":          ["phone", "laptop", "charger", "cable", "headphone", "earphone",
                      "gadget", "electronics", "repair", "case", "keyboard", "mouse",
                      "media markt", "saturn", "amazon electronics"],
}


# ---------------------------------------------------------------------------
# Config + I/O helpers
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _budget_path() -> Path:
    return BASE_DIR / "data" / "budget.json"


def _txn_path() -> Path:
    return BASE_DIR / "data" / "transactions.json"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write(path: Path, data: dict) -> None:
    bak = path.with_suffix(".bak")
    if path.exists():
        shutil.copy(path, bak)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")


def _next_txn_id(txns: list) -> str:
    nums = []
    for t in txns:
        try:
            nums.append(int(t["id"].split("_")[1]))
        except Exception:
            pass
    return f"txn_{(max(nums, default=0) + 1):03d}"


def _currency() -> str:
    return _read(_budget_path()).get("currency", "EUR")


# ---------------------------------------------------------------------------
# Amount parsing
# ---------------------------------------------------------------------------

def parse_amount(text: str) -> float | None:
    """Parse amounts like '4.50', '4,50', '€4.50', '86', 'four fifty'."""
    text = text.strip().lower().replace("€", "").replace("eur", "").strip()
    # Replace comma decimal separator
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    m = re.search(r"(\d+\.?\d*)", text)
    if m:
        return float(m.group(1))
    # Word numbers (basic)
    word_map = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
    for word, val in word_map.items():
        if word in text:
            rest = re.search(r"(\d+\.?\d*)", text.replace(word, ""))
            if rest:
                return val + float(rest.group(1)) / 100
            return float(val)
    return None


# ---------------------------------------------------------------------------
# Category detection
# ---------------------------------------------------------------------------

def auto_detect_category(description: str, llm_caller=None) -> str:
    """Fast keyword match, with LLM fallback."""
    desc_l = description.lower()
    for cat, keywords in CATEGORY_KEYWORDS.items():
        if any(kw in desc_l for kw in keywords):
            return cat

    if llm_caller:
        try:
            raw = llm_caller(
                f"Classify this purchase into exactly one of these categories: "
                f"food, transport, uni, clothes, health, entertainment, personal, tech, other.\n"
                f"Purchase: {description}\n"
                f"Reply with only the category name, nothing else."
            ).strip().lower()
            valid = set(CATEGORY_KEYWORDS.keys()) | {"other"}
            return raw if raw in valid else "other"
        except Exception:
            pass
    return "other"


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def log_transaction(amount: float, description: str, category: str | None = None,
                    payment_method: str = "card", llm_caller=None) -> str:
    """Record a new transaction and return a spoken confirmation."""
    cat = category or auto_detect_category(description, llm_caller)
    data = _read(_txn_path())
    txns = data.setdefault("transactions", [])

    txn = {
        "id":             _next_txn_id(txns),
        "date":           date.today().isoformat(),
        "amount":         round(amount, 2),
        "currency":       _currency(),
        "category":       cat,
        "subcategory":    "",
        "description":    description,
        "payment_method": payment_method,
        "notes":          "",
        "recurring":      False,
    }
    txns.append(txn)
    _write(_txn_path(), data)

    # Check category limit
    budget = _read(_budget_path())
    limit  = budget.get("limits", {}).get(cat, 0)
    cur    = _currency()
    spent  = _category_total(cat, "month")
    icon   = CATEGORY_ICONS.get(cat, "📦")

    base_msg = f"Logged {cur}{amount:.2f} for {description} under {cat}."

    if limit > 0:
        pct = spent / limit
        if pct > 1.0:
            over = spent - limit
            warning = f" ⚠️ You've gone over your {cat} budget by {cur}{over:.0f} this month."
        elif pct >= 0.8:
            warning = f" Heads up — you're at {int(pct*100)}% of your {cat} budget."
        else:
            warning = f" You've spent {cur}{spent:.0f} of your {cur}{limit:.0f} {cat} budget."
        return base_msg + warning

    return base_msg


def _category_total(category: str, period: str = "month") -> float:
    """Sum all transactions for a category in the given period."""
    txns   = _read(_txn_path()).get("transactions", [])
    cutoff = _period_start(period)
    return sum(
        t["amount"] for t in txns
        if t.get("category") == category and t.get("date", "") >= cutoff
    )


def _period_start(period: str) -> str:
    today = date.today()
    if period == "today":
        return today.isoformat()
    if period == "week":
        return (today - timedelta(days=today.weekday())).isoformat()
    if period == "month":
        return today.replace(day=1).isoformat()
    if period == "year":
        return today.replace(month=1, day=1).isoformat()
    return today.replace(day=1).isoformat()


def summary(period: str = "month") -> str:
    """Return a spoken spending summary for the given period."""
    txns   = _read(_txn_path()).get("transactions", [])
    cutoff = _period_start(period)
    cur    = _currency()

    period_txns = [t for t in txns if t.get("date", "") >= cutoff]
    if not period_txns:
        return f"No spending recorded {period.replace('_', ' ')}."

    total = sum(t["amount"] for t in period_txns)
    by_cat: dict[str, float] = {}
    for t in period_txns:
        cat = t.get("category", "other")
        by_cat[cat] = by_cat.get(cat, 0) + t["amount"]

    top = sorted(by_cat.items(), key=lambda x: x[1], reverse=True)[:4]
    top_str = ", ".join(f"{CATEGORY_ICONS.get(c,'')}{c}: {cur}{v:.0f}" for c, v in top)

    period_label = {"today": "today", "week": "this week",
                    "month": "this month", "year": "this year"}.get(period, period)
    return f"You've spent {cur}{total:.2f} {period_label}. Top categories: {top_str}."


def category_summary(category: str, period: str = "month") -> str:
    """Return spending in a specific category."""
    spent  = _category_total(category, period)
    budget = _read(_budget_path())
    limit  = budget.get("limits", {}).get(category, 0)
    cur    = _currency()
    period_label = {"today": "today", "week": "this week",
                    "month": "this month"}.get(period, period)

    if limit:
        pct = spent / limit * 100
        return (
            f"You've spent {cur}{spent:.2f} on {category} {period_label} "
            f"({pct:.0f}% of your {cur}{limit:.0f} budget)."
        )
    return f"You've spent {cur}{spent:.2f} on {category} {period_label}."


def remaining(category: str) -> str:
    """How much is left in a category budget this month."""
    budget = _read(_budget_path())
    limit  = budget.get("limits", {}).get(category, 0)
    spent  = _category_total(category, "month")
    cur    = _currency()

    if not limit:
        return f"No budget set for {category}."

    left = limit - spent
    if left < 0:
        return f"You're {cur}{abs(left):.2f} over your {category} budget this month."
    return f"You have {cur}{left:.2f} left in your {category} budget this month."


def overview() -> str:
    """Full monthly budget overview."""
    budget = _read(_budget_path())
    txns   = _read(_txn_path()).get("transactions", [])
    cur    = budget.get("currency", "EUR")
    income = float(budget.get("monthly_income", 0))
    limits = budget.get("limits", {})
    today  = date.today()
    month_start = today.replace(day=1).isoformat()

    month_txns = [t for t in txns if t.get("date", "") >= month_start]
    total_spent = sum(t["amount"] for t in month_txns)

    lines = [f"Budget overview for {today.strftime('%B %Y')}."]
    if income:
        lines.append(f"Income: {cur}{income:.0f}. Spent: {cur}{total_spent:.2f}. "
                     f"Remaining: {cur}{income - total_spent:.2f}.")

    over_budget = []
    near_budget = []
    for cat, limit in limits.items():
        spent = _category_total(cat, "month")
        if limit and spent > limit:
            over_budget.append(f"{cat} ({cur}{spent:.0f}/{cur}{limit:.0f})")
        elif limit and spent / limit >= 0.8:
            near_budget.append(f"{cat} at {int(spent/limit*100)}%")

    if over_budget:
        lines.append(f"Over budget: {', '.join(over_budget)}.")
    if near_budget:
        lines.append(f"Near limit: {', '.join(near_budget)}.")

    # Days remaining
    days_left = monthrange(today.year, today.month)[1] - today.day
    if days_left > 0 and total_spent > 0:
        daily_avg  = total_spent / today.day
        projected  = daily_avg * monthrange(today.year, today.month)[1]
        lines.append(f"{days_left} days left. Projected month-end: {cur}{projected:.0f}.")

    # Savings
    sav_goal = float(budget.get("savings_goal", 0))
    sav_curr = float(budget.get("savings_current", 0))
    if sav_goal:
        lines.append(f"Savings: {cur}{sav_curr:.0f} of {cur}{sav_goal:.0f} goal.")

    return " ".join(lines)


def today_spending() -> str:
    """What did I spend today?"""
    txns  = _read(_txn_path()).get("transactions", [])
    today = date.today().isoformat()
    cur   = _currency()
    today_txns = [t for t in txns if t.get("date") == today]
    if not today_txns:
        return "No spending recorded today."
    total = sum(t["amount"] for t in today_txns)
    lines = [f"Today you spent {cur}{total:.2f}:"]
    for t in today_txns:
        icon = CATEGORY_ICONS.get(t.get("category", "other"), "📦")
        lines.append(f"  {icon} {t['description']} — {cur}{t['amount']:.2f}")
    return "\n".join(lines)


def top_expenses(period: str = "month", n: int = 5) -> str:
    """Return the biggest single expenses in the period."""
    txns   = _read(_txn_path()).get("transactions", [])
    cutoff = _period_start(period)
    cur    = _currency()
    period_txns = sorted(
        [t for t in txns if t.get("date", "") >= cutoff],
        key=lambda t: t["amount"], reverse=True
    )[:n]
    if not period_txns:
        return f"No transactions recorded {period}."
    lines = [f"Biggest expenses {period}:"]
    for i, t in enumerate(period_txns, 1):
        lines.append(f"{i}. {t['description']} — {cur}{t['amount']:.2f}")
    return "\n".join(lines)


def afford_check(item: str, price: float, llm_caller=None) -> str:
    """Can I afford this? Check relevant category budget."""
    cat   = auto_detect_category(item, llm_caller)
    spent = _category_total(cat, "month")
    budget = _read(_budget_path())
    limit  = budget.get("limits", {}).get(cat, 0)
    cur    = _currency()

    if not limit:
        return f"No budget set for {cat}. {cur}{price:.2f} seems reasonable — up to you."

    left = limit - spent
    after = left - price

    if after >= 0:
        return (
            f"Your {cat} budget has {cur}{left:.2f} left. "
            f"A {cur}{price:.2f} purchase would leave you {cur}{after:.2f}. Looks fine."
        )
    else:
        over = abs(after)
        return (
            f"Your {cat} budget has {cur}{left:.2f} left. "
            f"Buying this for {cur}{price:.2f} would put you {cur}{over:.2f} over budget."
        )


def set_limit(category: str, amount: float) -> str:
    """Update a category budget limit."""
    data = _read(_budget_path())
    data.setdefault("limits", {})[category] = round(amount, 2)
    _write(_budget_path(), data)
    return f"Set {category} budget to {data['currency']}{amount:.0f} per month."


def set_income(amount: float) -> str:
    """Update monthly income."""
    data = _read(_budget_path())
    data["monthly_income"] = round(amount, 2)
    _write(_budget_path(), data)
    return f"Monthly income updated to {data['currency']}{amount:.0f}."


def log_savings(amount: float) -> str:
    """Add to savings."""
    data = _read(_budget_path())
    data["savings_current"] = round(float(data.get("savings_current", 0)) + amount, 2)
    _write(_budget_path(), data)
    cur  = data.get("currency", "EUR")
    goal = float(data.get("savings_goal", 0))
    curr = data["savings_current"]
    if goal:
        left = goal - curr
        return f"Added {cur}{amount:.2f} to savings. Total: {cur}{curr:.2f} of {cur}{goal:.0f} goal. {cur}{left:.2f} to go."
    return f"Added {cur}{amount:.2f} to savings. Total: {cur}{curr:.2f}."


def savings_status() -> str:
    """Return savings progress."""
    data = _read(_budget_path())
    cur  = data.get("currency", "EUR")
    goal = float(data.get("savings_goal", 0))
    curr = float(data.get("savings_current", 0))
    if not goal:
        return f"You have {cur}{curr:.2f} saved. No goal set."
    pct  = curr / goal * 100
    left = goal - curr
    return (
        f"Savings: {cur}{curr:.2f} of {cur}{goal:.0f} goal ({pct:.0f}%). "
        + (f"{cur}{left:.2f} to go." if left > 0 else "Goal reached! 🎉")
    )


def budget_briefing_check() -> str:
    """For morning briefing: warn if any category is near/over limit."""
    budget = _read(_budget_path())
    limits = budget.get("limits", {})
    cur    = budget.get("currency", "EUR")
    cfg    = _cfg()
    threshold = float(cfg.get("budget", {}).get("warning_threshold", 0.80))

    warnings = []
    for cat, limit in limits.items():
        if not limit:
            continue
        spent = _category_total(cat, "month")
        pct   = spent / limit
        if pct > 1.0:
            warnings.append(f"{cat} is over budget ({cur}{spent:.0f}/{cur}{limit:.0f})")
        elif pct >= threshold:
            warnings.append(f"{cat} is at {int(pct*100)}% of limit")

    if not warnings:
        return ""
    return "Budget alert: " + "; ".join(warnings) + "."


def get_monthly_data() -> dict:
    """Return structured data for the dashboard panel."""
    budget = _read(_budget_path())
    txns   = _read(_txn_path()).get("transactions", [])
    today  = date.today()
    month_start = today.replace(day=1).isoformat()

    month_txns = [t for t in txns if t.get("date", "") >= month_start]
    by_cat: dict[str, float] = {}
    for t in month_txns:
        cat = t.get("category", "other")
        by_cat[cat] = by_cat.get(cat, 0.0) + t["amount"]

    return {
        "budget":       budget,
        "by_category":  by_cat,
        "total_spent":  sum(t["amount"] for t in month_txns),
        "transactions": month_txns,
        "today_txns":   [t for t in month_txns if t.get("date") == today.isoformat()],
    }


def delete_transaction(txn_id: str) -> str:
    data = _read(_txn_path())
    txns = data.get("transactions", [])
    before = len(txns)
    data["transactions"] = [t for t in txns if t.get("id") != txn_id]
    if len(data["transactions"]) == before:
        return f"Transaction {txn_id} not found."
    _write(_txn_path(), data)
    return f"Deleted transaction {txn_id}."
