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


# 95% two-sided and 80% power normal quantiles, hardcoded (no scipy dependency).
_Z_ALPHA = 1.96
_Z_POWER = 0.84
_CMH_CHI2_CRIT = 3.841  # 1-dof chi-square at alpha=0.05


def stratified_two_proportion(strata: list[dict]) -> dict:
    """Cochran–Mantel–Haenszel test across strata — controls a confounder like time.

    A plain :func:`two_proportion` pools A vs B over the whole window; if the two
    groups' volumes concentrate in different periods, a time trend masquerades as a
    group effect (Simpson's paradox). Passing per-stratum counts (e.g. one dict per
    week: ``{k1, n1, k2, n2}``) tests the *within-stratum* gap and pools it fairly.

    Returns {pooled_diff, mh_chi2, significant, n_strata, ci_overlap}. Strata with a
    degenerate total (T ≤ 1) are skipped; no usable stratum → not significant. Never
    raises.
    """
    sum_a = sum_e = sum_v = 0.0
    diff_num = diff_den = 0.0
    used = 0
    for s in strata:
        n1 = float(s.get("n1", 0) or 0)
        n2 = float(s.get("n2", 0) or 0)
        k1 = min(max(float(s.get("k1", 0) or 0), 0.0), n1)
        k2 = min(max(float(s.get("k2", 0) or 0), 0.0), n2)
        total = n1 + n2
        if total <= 1 or n1 <= 0 or n2 <= 0:
            continue
        m1 = k1 + k2  # successes in stratum
        m2 = total - m1
        expected = n1 * m1 / total
        variance = (n1 * n2 * m1 * m2) / (total * total * (total - 1))
        sum_a += k1
        sum_e += expected
        sum_v += variance
        # Volume-weighted pooled difference (Mantel–Haenszel style weighting).
        weight = n1 * n2 / total
        diff_num += weight * (k1 / n1 - k2 / n2)
        diff_den += weight
        used += 1
    if used == 0 or sum_v <= 0:
        return {
            "pooled_diff": None, "mh_chi2": None,
            "significant": False, "n_strata": used, "ci_overlap": True,
        }
    # Continuity-corrected CMH statistic.
    mh_chi2 = (abs(sum_a - sum_e) - 0.5) ** 2 / sum_v
    pooled_diff = diff_num / diff_den if diff_den else None
    return {
        "pooled_diff": pooled_diff,
        "mh_chi2": mh_chi2,
        "significant": mh_chi2 >= _CMH_CHI2_CRIT,
        "n_strata": used,
        "ci_overlap": mh_chi2 < _CMH_CHI2_CRIT,
    }


def relative_lift(k1: float, n1: float, k2: float, n2: float) -> dict:
    """Relative lift p1/p2 − 1 with a conservative Wilson-based interval.

    Absolute differences hide scale (a 1pp gap is huge at a 1% base, trivial at
    50%). The interval combines the two rates' Wilson bounds at their worst-case
    corners, so it is deliberately wide but honest. None when either rate is
    undefined or the baseline p2 is zero.
    """
    if n1 <= 0 or n2 <= 0:
        return {"lift": None, "lift_ci_low": None, "lift_ci_high": None}
    k1 = min(max(k1, 0.0), n1)
    k2 = min(max(k2, 0.0), n2)
    p1, p2 = k1 / n1, k2 / n2
    if p2 <= 0:
        return {"lift": None, "lift_ci_low": None, "lift_ci_high": None}
    lo1, hi1 = wilson_interval(k1, n1)
    lo2, hi2 = wilson_interval(k2, n2)
    ci_low = (lo1 / hi2 - 1) if hi2 > 0 else None
    ci_high = (hi1 / lo2 - 1) if lo2 > 0 else None
    return {"lift": p1 / p2 - 1, "lift_ci_low": ci_low, "lift_ci_high": ci_high}


def min_detectable_effect(
    n1: float, n2: float, p_base: float, power: float = 0.8, alpha: float = 0.05
) -> float | None:
    """Smallest absolute rate gap a two-proportion test could detect at ``power``.

    Lets a "not significant" verdict be read correctly: a large MDE means the
    sample was simply too small to resolve a real difference, not that none exists.
    Normal approximation with fixed 95%/80% quantiles. None on degenerate input.
    """
    if n1 <= 0 or n2 <= 0 or not (0.0 < p_base < 1.0):
        return None
    if not (0.0 < power < 1.0) or not (0.0 < alpha < 1.0):
        return None
    se = math.sqrt(p_base * (1 - p_base) * (1 / n1 + 1 / n2))
    return (_Z_ALPHA + _Z_POWER) * se
