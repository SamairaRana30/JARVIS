"""tests/test_new_features.py — Tests for RAG, proactive engine, shortcuts."""

import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# RAG tool tests (without actually loading ChromaDB)
# ---------------------------------------------------------------------------

def test_chunk_text_basic():
    from rag_tool import _chunk_text
    text  = " ".join([f"word{i}" for i in range(600)])
    chunks = _chunk_text(text, chunk_size=100, overlap=10)
    assert len(chunks) > 1
    assert all(len(c) > 0 for c in chunks)


def test_chunk_text_short():
    from rag_tool import _chunk_text
    text   = "short text"
    chunks = _chunk_text(text, chunk_size=100)
    assert len(chunks) == 0   # too short (< 40 chars after splitting)


def test_doc_id_stable():
    from rag_tool import _doc_id
    id1 = _doc_id("notes/test.md", 0)
    id2 = _doc_id("notes/test.md", 0)
    assert id1 == id2


def test_doc_id_different_chunks():
    from rag_tool import _doc_id
    assert _doc_id("test.md", 0) != _doc_id("test.md", 1)


def test_rag_get_stats_no_collection():
    """get_stats should handle missing ChromaDB gracefully."""
    from rag_tool import get_stats
    with patch("rag_tool._get_collection", side_effect=RuntimeError("no db")):
        result = get_stats()
    assert isinstance(result, str)


def test_rag_search_empty():
    """search should return empty list when collection fails."""
    from rag_tool import search
    with patch("rag_tool._get_collection", side_effect=Exception("unavailable")):
        result = search("anything")
    assert result == []


# ---------------------------------------------------------------------------
# Proactive engine tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_proactive():
    import proactive_engine
    proactive_engine._last_suggestion_time    = datetime.min
    proactive_engine._last_jarvis_speak       = datetime.min
    yield


def test_record_jarvis_spoke():
    import proactive_engine
    proactive_engine.record_jarvis_spoke()
    silence = (datetime.now() - proactive_engine._last_jarvis_speak).total_seconds()
    assert silence < 2


def test_suppressed_when_just_spoke():
    import proactive_engine
    proactive_engine._last_jarvis_speak = datetime.now()
    assert proactive_engine._is_suppressed() is True


def test_not_suppressed_after_silence():
    import proactive_engine
    proactive_engine._last_jarvis_speak = datetime.now() - timedelta(minutes=20)
    # Patch the import inside _is_suppressed
    with patch.dict("sys.modules", {"jarvis": MagicMock(is_sleeping=lambda: False),
                                    "meeting_mode": MagicMock(is_in_meeting=lambda: False)}):
        result = proactive_engine._is_suppressed()
    assert result is False


def test_suggest_hydration_returns_tuple_or_none(tmp_path, monkeypatch):
    import proactive_engine
    wb_data = [{"date": date.today().isoformat(), "hydration_L": 0, "exercise": ""}]
    wb_path = tmp_path / "wellbeing.json"
    wb_path.write_text(json.dumps(wb_data))

    monkeypatch.setattr(proactive_engine, "_data",
        lambda p: json.loads(wb_path.read_text()) if "wellbeing" in p else {})

    def _fake_cfg():
        return {"paths": {"wellbeing": str(wb_path)}}
    monkeypatch.setattr(proactive_engine, "_cfg", _fake_cfg)

    result = proactive_engine._suggest_hydration()
    # Either None (wrong hour) or a (text, priority) tuple
    assert result is None or (isinstance(result, tuple) and len(result) == 2)


# ---------------------------------------------------------------------------
# Budget shortcut integration (via intent_router)
# ---------------------------------------------------------------------------

def _setup_budget(tmp_path, monkeypatch):
    import budget_tool, yaml
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "backups").mkdir(exist_ok=True)
    cfg = {"paths": {"budget": "data/budget.json", "transactions": "data/transactions.json",
                     "backups": "backups/"}, "budget": {"warning_threshold": 0.80}}
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    (tmp_path / "data" / "budget.json").write_text(
        json.dumps({"monthly_income": 800, "currency": "EUR",
                    "limits": {"food": 200}, "savings_goal": 0, "savings_current": 0})
    )
    (tmp_path / "data" / "transactions.json").write_text('{"transactions":[]}')
    monkeypatch.setattr(budget_tool, "BASE_DIR", tmp_path)


def test_budget_route_log_spending(tmp_path, monkeypatch):
    import intent_router, budget_tool
    _setup_budget(tmp_path, monkeypatch)
    result = intent_router.route("i spent 4.50 on coffee")
    assert result is not None
    assert "4.50" in result or "logged" in result.lower()


def test_budget_route_remaining(tmp_path, monkeypatch):
    import intent_router, budget_tool
    _setup_budget(tmp_path, monkeypatch)
    result = intent_router.route("how much do I have left for food")
    assert result is not None
    assert "food" in result.lower() or "200" in result


# ---------------------------------------------------------------------------
# Closet router tests
# ---------------------------------------------------------------------------

def test_closet_router_log_worn(tmp_path, monkeypatch):
    import intent_router, closet_tool

    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "backups").mkdir(exist_ok=True)
    closet = {"items": [{"id": "item_001", "name": "white tee", "category": "tops",
                          "colors": ["white"], "active": True, "times_worn": 0,
                          "last_worn": None, "favorite": False}]}
    (tmp_path / "data" / "closet.json").write_text(json.dumps(closet))

    monkeypatch.setattr(closet_tool, "BASE_DIR", tmp_path)
    monkeypatch.setattr(closet_tool, "_cfg",
        lambda: {"paths": {"closet": "data/closet.json"}, "stylist": {"avoid_rewear_days": 3}})

    result = intent_router.route("i wore my white tee today")
    assert result is not None
    assert "white tee" in result.lower() or "Logged" in result
