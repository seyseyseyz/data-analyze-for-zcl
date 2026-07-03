"""Refund-adjusted GMV and refund rates.

Used mainly as a cross-check: the 千帆 platform already ships ``net_gmv_pay``
(退款后支付金额) and ``refund_rate_pay`` (退款率（支付时间）) per SKU/day.
"""


def net_gmv(gmv: float | None, refund_amount: float | None) -> float | None:
    if gmv is None or refund_amount is None:
        return None
    return gmv - refund_amount


def refund_rate(refund_amount: float | None, gmv: float | None) -> float | None:
    if refund_amount is None or not gmv:
        return None
    return refund_amount / gmv


def refund_order_rate(
    refund_orders: float | None, paid_orders: float | None
) -> float | None:
    if refund_orders is None or not paid_orders:
        return None
    return refund_orders / paid_orders
