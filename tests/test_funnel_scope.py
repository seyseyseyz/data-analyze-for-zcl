"""Tests for the shared shop_page_funnel scope normalization layer."""
from xhs_ceramics_analytics.analysis.funnel_scope import (
    ROLLUP,
    canonical_cycle,
    normalize_funnel_rows,
)


def test_canonical_cycle_picks_widest_numeric_window():
    assert canonical_cycle(["180天", "365天", "180天"]) == "365天"


def test_canonical_cycle_none_when_no_numeric_label():
    assert canonical_cycle(["首购", "复购"]) is None
    assert canonical_cycle([]) is None


def test_normalize_drops_rollup_and_collapses_window():
    rows = [
        {"audience_type": ROLLUP, "first_purchase_cycle": None, "shop_visitors": 100, "shop_payers": 10},
        {"audience_type": "新客", "first_purchase_cycle": "180天", "shop_visitors": 40, "shop_payers": 3},
        {"audience_type": "新客", "first_purchase_cycle": "365天", "shop_visitors": 60, "shop_payers": 5},
        {"audience_type": "老客", "first_purchase_cycle": "180天", "shop_visitors": 20, "shop_payers": 4},
        {"audience_type": "老客", "first_purchase_cycle": "365天", "shop_visitors": 30, "shop_payers": 6},
    ]
    segment_rows, rollup_rows, canonical = normalize_funnel_rows(
        rows, has_audience=True, has_cycle=True
    )
    assert canonical == "365天"
    # Rollup separated out
    assert len(rollup_rows) == 1 and rollup_rows[0]["audience_type"] == ROLLUP
    # Segments collapsed to the widest window only — no 180天 rows, no 全部
    assert {r["audience_type"] for r in segment_rows} == {"新客", "老客"}
    assert all(r["first_purchase_cycle"] == "365天" for r in segment_rows)
    assert len(segment_rows) == 2


def test_normalize_without_cycle_column_keeps_all_segments():
    rows = [
        {"audience_type": ROLLUP, "shop_visitors": 100, "shop_payers": 10},
        {"audience_type": "新客", "shop_visitors": 60, "shop_payers": 5},
        {"audience_type": "老客", "shop_visitors": 40, "shop_payers": 5},
    ]
    segment_rows, rollup_rows, canonical = normalize_funnel_rows(
        rows, has_audience=True, has_cycle=False
    )
    assert canonical is None
    assert len(rollup_rows) == 1
    assert {r["audience_type"] for r in segment_rows} == {"新客", "老客"}


def test_normalize_without_audience_column_no_rollup():
    rows = [
        {"shop_visitors": 60, "shop_payers": 5},
        {"shop_visitors": 40, "shop_payers": 5},
    ]
    segment_rows, rollup_rows, canonical = normalize_funnel_rows(
        rows, has_audience=False, has_cycle=False
    )
    assert rollup_rows == []
    assert len(segment_rows) == 2
