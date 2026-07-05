# tests/test_analytics_cumulative_curve.py
"""Descending Pareto curve — 'top X% of SKUs = Y% of GMV'."""
import pytest

from xhs_ceramics_analytics.analytics.concentration import cumulative_curve


def test_top_two_of_ten_hold_eighty_percent():
    values = [40.0, 40.0] + [2.5] * 8  # top 20% (2 of 10) = 80% of total
    curve = cumulative_curve(values)
    assert len(curve) == 10
    assert curve[0]["rank"] == 1
    assert curve[1]["cum_item_frac"] == pytest.approx(0.2)
    assert curve[1]["cum_value_share"] == pytest.approx(0.8)
    assert curve[-1]["cum_item_frac"] == pytest.approx(1.0)
    assert curve[-1]["cum_value_share"] == pytest.approx(1.0)


def test_descending_and_monotonic():
    curve = cumulative_curve([1.0, 5.0, 3.0, 2.0])
    shares = [r["cum_value_share"] for r in curve]
    assert shares == sorted(shares)  # non-decreasing
    assert shares[0] == pytest.approx(5.0 / 11.0)  # largest first


def test_degrades_on_bad_input():
    assert cumulative_curve([]) == []
    assert cumulative_curve([0.0, 0.0]) == []
    assert cumulative_curve([-1.0, -2.0]) == []


def test_order_independent_with_dirty_entries():
    assert cumulative_curve([3.0, 1.0, float("nan"), 2.0]) == cumulative_curve([1.0, 2.0, 3.0])
