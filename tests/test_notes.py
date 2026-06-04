"""tests/test_notes.py — Tests for notes manager."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import tools


@pytest.fixture(autouse=True)
def patch_base(tmp_path, monkeypatch):
    for folder in ("quick", "study", "projects", "ideas", "meetings", "personal"):
        (tmp_path / "notes" / folder).mkdir(parents=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "backups").mkdir(exist_ok=True)
    (tmp_path / "data" / "notes_index.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(tools, "BASE_DIR", tmp_path)
    monkeypatch.setattr(tools, "PATHS", {
        "notes":       "notes/",
        "notes_index": "data/notes_index.json",
        "backups":     "backups/",
    })
    monkeypatch.setattr(tools, "CFG", {
        "notes": {"max_read_length": 500},
        "paths": {"backups": "backups/", "notes_index": "data/notes_index.json"},
    })


# ---------------------------------------------------------------------------

def test_save_note_creates_file():
    tools.save_note("This is a quick note about Python.", folder="quick")
    quick_dir = tools._notes_dir("quick")
    files = list(quick_dir.glob("*.md"))
    assert len(files) == 1


def test_save_note_frontmatter():
    tools.save_note("Flexbox layout ideas for the project.", folder="study")
    study_dir = tools._notes_dir("study")
    files = list(study_dir.glob("*.md"))
    content = files[0].read_text(encoding="utf-8")
    assert "---" in content
    assert "title:" in content
    assert "created:" in content


def test_save_note_updates_index():
    tools.save_note("Brainstorm idea for new feature.", folder="ideas")
    index = tools._read_index()
    assert len(index) == 1
    assert index[0]["folder"] == "ideas"


def test_search_notes_finds_match():
    tools.save_note("CSS flexbox is useful for layouts.", folder="study")
    result = tools.search_notes("flexbox")
    assert "flexbox" in result.lower()


def test_search_notes_no_match():
    tools.save_note("Python is great.", folder="quick")
    result = tools.search_notes("quantum physics")
    assert "No notes" in result


def test_auto_topic_detection_study():
    topic = tools._detect_topic("I need to debug this Python function and fix the code.")
    assert topic == "study"


def test_auto_topic_detection_ideas():
    topic = tools._detect_topic("What if we added an idea for a new brainstorm feature?")
    assert topic == "ideas"


def test_auto_topic_detection_default():
    topic = tools._detect_topic("Had a lovely walk today.")
    assert topic == "quick"


def test_organise_moves_study_note():
    tools.save_note("Debug this Python function and fix the bug in the code.", folder="quick")
    result = tools.organise_notes()
    assert "Organised 1" in result
    study_files = list(tools._notes_dir("study").glob("*.md"))
    assert len(study_files) == 1


def test_summarise_notes_returns_text():
    tools.save_note("CSS grid and flexbox are layout systems.", folder="study")
    result = tools.summarise_notes("CSS")
    assert len(result) > 0


def test_backup_created_on_index_write(tmp_path):
    tools.save_note("First note.", folder="quick")
    tools.save_note("Second note.", folder="quick")
    bak = tmp_path / "data" / "notes_index.bak"
    assert bak.exists()
