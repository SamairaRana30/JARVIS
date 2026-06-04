"""
notion_tool.py — Notion API integration for Jarvis.

Requires:
  pip install notion-client
  config.yaml → notion.token (from notion.so/my-integrations)
  Share pages with your integration inside Notion.

All operations are read-safe by default. Write ops are guarded.
"""

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.resolve()


def _load_cfg() -> dict:
    with open(BASE_DIR / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _get_token() -> str | None:
    cfg = _load_cfg()
    return cfg.get("notion", {}).get("token", "").strip() or None


def _client():
    """Return an authenticated Notion client."""
    try:
        from notion_client import Client  # type: ignore
    except ImportError:
        raise RuntimeError("notion-client not installed. Run: pip install notion-client")
    token = _get_token()
    if not token:
        raise RuntimeError(
            "No Notion token found. Add it to config.yaml under notion.token"
        )
    return Client(auth=token)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _page_text(page: dict) -> str:
    """Extract plain text from a Notion page properties."""
    title_prop = page.get("properties", {})
    for prop in title_prop.values():
        if prop.get("type") == "title":
            parts = prop.get("title", [])
            return "".join(p.get("plain_text", "") for p in parts)
    return page.get("id", "Untitled")


def _block_text(blocks: list) -> str:
    """Convert Notion blocks to plain text."""
    lines = []
    for block in blocks:
        btype = block.get("type", "")
        content = block.get(btype, {})
        rich = content.get("rich_text", [])
        text = "".join(r.get("plain_text", "") for r in rich)
        if text:
            lines.append(text)
    return "\n".join(lines)


def _make_paragraph(text: str) -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def _make_heading(text: str, level: int = 2) -> dict:
    t = f"heading_{level}"
    return {
        "object": "block",
        "type": t,
        t: {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _make_todo(text: str, checked: bool = False) -> dict:
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {
            "rich_text": [{"type": "text", "text": {"content": text}}],
            "checked": checked,
        },
    }


# ---------------------------------------------------------------------------
# Read operations
# ---------------------------------------------------------------------------

def notion_list_pages(limit: int = 20) -> str:
    """List all pages accessible to the integration."""
    try:
        nc = _client()
        results = nc.search(filter={"property": "object", "value": "page"}).get("results", [])
        if not results:
            return "No pages found. Make sure you've shared pages with the Jarvis integration."
        titles = [f"• {_page_text(p)}" for p in results[:limit]]
        return f"Found {len(results)} pages:\n" + "\n".join(titles)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.error("notion_list_pages: %s", e)
        return f"I couldn't access Notion: {e}"


def notion_search(query: str) -> str:
    """Search Notion pages by keyword."""
    try:
        nc = _client()
        results = nc.search(query=query, filter={"property": "object", "value": "page"}).get("results", [])
        if not results:
            return f"No Notion pages found matching '{query}'."
        titles = [f"• {_page_text(p)}" for p in results[:5]]
        return f"Found {len(results)} results for '{query}':\n" + "\n".join(titles)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Search failed: {e}"


def notion_read_page(query: str) -> str:
    """Find a page by name and read its content."""
    try:
        nc = _client()
        results = nc.search(query=query, filter={"property": "object", "value": "page"}).get("results", [])
        if not results:
            return f"No Notion page found matching '{query}'."
        page = results[0]
        page_id = page["id"]
        blocks = nc.blocks.children.list(block_id=page_id).get("results", [])
        text = _block_text(blocks)
        title = _page_text(page)
        if not text:
            return f"Page '{title}' exists but appears to be empty."
        max_chars = 800
        return f"**{title}**\n\n{text[:max_chars]}{'...' if len(text) > max_chars else ''}"
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't read page: {e}"


def notion_analyse_workspace(llm_caller=None) -> str:
    """Fetch page list and ask LLM to suggest organisation improvements."""
    try:
        nc = _client()
        results = nc.search(filter={"property": "object", "value": "page"}).get("results", [])
        if not results:
            return "Your Notion workspace appears to be empty or no pages are shared."
        titles = [_page_text(p) for p in results[:30]]
        summary = f"Pages in Notion workspace ({len(titles)} total):\n" + "\n".join(f"- {t}" for t in titles)
        if llm_caller:
            prompt = (
                f"Analyse this Notion workspace and give 3-5 specific, actionable suggestions "
                f"to improve its organisation. Be concise.\n\n{summary}"
            )
            return llm_caller(prompt)
        return summary
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't analyse workspace: {e}"


# ---------------------------------------------------------------------------
# Write operations
# ---------------------------------------------------------------------------

def notion_create_page(title: str, content: str = "", parent_page_id: str | None = None) -> str:
    """Create a new Notion page."""
    try:
        nc = _client()
        cfg = _load_cfg()
        parent_id = parent_page_id or cfg.get("notion", {}).get("default_page_id", "")

        parent = (
            {"type": "page_id", "page_id": parent_id}
            if parent_id
            else {"type": "workspace", "workspace": True}
        )

        children = []
        if content:
            for para in content.split("\n\n"):
                para = para.strip()
                if para:
                    children.append(_make_paragraph(para))

        page = nc.pages.create(
            parent=parent,
            properties={
                "title": {"title": [{"type": "text", "text": {"content": title}}]}
            },
            children=children or [_make_paragraph("Created by Jarvis.")],
        )
        return f"Created Notion page '{title}'."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.error("notion_create_page: %s", e)
        return f"Couldn't create page: {e}"


def notion_append_to_page(query: str, text: str) -> str:
    """Find a page by name and append text to it."""
    try:
        nc = _client()
        results = nc.search(query=query, filter={"property": "object", "value": "page"}).get("results", [])
        if not results:
            return f"No page found matching '{query}'. Try creating it first."
        page_id = results[0]["id"]
        title = _page_text(results[0])
        nc.blocks.children.append(
            block_id=page_id,
            children=[_make_paragraph(text)],
        )
        return f"Added to Notion page '{title}'."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't append to page: {e}"


def notion_add_todo(page_query: str, todo_text: str) -> str:
    """Add a to-do checkbox item to a Notion page."""
    try:
        nc = _client()
        results = nc.search(query=page_query, filter={"property": "object", "value": "page"}).get("results", [])
        if not results:
            return f"No page found matching '{page_query}'."
        page_id = results[0]["id"]
        title = _page_text(results[0])
        nc.blocks.children.append(
            block_id=page_id,
            children=[_make_todo(todo_text)],
        )
        return f"Added todo '{todo_text}' to '{title}'."
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        return f"Couldn't add todo: {e}"


def notion_status() -> str:
    """Check if Notion is connected."""
    token = _get_token()
    if not token:
        return "Notion is not configured. Add your token to config.yaml under notion.token."
    try:
        _client()
        return "Notion is connected."
    except Exception as e:
        return f"Notion connection failed: {e}"
