"""tests/test_sites.py — Tests for sites manager."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


@pytest.fixture(autouse=True)
def patch_base(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()
    (tmp_path / "data" / "sites.json").write_text(
        '{"distracting":["youtube.com"],"study":["notion.so"],"quick_links":{"email":"https://mail.google.com"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "PATHS", {
        "sites":   "data/sites.json",
        "backups": "backups/",
        "notes_index": "data/notes_index.json",
    })
    monkeypatch.setattr(tools, "CFG", {"paths": {"backups": "backups/"}})


# ---------------------------------------------------------------------------

def test_list_distracting():
    result = tools.sites_list("distracting")
    assert "youtube.com" in result


def test_list_study():
    result = tools.sites_list("study")
    assert "notion.so" in result


def test_add_distracting():
    result = tools.sites_add("twitter.com", "distracting")
    assert "twitter.com" in result
    sites = tools._read_json(tools._p("sites"))
    assert "twitter.com" in sites["distracting"]


def test_add_study():
    result = tools.sites_add("github.com", "study")
    assert "github.com" in result


def test_remove_distracting():
    result = tools.sites_remove("youtube.com", "distracting")
    assert "Removed" in result
    sites = tools._read_json(tools._p("sites"))
    assert "youtube.com" not in sites["distracting"]


def test_remove_not_found():
    result = tools.sites_remove("notexist.com", "distracting")
    assert "not found" in result.lower()


def test_add_duplicate_ignored():
    tools.sites_add("notion.so", "study")
    sites = tools._read_json(tools._p("sites"))
    assert sites["study"].count("notion.so") == 1


def test_open_quick_link(monkeypatch):
    opened = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: opened.append(url))
    tools.open_quick_link("email")
    assert any("mail.google.com" in u for u in opened)


def test_backup_created_on_add(tmp_path):
    tools.sites_add("tiktok.com", "distracting")
    bak = tmp_path / "data" / "sites.bak"
    assert bak.exists()
