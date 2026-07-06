"""Non-additive recoverable ledger — parallel pools, deliberately no net total.

Different recoverable pools (发货前退款, 误拍退款, 退货退款 …) overlap and use
incompatible calibers, so summing them into a single "net recoverable" would
double-count with no ground truth for the overlap. This ledger lists them
side by side, sorted by size, with a controllability column and a banner that
states the sum is not meaningful. ``net_total`` is always ``None`` by contract.
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float

_BANNER = "各池口径不同，不可相加为单一净额"


def non_additive_ledger(pools: list[dict]) -> dict:
    """Sort pools by amount desc; drop dirty amounts; never compute a net total."""
    rows = []
    for pool in pools or []:
        if not isinstance(pool, dict):
            continue
        amount = to_finite_float(pool.get("amount"))
        if amount is None:
            continue
        rows.append(
            {
                "name": pool.get("name"),
                "amount": amount,
                "controllability": pool.get("controllability"),
            }
        )
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return {"rows": rows, "net_total": None, "banner": _BANNER}
