"""Money primitives — per-visitor efficiency, ceiling counterfactual, pre-ship pool."""
import pytest

from xhs_ceramics_analytics.reporting.money import (
    efficiency_ceiling,
    per_visitor_gmv,
    preship_recoverable,
)


def test_per_visitor_gmv_uses_product_visitors():
    assert per_visitor_gmv(4000.0, 400.0) == pytest.approx(10.0)


def test_per_visitor_gmv_degrades():
    assert per_visitor_gmv(4000.0, 0.0) is None
    assert per_visitor_gmv(4000.0, None) is None
    assert per_visitor_gmv(None, 400.0) is None


def test_efficiency_ceiling_sums_negative_drags():
    bridge = {"contrib_traffic": 30000.0, "contrib_conversion": -28000.0, "contrib_aov": -34000.0}
    ceil = efficiency_ceiling(bridge)
    assert ceil["ceiling_gmv"] == pytest.approx(62000.0)  # |−28k| + |−34k|
    assert set(ceil["factors"]) == {"转化", "客单价"}
    assert ceil["label"] == "上限（乐观估计）"


def test_efficiency_ceiling_ignores_positive_factors():
    bridge = {"contrib_traffic": 30000.0, "contrib_conversion": 5000.0, "contrib_aov": -34000.0}
    ceil = efficiency_ceiling(bridge)
    assert ceil["ceiling_gmv"] == pytest.approx(34000.0)
    assert ceil["factors"] == ["客单价"]


def test_preship_recoverable_never_estimates_recovery_rate():
    pool = preship_recoverable({"pre_ship_refund_amount": 129019.0})
    assert pool["amount"] == pytest.approx(129019.0)
    assert pool["recovery_rate"] is None
    assert "发货前" in pool["caliber"]


def test_primitives_never_raise_on_none():
    # "pure and never raise" — a missing refund/bridge slice commonly surfaces as None.
    assert per_visitor_gmv(None, None) is None
    assert efficiency_ceiling(None) == {"ceiling_gmv": 0.0, "factors": [], "label": "上限（乐观估计）"}
    assert preship_recoverable(None)["amount"] is None
    assert preship_recoverable(None)["recovery_rate"] is None
