"""
news_tool.py — RSS news headlines. No API key, no account.
Parses public RSS feeds from BBC, Reuters, and others.
Requires internet connection.
"""

import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)
BASE_DIR = Path(__file__).parent.resolve()

DEFAULT_FEEDS = {
    "bbc":     "http://feeds.bbci.co.uk/news/rss.xml",
    "reuters": "https://feeds.reuters.com/reuters/topNews",
    "tech":    "http://feeds.bbci.co.uk/news/technology/rss.xml",
    "science": "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
    "world":   "http://feeds.bbci.co.uk/news/world/rss.xml",
}


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text).strip()


def _fetch_feed(url: str, max_items: int = 5) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of {title, description}."""
    try:
        resp = requests.get(url, timeout=6, headers={"User-Agent": "Jarvis/1.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            desc  = _strip_html(item.findtext("description", "")).strip()
            if title:
                items.append({"title": title, "description": desc[:150]})
            if len(items) >= max_items:
                break
        return items
    except Exception as e:
        logger.warning("RSS fetch failed (%s): %s", url, e)
        return []


def get_headlines(source: str = "bbc", count: int = 3) -> str:
    """Return top N headlines from the given source as a spoken string."""
    cfg = _load_cfg()
    feeds = cfg.get("news", {}).get("feeds", DEFAULT_FEEDS)
    url = feeds.get(source.lower(), DEFAULT_FEEDS.get(source.lower(), DEFAULT_FEEDS["bbc"]))

    items = _fetch_feed(url, max_items=count)
    if not items:
        return f"Couldn't fetch {source} headlines right now. Check your connection."

    source_name = source.title()
    lines = [f"Here are {count} headlines from {source_name}."]
    for i, item in enumerate(items, 1):
        lines.append(f"{i}. {item['title']}.")
    return " ".join(lines)


def get_news_briefing(llm_caller=None) -> str:
    """Fetch top 3 headlines from BBC and return a spoken briefing."""
    items = _fetch_feed(DEFAULT_FEEDS["bbc"], max_items=3)
    if not items:
        return "I couldn't reach the news right now."

    headlines = " ".join(f"{i+1}. {it['title']}." for i, it in enumerate(items))
    if llm_caller:
        return llm_caller(
            f"Give a brief 2-sentence spoken news summary based on these BBC headlines:\n{headlines}"
        )
    return f"Today's top headlines. {headlines}"


def list_news_sources() -> str:
    cfg = _load_cfg()
    sources = list(cfg.get("news", {}).get("feeds", DEFAULT_FEEDS).keys())
    return "Available news sources: " + ", ".join(s.title() for s in sources) + "."
