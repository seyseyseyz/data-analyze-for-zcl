"""Recoverable pools are listed in parallel — never summed into one net total."""
from xhs_ceramics_analytics.reporting.money_ledger import non_additive_ledger


def test_rows_sorted_by_amount_and_no_net_total():
    ledger = non_additive_ledger([
        {"name": "发货前退款", "amount": 129019.0, "controllability": "高"},
        {"name": "误拍退款", "amount": 185851.0, "controllability": "中"},
        {"name": "退货退款", "amount": 57660.0, "controllability": "低"},
    ])
    assert ledger["net_total"] is None
    assert [r["name"] for r in ledger["rows"]] == ["误拍退款", "发货前退款", "退货退款"]
    assert "不可相加" in ledger["banner"]


def test_dirty_amount_dropped():
    ledger = non_additive_ledger([
        {"name": "a", "amount": float("nan"), "controllability": "高"},
        {"name": "b", "amount": 100.0, "controllability": "低"},
    ])
    assert [r["name"] for r in ledger["rows"]] == ["b"]


def test_empty_is_safe():
    ledger = non_additive_ledger([])
    assert ledger["rows"] == []
    assert ledger["net_total"] is None
