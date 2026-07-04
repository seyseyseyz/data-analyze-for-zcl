"""Posting-cadence primitives — which publish window performs best, net of drift.

A note published earlier in the window has accumulated reads/engagement for longer,
so a raw weekday×slot mean confounds *timing quality* with *note age*. These pure,
never-raise primitives optionally remove a linear age trend before grouping, and
guard every bucket with a minimum sample count so a single lucky post never crowns
a window. No numpy/pandas — stdlib only.
"""
import math

_EPS = 1e-9


def posting_windows(
    observations,
    min_n: int = 3,
    detrend: bool = True,
) -> list[dict]:
    """Mean performance per publish window, best-first, net of a linear age trend.

    ``observations``: iterable of ``(group, order, value)`` where ``group`` is any
    hashable window key (e.g. ``(weekday, slot)``), ``order`` is a monotonic recency
    index (publish day number) used *only* for detrending, and ``value`` is the
    performance metric. Observations with a non-finite ``value`` are dropped. When
    ``detrend`` is set and there are ≥3 points spanning ≥2 distinct finite orders,
    each value is replaced by its residual from an OLS fit ``value ~ order`` with the
    grand mean added back, so the level stays interpretable while the age drift is
    removed. Groups with fewer than ``min_n`` observations are omitted.

    Returns ``list[dict]`` with ``group`` / ``n`` / ``mean`` / ``lift`` (group mean
    minus the grand mean), sorted by ``mean`` descending then by ``group``. Never
    raises; returns ``[]`` on empty or all-invalid input.
    """
    clean = [
        (group, order, float(value))
        for group, order, value in observations
        if group is not None and _is_finite(value)
    ]
    if not clean:
        return []

    adjusted = _detrend(clean) if detrend else [(g, v) for g, _, v in clean]
    if not adjusted:
        return []

    buckets: dict = {}
    for group, value in adjusted:
        buckets.setdefault(group, []).append(value)

    # Baseline is the average over *qualified* windows only — a sparse, dropped
    # bucket (e.g. one lucky viral post) must not skew what "typical" looks like.
    qualified = {g: v for g, v in buckets.items() if len(v) >= min_n}
    pooled = [value for values in qualified.values() for value in values]
    if not pooled:
        return []
    grand_mean = sum(pooled) / len(pooled)

    rows = [
        {
            "group": group,
            "n": len(values),
            "mean": sum(values) / len(values),
            "lift": sum(values) / len(values) - grand_mean,
        }
        for group, values in qualified.items()
    ]
    rows.sort(key=lambda r: (-r["mean"], _sort_key(r["group"])))
    return rows


def _detrend(clean: list[tuple]) -> list[tuple]:
    """Replace each value with its OLS residual against ``order`` (grand mean added
    back). Points with non-finite order keep their raw value; degrades to raw values
    when fewer than 3 points or fewer than 2 distinct orders are available."""
    fit_points = [(order, value) for _, order, value in clean if _is_finite(order)]
    slope_intercept = _ols(fit_points)
    if slope_intercept is None:
        return [(g, v) for g, _, v in clean]
    slope, intercept, grand_mean = slope_intercept
    result = []
    for group, order, value in clean:
        if _is_finite(order):
            result.append((group, value - (intercept + slope * order) + grand_mean))
        else:
            result.append((group, value))
    return result


def _ols(points: list[tuple]) -> tuple | None:
    """Ordinary least-squares ``value ~ order``. Returns ``(slope, intercept,
    grand_mean)`` or ``None`` when the fit is undefined (too few points or no spread
    in ``order``)."""
    n = len(points)
    if n < 3:
        return None
    mean_x = sum(x for x, _ in points) / n
    mean_y = sum(y for _, y in points) / n
    var_x = sum((x - mean_x) ** 2 for x, _ in points)
    if var_x <= _EPS:
        return None
    cov = sum((x - mean_x) * (y - mean_y) for x, y in points)
    slope = cov / var_x
    intercept = mean_y - slope * mean_x
    return slope, intercept, mean_y


def _sort_key(group):
    """Stable, type-safe secondary sort key for arbitrary hashable group keys."""
    return str(group)


def _is_finite(value) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)
