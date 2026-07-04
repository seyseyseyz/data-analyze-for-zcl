"""GMV multiplicative attribution bridge (LMDI).

GMV = visitors × conversion × AOV. When GMV moves, the operator's first question
is *which lever* — traffic, conversion, or price. LMDI (Log-Mean Divisia Index)
splits ΔGMV into three **exactly additive** factor contributions (their sum equals
ΔGMV, no residual when all factors are positive), a deterministic decomposition
with no causal claim. Pure stdlib; missing/zero factors degrade to ``partial``.
"""
import math

from xhs_ceramics_analytics.analytics.numeric import is_finite_number, to_finite_float

_EPS = 1e-12
_FACTOR_ZH = {"traffic": "流量", "conversion": "转化", "aov": "客单价"}


def _factors(period: dict) -> tuple[float, float, float] | None:
    """Normalise a period dict to (visitors, conversion, aov).

    Accepts either explicit {visitors, conversion, aov} or {gmv, visitors, buyers}
    (conversion and aov reverse-derived). Non-finite/uncoercible cells and an
    under-specified period return None so the caller degrades to ``partial``.
    """
    if period is None:
        return None
    v = to_finite_float(period.get("visitors"))
    if v is None:
        return None
    conversion = to_finite_float(period.get("conversion"))
    aov = to_finite_float(period.get("aov"))
    if conversion is not None and aov is not None:
        return v, conversion, aov
    gmv = to_finite_float(period.get("gmv"))
    buyers = to_finite_float(period.get("buyers"))
    if gmv is not None and buyers is not None:
        conversion = (buyers / v) if v else 0.0
        aov = (gmv / buyers) if buyers else 0.0
        return v, conversion, aov
    return None


def _lmdi_weight(a: float, b: float) -> float:
    """Log-mean L(a,b) = (b-a)/(ln b - ln a); = a when a≈b."""
    if abs(a - b) < _EPS:
        return a
    return (b - a) / (math.log(b) - math.log(a))


def gmv_bridge(period_0: dict, period_1: dict) -> dict:
    """Decompose ΔGMV between two periods into traffic/conversion/AOV contributions.

    Returns {delta_gmv, contrib_traffic, contrib_conversion, contrib_aov, residual,
    dominant_factor, dominant_factor_zh, partial}. When any factor is missing or
    non-positive the log split is undefined → ``partial=True`` with the whole delta
    parked in ``residual``. Never raises.
    """
    f0 = _factors(period_0)
    f1 = _factors(period_1)
    partial_result = {
        "delta_gmv": None, "contrib_traffic": 0.0, "contrib_conversion": 0.0,
        "contrib_aov": 0.0, "residual": None, "dominant_factor": None,
        "dominant_factor_zh": None, "partial": True,
    }
    if f0 is None or f1 is None:
        return partial_result
    v0, c0, a0 = f0
    v1, c1, a1 = f1
    gmv0, gmv1 = v0 * c0 * a0, v1 * c1 * a1
    delta = gmv1 - gmv0
    # Any non-positive or non-finite factor makes ln() undefined — report a
    # partial bridge. A plain ``min(...) <= 0`` would let a NaN slip through
    # (``nan <= 0`` is False), so check finiteness AND positivity per factor.
    if not all(is_finite_number(x) and x > 0 for x in (v0, c0, a0, v1, c1, a1)):
        partial_result["delta_gmv"] = delta
        partial_result["residual"] = delta
        return partial_result
    weight = _lmdi_weight(gmv0, gmv1)
    contribs = {
        "traffic": weight * math.log(v1 / v0),
        "conversion": weight * math.log(c1 / c0),
        "aov": weight * math.log(a1 / a0),
    }
    residual = delta - sum(contribs.values())
    if abs(delta) < _EPS:
        dominant = None
    else:
        dominant = max(contribs, key=lambda k: abs(contribs[k]))
    return {
        "delta_gmv": delta,
        "contrib_traffic": contribs["traffic"],
        "contrib_conversion": contribs["conversion"],
        "contrib_aov": contribs["aov"],
        "residual": residual,
        "dominant_factor": dominant,
        "dominant_factor_zh": _FACTOR_ZH.get(dominant) if dominant else None,
        "partial": False,
    }


def gmv_bridge_series(periods: list[dict]) -> list[dict]:
    """Chain :func:`gmv_bridge` over adjacent periods. <2 periods → empty."""
    if len(periods) < 2:
        return []
    return [gmv_bridge(periods[i], periods[i + 1]) for i in range(len(periods) - 1)]
