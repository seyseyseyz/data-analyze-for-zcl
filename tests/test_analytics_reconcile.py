from xhs_ceramics_analytics.analytics.reconcile import (
    REFUND_RECONCILE_TOLERANCE,
    reconcile_net_gmv,
)


def test_reconcile_within_tolerance_returns_none():
    assert reconcile_net_gmv(1000.0, 100.0, 900.0) is None


def test_reconcile_beyond_tolerance_returns_caveat():
    caveat = reconcile_net_gmv(1000.0, 100.0, 500.0)
    assert caveat is not None and "退款后GMV" in caveat


def test_reconcile_missing_inputs_returns_none():
    assert reconcile_net_gmv(None, 100.0, 900.0) is None
    assert reconcile_net_gmv(0.0, 0.0, 0.0) is None


def test_tolerance_constant():
    assert REFUND_RECONCILE_TOLERANCE == 0.05
