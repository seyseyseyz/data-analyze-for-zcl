"""Money-sizing primitives — deterministic, caliber-honest, never over-claimed.

All three functions are pure and never raise. They encode the report's money
discipline: efficiency ratios use ``product_visitors`` only; the efficiency
"ceiling" is explicitly an optimistic upper bound (the two negative drags fully
reversed), never a forecast; the pre-ship refund pool is reported as a marginal
sum with NO recovery-rate estimate (the data has no basis for one).
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float

_FACTOR_ZH = {"conversion": "转化", "aov": "客单价"}


def per_visitor_gmv(gmv: object, product_visitors: object) -> float | None:
    """GMV per 商品访客 (the only efficiency caliber). None on non-positive/dirty UV."""
    g = to_finite_float(gmv)
    v = to_finite_float(product_visitors)
    if g is None or v is None or v <= 0:
        return None
    return g / v


def efficiency_ceiling(bridge: dict) -> dict:
    """Optimistic recoverable GMV = |negative conversion drag| + |negative AOV drag|.

    This is the sum of the two efficiency factors' *negative* contributions in the
    LMDI bridge — what GMV would return if both drags were fully reversed. It is an
    upper bound, labelled as such, never a projection.
    """
    bridge = bridge or {}
    total = 0.0
    factors: list[str] = []
    for key, zh in _FACTOR_ZH.items():
        contrib = to_finite_float(bridge.get(f"contrib_{key}"))
        if contrib is not None and contrib < 0:
            total += -contrib
            factors.append(zh)
    return {"ceiling_gmv": total, "factors": factors, "label": "上限（乐观估计）"}


def preship_recoverable(refund_row: dict) -> dict:
    """Pre-ship refund pool as a marginal sum. recovery_rate is ALWAYS None.

    The export has no cancel-reason or timing slice, so any recovery-rate estimate
    would be fabricated — we report the poolsize and explicitly decline to size the
    recoverable fraction.
    """
    amount = to_finite_float((refund_row or {}).get("pre_ship_refund_amount"))
    return {
        "amount": amount,
        "caliber": "发货前退款池（可拦截上限，恢复率未知、不估算）",
        "recovery_rate": None,
    }
