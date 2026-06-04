"""tests/test_budget.py — Tests for budget_tool.py"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import budget_tool


@pytest.fixture(autouse=True)
def patch_paths(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "backups").mkdir()
    budget = {"monthly_income": 800, "currency": "EUR", "month": "2025-06",
               "limits": {"food": 200, "transport": 80, "clothes": 100},
               "savings_goal": 150, "savings_current": 0}
    txns   = {"transactions": []}
    cfg    = {"paths": {"budget": "data/budget.json",
                        "transactions": "data/transactions.json",
                        "backups": "backups/"},
              "budget": {"warning_threshold": 0.80}}
    (tmp_path / "data" / "budget.json").write_text(json.dumps(budget))
    (tmp_path / "data" / "transactions.json").write_text(json.dumps(txns))
    (tmp_path / "config.yaml").write_text(
        __import__("yaml").dump(cfg)
    )
    monkeypatch.setattr(budget_tool, "BASE_DIR", tmp_path)
    yield tmp_path


def _txns(tmp_path):
    return json.loads((tmp_path / "data" / "transactions.json").read_text())["transactions"]


# ---------------------------------------------------------------------------

def test_parse_amount_decimal():
    assert budget_tool.parse_amount("4.50") == pytest.approx(4.50)

def test_parse_amount_comma():
    assert budget_tool.parse_amount("4,50") == pytest.approx(4.50)

def test_parse_amount_euro_symbol():
    assert budget_tool.parse_amount("€12.99") == pytest.approx(12.99)

def test_parse_amount_none():
    assert budget_tool.parse_amount("no number here") is None

def test_auto_detect_food():
    assert budget_tool.auto_detect_category("coffee at the cafe") == "food"

def test_auto_detect_transport():
    assert budget_tool.auto_detect_category("bvg monthly ticket") == "transport"

def test_auto_detect_clothes():
    assert budget_tool.auto_detect_category("new shoes from Zara") == "clothes"

def test_auto_detect_default():
    assert budget_tool.auto_detect_category("random thing") == "other"

def test_log_transaction_saves(tmp_path):
    budget_tool.log_transaction(4.50, "coffee", category="food")
    txns = _txns(tmp_path)
    assert len(txns) == 1
    assert txns[0]["amount"] == 4.50
    assert txns[0]["category"] == "food"
    assert txns[0]["description"] == "coffee"

def test_log_transaction_ids_increment(tmp_path):
    budget_tool.log_transaction(1.0, "a", category="food")
    budget_tool.log_transaction(2.0, "b", category="food")
    txns = _txns(tmp_path)
    assert txns[0]["id"] == "txn_001"
    assert txns[1]["id"] == "txn_002"

def test_category_total_empty():
    assert budget_tool._category_total("food", "month") == pytest.approx(0.0)

def test_category_total_after_log(tmp_path):
    budget_tool.log_transaction(10.0, "lunch", category="food")
    budget_tool.log_transaction(5.0,  "coffee", category="food")
    assert budget_tool._category_total("food", "month") == pytest.approx(15.0)

def test_remaining_under_budget(tmp_path):
    budget_tool.log_transaction(50.0, "groceries", category="food")
    result = budget_tool.remaining("food")
    assert "150" in result or "left" in result.lower()

def test_remaining_over_budget(tmp_path):
    budget_tool.log_transaction(250.0, "big shop", category="food")
    result = budget_tool.remaining("food")
    assert "over" in result.lower()

def test_set_limit(tmp_path):
    budget_tool.set_limit("food", 300.0)
    b = json.loads((tmp_path / "data" / "budget.json").read_text())
    assert b["limits"]["food"] == 300.0

def test_set_income(tmp_path):
    budget_tool.set_income(1000.0)
    b = json.loads((tmp_path / "data" / "budget.json").read_text())
    assert b["monthly_income"] == 1000.0

def test_log_savings(tmp_path):
    result = budget_tool.log_savings(50.0)
    assert "50" in result
    b = json.loads((tmp_path / "data" / "budget.json").read_text())
    assert b["savings_current"] == pytest.approx(50.0)

def test_today_spending_empty():
    result = budget_tool.today_spending()
    assert "No spending" in result

def test_overview_returns_string():
    result = budget_tool.overview()
    assert isinstance(result, str) and len(result) > 0

def test_delete_transaction(tmp_path):
    budget_tool.log_transaction(5.0, "test", category="food")
    txns = _txns(tmp_path)
    txn_id = txns[0]["id"]
    result = budget_tool.delete_transaction(txn_id)
    assert "Deleted" in result
    assert len(_txns(tmp_path)) == 0
