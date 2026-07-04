"""Concentration primitives — Gini, HHI, top-share, trend."""
import pytest

from xhs_ceramics_analytics.analytics.concentration import (
    concentration_trend,
    gini,
    hhi,
    top_share,
)


def test_gini_uniform_near_zero():
    assert gini([10.0, 10.0, 10.0, 10.0]) == pytest.approx(0.0, abs=1e-9)


def test_gini_monopoly_near_one():
    # One holder has everything → Gini approaches (n-1)/n.
    g = gini([0.0, 0.0, 0.0, 100.0])
    assert g > 0.7


def test_gini_known_value():
    # Classic reference: [1,2,3,4,5] → Gini ≈ 0.2667.
    assert gini([1.0, 2.0, 3.0, 4.0, 5.0]) == pytest.approx(0.2667, abs=0.001)


def test_gini_degrades():
    assert gini([]) is None
    assert gini([5.0]) is None or gini([5.0]) == 0.0
    assert gini([-1.0, -2.0]) is None  # negatives are not a valid share basis


def test_hhi_uniform_and_monopoly():
    assert hhi([25.0, 25.0, 25.0, 25.0]) == pytest.approx(0.25)
    assert hhi([100.0]) == pytest.approx(1.0)


def test_hhi_degrades():
    assert hhi([]) is None
    assert hhi([0.0, 0.0]) is None  # zero total


def test_top_share_pareto():
    # 10 holders, top 20% (2 largest) hold 80.
    values = [40.0, 40.0] + [2.5] * 8
    assert top_share(values, 0.2) == pytest.approx(0.8, abs=0.001)


def test_top_share_degrades():
    assert top_share([], 0.2) == 0.0 or top_share([], 0.2) is None


def test_concentration_trend_per_period():
    data = {
        "2026-04": [1.0, 1.0, 1.0, 1.0],       # even
        "2026-05": [0.0, 0.0, 0.0, 100.0],     # concentrated
    }
    trend = concentration_trend(data)
    assert len(trend) == 2
    by_period = {r["period"]: r for r in trend}
    assert by_period["2026-05"]["gini"] > by_period["2026-04"]["gini"]


def test_gini_and_hhi_ignore_nan_instead_of_returning_nan():
    assert gini([1.0, 2.0, float("nan"), 3.0]) == gini([1.0, 2.0, 3.0])
    assert hhi([1.0, float("inf"), 1.0]) == hhi([1.0, 1.0])


def test_gini_is_order_independent_with_dirty_entries():
    # NaN dropped before sorted() → result cannot depend on input order.
    assert gini([3.0, 1.0, float("nan"), 2.0]) == gini([1.0, 2.0, 3.0, float("nan")])
