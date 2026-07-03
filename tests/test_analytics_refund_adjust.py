from xhs_ceramics_analytics.analytics.refund_adjust import (
    net_gmv,
    refund_order_rate,
    refund_rate,
)


def test_net_gmv_subtracts_refund():
    assert net_gmv(1000.0, 150.0) == 850.0


def test_refund_rate_is_amount_over_gmv():
    assert refund_rate(150.0, 1000.0) == 0.15


def test_refund_order_rate():
    assert refund_order_rate(3, 20) == 0.15


def test_none_or_zero_denominator_returns_none():
    assert net_gmv(None, 10.0) is None
    assert refund_rate(10.0, 0) is None
    assert refund_rate(10.0, None) is None
    assert refund_order_rate(3, 0) is None
