"""投放弹性 / 花费—回报响应曲线原语.

Cross-sectional spend→GMV response: quantile-bin objects by spend (shared
``distribution`` caliber), then measure how incremental GMV per incremental spend
(marginal ROAS) changes as spend rises. A declining marginal ROAS across
ascending spend bins is the diminishing-returns signature; the *saturation point*
is the first bin whose marginal ROAS falls below break-even (1.0) — beyond it an
extra yuan of spend returns less than a yuan of GMV.

This is observational and cross-object: objects differ in intrinsic quality, so a
declining curve is an *association*, not a within-object dose response. It exists
to replace hand-set ROAS thresholds with a data-driven turning point, but does not
license causal claims. Pure, stdlib-only, never-raise — no numpy/pandas.
"""
from xhs_ceramics_analytics.analytics.distribution import band_of, quantile_edges

# Marginal ROAS below this means the last increment of spend lost money.
BREAK_EVEN_ROAS = 1.0


def spend_response_curve(observations, bins: int = 4) -> list[dict]:
    """Quantile-binned spend→GMV response curve with per-bin marginal ROAS.

    ``observations``: iterable of ``(spend, gmv)``. Rows with non-finite or
    non-positive spend, or missing values, are dropped. Objects are quantile-binned
    by spend using the shared ``quantile_edges``/``band_of`` caliber; each populated
    bin reports pooled totals, average ROAS, and the *marginal* ROAS =
    ``Δavg_gmv / Δavg_spend`` versus the previous populated bin's centroid (``None``
    for the first bin). Returns ``[]`` when fewer than ``bins`` finite spend values
    exist. Never raises.
    """
    clean = [
        (float(s), float(g))
        for s, g in observations
        if s is not None
        and g is not None
        and _is_finite(s)
        and _is_finite(g)
        and float(s) > 0.0
    ]
    spends = [s for s, _ in clean]
    edges = quantile_edges(spends, bins)
    if not edges:
        return []

    buckets = {i: {"n": 0, "spend": 0.0, "gmv": 0.0} for i in range(bins)}
    for spend, gmv in clean:
        idx = band_of(spend, edges)
        if idx is None:
            continue
        bucket = buckets[idx]
        bucket["n"] += 1
        bucket["spend"] += spend
        bucket["gmv"] += gmv

    curve: list[dict] = []
    prev: dict | None = None
    for i in range(bins):
        bucket = buckets[i]
        if bucket["n"] == 0:
            continue  # empty quantile bin (ties collapsed a band) — skip, don't fake it
        avg_spend = bucket["spend"] / bucket["n"]
        avg_gmv = bucket["gmv"] / bucket["n"]
        avg_roas = (bucket["gmv"] / bucket["spend"]) if bucket["spend"] else None
        marginal = None
        if prev is not None:
            d_spend = avg_spend - prev["avg_spend"]
            if d_spend > 0:
                marginal = (avg_gmv - prev["avg_gmv"]) / d_spend
        row = {
            "bin": i,
            "n": bucket["n"],
            "avg_spend": avg_spend,
            "avg_gmv": avg_gmv,
            "avg_roas": avg_roas,
            "marginal_roas": marginal,
        }
        curve.append(row)
        prev = row
    return curve


def saturation_point(curve: list[dict]) -> dict:
    """Locate the diminishing-returns turning point on a ``spend_response_curve``.

    Returns ``{saturation_bin, break_even_spend, diminishing}``:
    - ``saturation_bin``: index of the first bin whose marginal ROAS drops below
      :data:`BREAK_EVEN_ROAS` (extra spend stops paying back), else ``None``.
    - ``break_even_spend``: that bin's average spend, else ``None``.
    - ``diminishing``: ``True`` when the last measurable marginal ROAS is below the
      first (the curve bends down), ``None`` when fewer than two marginals exist.
    """
    marginals = [
        (r["bin"], r["marginal_roas"], r["avg_spend"])
        for r in curve
        if r.get("marginal_roas") is not None
    ]
    saturation_bin = None
    break_even_spend = None
    for bin_i, marginal, avg_spend in marginals:
        if marginal < BREAK_EVEN_ROAS:
            saturation_bin = bin_i
            break_even_spend = avg_spend
            break

    diminishing = None
    if len(marginals) >= 2:
        diminishing = marginals[-1][1] < marginals[0][1]

    return {
        "saturation_bin": saturation_bin,
        "break_even_spend": break_even_spend,
        "diminishing": diminishing,
    }


def _is_finite(value) -> bool:
    return value == value and value not in (float("inf"), float("-inf"))
