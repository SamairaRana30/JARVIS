"""tests/test_closet.py — Tests for closet_tool.py"""

import json
import sys
from pathlib import Path
from datetime import date, timedelta

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import closet_tool


@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "assets" / "closet").mkdir(parents=True)
    closet  = {"items": []}
    outfits = {"outfits": []}
    rules   = {"white": ["everything"], "black": ["everything"],
                "navy": ["white", "grey"], "denim": ["white", "black"]}
    (tmp_path / "data" / "closet.json").write_text(json.dumps(closet))
    (tmp_path / "data" / "outfits.json").write_text(json.dumps(outfits))
    (tmp_path / "data" / "color_rules.json").write_text(json.dumps(rules))
    (tmp_path / "data" / "schedule.json").write_text('{"classes":[]}')

    import yaml
    cfg = {"paths": {"closet": "data/closet.json", "outfits": "data/outfits.json"},
           "stylist": {"avoid_rewear_days": 3, "photo_path": "assets/closet/"},
           "weather": {"default_location": "Berlin"}}
    (tmp_path / "config.yaml").write_text(yaml.dump(cfg))
    monkeypatch.setattr(closet_tool, "BASE_DIR", tmp_path)
    yield tmp_path


def _items(tmp_path):
    return json.loads((tmp_path / "data" / "closet.json").read_text())["items"]


# ---------------------------------------------------------------------------

def test_add_item_saves(tmp_path):
    result = closet_tool.add_item("White Tee", "tops", ["white"], ["casual"])
    assert "Added" in result
    items = _items(tmp_path)
    assert len(items) == 1
    assert items[0]["name"] == "White Tee"
    assert items[0]["category"] == "tops"
    assert items[0]["colors"] == ["white"]

def test_add_item_id_format(tmp_path):
    closet_tool.add_item("Item A", "tops", ["white"])
    closet_tool.add_item("Item B", "bottoms", ["black"])
    items = _items(tmp_path)
    assert items[0]["id"] == "item_001"
    assert items[1]["id"] == "item_002"

def test_log_worn_updates_count(tmp_path):
    closet_tool.add_item("White Tee", "tops", ["white"])
    result = closet_tool.log_worn("White Tee")
    assert "Logged" in result
    items = _items(tmp_path)
    assert items[0]["times_worn"] == 1
    assert items[0]["last_worn"] == date.today().isoformat()

def test_log_worn_not_found():
    result = closet_tool.log_worn("Nonexistent Item")
    assert "Couldn't find" in result

def test_toggle_favorite(tmp_path):
    closet_tool.add_item("Test Item", "tops", ["white"])
    items = _items(tmp_path)
    item_id = items[0]["id"]
    result = closet_tool.toggle_favorite(item_id)
    assert "favourites" in result
    items = _items(tmp_path)
    assert items[0]["favorite"] is True

def test_delete_item(tmp_path):
    closet_tool.add_item("Delete Me", "tops", ["white"])
    items = _items(tmp_path)
    item_id = items[0]["id"]
    result = closet_tool.delete_item(item_id)
    assert "Removed" in result
    items = _items(tmp_path)
    assert items[0].get("active") is False

def test_get_all_items_excludes_inactive(tmp_path):
    closet_tool.add_item("Active", "tops", ["white"])
    closet_tool.add_item("Inactive", "tops", ["black"])
    items = _items(tmp_path)
    closet_tool.delete_item(items[1]["id"])
    active = closet_tool.get_all_items()
    assert len(active) == 1
    assert active[0]["name"] == "Active"

def test_color_match_white():
    assert closet_tool._color_matches("white", ["navy"]) is True

def test_color_match_no_match():
    assert closet_tool._color_matches("pink", ["navy"]) is False

def test_days_since_worn_never():
    item = {"last_worn": None}
    assert closet_tool._days_since_worn(item) == 9999

def test_days_since_worn_today():
    item = {"last_worn": date.today().isoformat()}
    assert closet_tool._days_since_worn(item) == 0

def test_days_since_worn_three_days():
    three_ago = (date.today() - timedelta(days=3)).isoformat()
    item = {"last_worn": three_ago}
    assert closet_tool._days_since_worn(item) == 3

def test_unworn_empty_closet():
    result = closet_tool.unworn()
    assert "closet" in result.lower() or "haven't" in result.lower()

def test_unworn_lists_items(tmp_path):
    closet_tool.add_item("Old Jacket", "outerwear", ["black"])
    result = closet_tool.unworn(days=0)
    assert "Old Jacket" in result

def test_get_stats_empty():
    result = closet_tool.get_stats()
    assert "empty" in result.lower()

def test_get_stats_with_items(tmp_path):
    closet_tool.add_item("Tee", "tops", ["white"], cost=19.99)
    result = closet_tool.get_stats()
    assert "1" in result
    assert "€" in result or "EUR" in result
