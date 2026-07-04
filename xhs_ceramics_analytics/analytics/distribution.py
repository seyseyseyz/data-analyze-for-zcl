"""Distribution shape primitives — quantiles, spread, histogram, bimodality.

A single mean hides structure: ceramics AOV is bimodal (cheap traffic-driver
pieces plus expensive gift sets), so the average lands in an empty valley. These
pure-stdlib helpers surface that shape. Never raise — degenerate input degrades
to None/empty.
"""
import math

from xhs_ceramics_analytics.analytics.numeric import to_finite_float


def _clean(values: list[float]) -> list[float]:
    """Drop None/non-finite entries so NaN never poisons stats or ``sorted`` order."""
    return [x for x in (to_finite_float(v) for v in values) if x is not None]


def quantiles(values: list[float], qs: tuple[float, ...] = (0.25, 0.5, 0.75)) -> dict:
    """Linear-interpolated quantiles. Empty input → each q maps to None."""
    clean = sorted(_clean(values))
    if not clean:
        return {q: None for q in qs}
    n = len(clean)
    out: dict[float, float] = {}
    for q in qs:
        if n == 1:
            out[q] = clean[0]
            continue
        pos = min(max(q, 0.0), 1.0) * (n - 1)
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            out[q] = clean[lo]
        else:
            frac = pos - lo
            out[q] = clean[lo] * (1 - frac) + clean[hi] * frac
    return out


def describe(values: list[float]) -> dict:
    """Summary stats with spread. Empty input → all-None (n=0). Never raises."""
    clean = _clean(values)
    n = len(clean)
    if n == 0:
        return {
            "n": 0, "mean": None, "median": None, "p25": None, "p75": None,
            "iqr": None, "min": None, "max": None, "cv": None,
        }
    mean = sum(clean) / n
    q = quantiles(clean, (0.25, 0.5, 0.75))
    p25, median, p75 = q[0.25], q[0.5], q[0.75]
    variance = sum((v - mean) ** 2 for v in clean) / n
    std = math.sqrt(variance)
    return {
        "n": n,
        "mean": mean,
        "median": median,
        "p25": p25,
        "p75": p75,
        "iqr": (p75 - p25) if (p25 is not None and p75 is not None) else None,
        "min": min(clean),
        "max": max(clean),
        "cv": (std / mean) if mean else None,
    }


def histogram(values: list[float], bins: object) -> list[dict]:
    """Counts per bin. ``bins`` is either an int (equal-width) or a list of left
    edges (last bin extends to +inf). Values below the first edge fall in bin 0.
    Empty values → bins with zero counts (or [] when no bins can be formed).
    """
    clean = _clean(values)
    edges = _resolve_edges(clean, bins)
    if not edges:
        return []
    rows: list[dict] = []
    total = len(clean)
    for i, lo in enumerate(edges):
        hi = edges[i + 1] if i + 1 < len(edges) else math.inf
        if i + 1 < len(edges):
            count = sum(1 for v in clean if lo <= v < hi)
        else:
            count = sum(1 for v in clean if v >= lo)
        rows.append(
            {
                "lo": lo,
                "hi": hi,
                "count": count,
                "share": (count / total) if total else 0.0,
            }
        )
    # Values below the first edge are folded into bin 0 so counts always sum to n.
    below = sum(1 for v in clean if v < edges[0])
    if below and rows:
        rows[0]["count"] += below
        if total:
            rows[0]["share"] = rows[0]["count"] / total
    return rows


def quantile_edges(values: list[float], n: int = 4) -> list[float]:
    """Left edges for ``n`` equal-count (quantile) bands — the shared price-band
    caliber. Returns ``[min, q_1/n, q_2/n, …, q_(n-1)/n]`` (``n`` left edges); feed
    directly to :func:`histogram` or classify with :func:`band_of`. Both use the
    same left-closed rule, so every consumer bands prices identically.

    Returns ``[]`` when fewer than ``n`` finite values exist (can't form ``n``
    bands). Edges are non-decreasing; ties (concentrated data) collapse a band to
    zero width rather than dropping it, so the band count is always exactly ``n``.
    """
    clean = sorted(_clean(values))
    if n < 1 or len(clean) < n:
        return []
    qs = tuple(i / n for i in range(1, n))
    cuts = quantiles(clean, qs)
    edges = [clean[0]] + [cuts[q] for q in qs]
    # Guard monotonicity: interpolated cuts are already sorted, but float noise or
    # a degenerate tail must never let a later edge dip below an earlier one.
    for i in range(1, len(edges)):
        if edges[i] < edges[i - 1]:
            edges[i] = edges[i - 1]
    return edges


def band_of(value: float, edges: list[float]) -> int | None:
    """Index of the band ``value`` falls in, using the same left-closed rule as
    :func:`histogram`: values below ``edges[0]`` fold into band 0, a value equal to
    an edge joins the upper band, and the top band is closed above (+inf). Returns
    ``None`` when ``edges`` is empty."""
    if not edges:
        return None
    v = float(value)
    idx = 0
    for i, edge in enumerate(edges):
        if v >= edge:
            idx = i
    return idx


def _resolve_edges(clean: list[float], bins: object) -> list[float]:
    if isinstance(bins, (list, tuple)):
        return [float(b) for b in bins]
    if isinstance(bins, int) and bins > 0 and clean:
        lo, hi = min(clean), max(clean)
        if hi <= lo:
            return [lo]
        width = (hi - lo) / bins
        return [lo + i * width for i in range(bins)]
    return []


def bimodality_coefficient(values: list[float]) -> float | None:
    """Sarle's bimodality coefficient (sample-corrected). > 0.555 hints multi-peak.

    b = (skew² + 1) / kurtosis, with the SAS sample corrections. Needs ≥4 points
    and non-zero variance; otherwise None.
    """
    clean = _clean(values)
    n = len(clean)
    if n < 4:
        return None
    mean = sum(clean) / n
    m2 = sum((v - mean) ** 2 for v in clean) / n
    if m2 <= 0:
        return None
    m3 = sum((v - mean) ** 3 for v in clean) / n
    m4 = sum((v - mean) ** 4 for v in clean) / n
    g1 = m3 / (m2 ** 1.5)
    g2 = m4 / (m2 ** 2) - 3.0
    skew = g1 * math.sqrt(n * (n - 1)) / (n - 2)
    kurt = ((n - 1) / ((n - 2) * (n - 3))) * ((n + 1) * g2 + 6)
    denom = kurt + 3.0 * ((n - 1) ** 2) / ((n - 2) * (n - 3))
    if denom == 0:
        return None
    return (skew ** 2 + 1.0) / denom
