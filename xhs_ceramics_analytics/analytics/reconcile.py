"""Cross-check the platform-given net GMV against gmv - refund_amount."""
from xhs_ceramics_analytics.analytics.refund_adjust import net_gmv

REFUND_RECONCILE_TOLERANCE = 0.05


def reconcile_net_gmv(
    gmv: float | None,
    refund_amount: float | None,
    net_gmv_pay: float | None,
    tolerance: float = REFUND_RECONCILE_TOLERANCE,
) -> str | None:
    computed = net_gmv(gmv, refund_amount)
    if computed is None or net_gmv_pay is None or not gmv:
        return None
    if abs(computed - net_gmv_pay) / gmv <= tolerance:
        return None
    return (
        f"退款后GMV 对不上：平台值 {net_gmv_pay:.0f} 与 支付金额-退款金额 "
        f"{computed:.0f} 相差超过 {tolerance:.0%}，请核对退款口径。"
    )
