"""Concentration primitives — Gini, HHI, top-share, and their trend.

Pareto head-share answers "how much do the top few hold" but is not a single
comparable number and carries no time direction. Gini/HHI collapse a whole
distribution to one figure so "this month is more concentrated than last" becomes
checkable. Pure stdlib; negative, non-finite, or empty bases degrade to None.
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float


def _clean(values: list[float]) -> list[float]:
    """Drop None/non-finite entries; keeps NaN out of ``sorted`` (determinism)."""
    return [x for x in (to_finite_float(v) for v in values) if x is not None]


def gini(values: list[float]) -> float | None:
    """Gini coefficient (0 = perfectly even, →1 = one holder). None on bad input.

    Requires non-negative values with a positive total. A single element is fully
    even → 0.0.
    """
    clean = _clean(values)
    if not clean or any(v < 0 for v in clean):
        return None
    total = sum(clean)
    if total <= 0:
        return None
    if len(clean) == 1:
        return 0.0
    ordered = sorted(clean)
    n = len(ordered)
    weighted = sum((i + 1) * x for i, x in enumerate(ordered))
    return (2 * weighted - (n + 1) * total) / (n * total)


def hhi(values: list[float]) -> float | None:
    """Herfindahl–Hirschman index — Σ share² in [1/n, 1]. None on empty/zero total."""
    clean = _clean(values)
    if not clean or any(v < 0 for v in clean):
        return None
    total = sum(clean)
    if total <= 0:
        return None
    return sum((v / total) ** 2 for v in clean)


def top_share(values: list[float], k_frac: float = 0.2) -> float:
    """Share of the total held by the top ``k_frac`` of holders (Pareto head)."""
    clean = [v for v in _clean(values) if v >= 0]
    total = sum(clean)
    if not clean or total <= 0:
        return 0.0
    k = max(1, round(len(clean) * min(max(k_frac, 0.0), 1.0)))
    head = sum(sorted(clean, reverse=True)[:k])
    return head / total


def concentration_trend(period_to_values: dict) -> list[dict]:
    """Per-period Gini + HHI, chronologically ordered — is the mix concentrating?"""
    rows: list[dict] = []
    for period in sorted(period_to_values):
        vals = period_to_values[period]
        rows.append({"period": period, "gini": gini(vals), "hhi": hhi(vals)})
    return rows


def cumulative_curve(values: list[float]) -> list[dict]:
    """Descending Pareto curve: cumulative value share as holders join largest-first.

    Each row is ``{rank, cum_item_frac, cum_value_share}`` so a report can state
    "top X% of SKUs hold Y% of GMV". Drops None/non-finite entries; a negative
    entry makes the share base untrustworthy, so — like :func:`gini`/:func:`hhi` —
    the whole series is rejected (``[]``) rather than silently computed on a
    partial base. An empty or zero-total base also returns ``[]``. Deterministic:
    ties keep a stable descending order.
    """
    clean = _clean(values)
    if not clean or any(v < 0 for v in clean):
        return []
    total = sum(clean)
    if total <= 0:
        return []
    ordered = sorted(clean, reverse=True)
    n = len(ordered)
    rows: list[dict] = []
    running = 0.0
    for i, v in enumerate(ordered):
        running += v
        rows.append(
            {
                "rank": i + 1,
                "cum_item_frac": (i + 1) / n,
                "cum_value_share": running / total,
            }
        )
    return rows
