"""
wikipedia_tool.py — Free Wikipedia lookup, no API key.
Used as a factual fallback to prevent LLM hallucination on factual questions.
"""

import logging
import re

import requests

logger = logging.getLogger(__name__)

_WIKI_API = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
_WIKI_SEARCH = "https://en.wikipedia.org/w/api.php"


def _search_wikipedia(query: str) -> str | None:
    """Return the page title of the best Wikipedia match."""
    try:
        resp = requests.get(
            _WIKI_SEARCH,
            params={"action": "query", "list": "search", "srsearch": query,
                    "format": "json", "srlimit": 1},
            timeout=5,
            headers={"User-Agent": "Jarvis/1.0"},
        )
        results = resp.json().get("query", {}).get("search", [])
        return results[0]["title"] if results else None
    except Exception as e:
        logger.warning("Wikipedia search failed: %s", e)
        return None


def lookup(query: str, sentences: int = 2) -> str:
    """
    Look up a topic on Wikipedia.
    Returns a spoken summary (up to `sentences` sentences).
    """
    try:
        title = _search_wikipedia(query)
        if not title:
            return f"I couldn't find Wikipedia information on '{query}'."

        resp = requests.get(
            _WIKI_API.format(title=title.replace(" ", "_")),
            timeout=5,
            headers={"User-Agent": "Jarvis/1.0"},
        )
        data = resp.json()
        if data.get("type") == "disambiguation":
            return f"{title} is a disambiguation page. Please be more specific."

        extract = data.get("extract", "")
        if not extract:
            return f"No summary available for {title}."

        # Return first N sentences
        sents = re.split(r"(?<=[.!?])\s+", extract)
        summary = " ".join(sents[:sentences])
        return f"According to Wikipedia: {summary}"
    except Exception as e:
        logger.warning("Wikipedia lookup failed: %s", e)
        return f"Wikipedia lookup failed: {e}"


def is_factual_question(text: str) -> bool:
    """Heuristic: does this look like a factual lookup question?"""
    patterns = [
        r"\bwhat is\b", r"\bwho is\b", r"\bwhen was\b", r"\bwhere is\b",
        r"\bwhat are\b", r"\bhow does\b", r"\bdefine\b", r"\bexplain\b",
        r"\btell me about\b", r"\bwhat was\b",
    ]
    text_l = text.lower()
    return any(re.search(p, text_l) for p in patterns)
