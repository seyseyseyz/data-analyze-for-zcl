"""Honest small-sample confidence for observed rates.

Feeds ``evidence.py`` rather than duplicating its enum. Below
``MIN_ORDERS_FOR_RATE`` a rate is not judgable and should be left unranked.
"""
import math

MIN_ORDERS_FOR_RATE = 30


def wilson_interval(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    # Defensive clamp: k and n may come from different source columns or from
    # reverse-derivation, so k>n (p>1 → sqrt of negative) is reachable. Clamp
    # k into [0, n] so p stays a valid probability — never raise on dirty data.
    k = min(max(k, 0.0), n)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))


def min_n_guard(n: float | None) -> bool:
    return n is not None and n >= MIN_ORDERS_FOR_RATE


def rate_band(lo: float, hi: float) -> str:
    return f"约 {round(lo * 100)}%–{round(hi * 100)}%"


def bounded_rate(r: float | None) -> float | None:
    """Normalise a stored rate to a fraction in [0, 1], or None if uninterpretable.

    Exports mix conventions: some rate columns are fractions (0.12), others are
    percentages (12.0). Treat values in (1, 100] as percentages and divide by
    100; reject negatives and anything still above 1 (e.g. 150) as dirty. A bare
    1.0 is read as 100% (fraction convention), matching the rest of the pipeline.
    """
    if r is None:
        return None
    r = float(r)
    if r < 0:
        return None
    if r > 1:
        r = r / 100
    if r > 1:
        return None
    return r


def two_proportion(k1: float, n1: float, k2: float, n2: float) -> dict:
    """Two-proportion z-test (alpha=0.05) plus a Wilson-CI overlap flag.

    Observational comparison of two observed rates k1/n1 vs k2/n2. Reports the
    difference, the z statistic, whether it is significant, and whether the two
    Wilson intervals overlap. Not-judgable (all-None, not significant) when either
    denominator is non-positive or the pooled standard error is zero.
    """
    if n1 <= 0 or n2 <= 0:
        return {"diff": None, "z": None, "significant": False, "ci_overlap": True}
    # Clamp each numerator into [0, n] so pooled proportion stays in [0, 1];
    # mixed-source k/n must never crash the report (sqrt-of-negative guard).
    k1 = min(max(k1, 0.0), n1)
    k2 = min(max(k2, 0.0), n2)
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
