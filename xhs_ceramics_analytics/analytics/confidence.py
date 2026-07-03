"""Honest small-sample confidence for observed rates.

Feeds ``evidence.py`` rather than duplicating its enum. Below
``MIN_ORDERS_FOR_RATE`` a rate is not judgable and should be left unranked.
"""
import math

MIN_ORDERS_FOR_RATE = 30


def wilson_interval(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))


def min_n_guard(n: float | None) -> bool:
    return n is not None and n >= MIN_ORDERS_FOR_RATE


def rate_band(lo: float, hi: float) -> str:
    return f"约 {round(lo * 100)}%–{round(hi * 100)}%"


def two_proportion(k1: float, n1: float, k2: float, n2: float) -> dict:
    """Two-proportion z-test (alpha=0.05) plus a Wilson-CI overlap flag.

    Observational comparison of two observed rates k1/n1 vs k2/n2. Reports the
    difference, the z statistic, whether it is significant, and whether the two
    Wilson intervals overlap. Not-judgable (all-None, not significant) when either
    denominator is non-positive or the pooled standard error is zero.
    """
    if n1 <= 0 or n2 <= 0:
        return {"diff": None, "z": None, "significant": False, "ci_overlap": True}
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = None if se == 0 else (p1 - p2) / se
    lo1, hi1 = wilson_interval(k1, n1)
    lo2, hi2 = wilson_interval(k2, n2)
    ci_overlap = not (hi1 < lo2 or hi2 < lo1)
    return {
        "diff": p1 - p2,
        "z": z,
        "significant": z is not None and abs(z) >= 1.96,
        "ci_overlap": ci_overlap,
    }
