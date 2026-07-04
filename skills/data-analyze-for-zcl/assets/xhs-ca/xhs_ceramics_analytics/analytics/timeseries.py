"""Daily-series decomposition — turns a flat first-vs-last slope into structure.

91 daily points support week-over-week trend, day-of-week seasonality, and a
simple mean-shift changepoint. All observational: report direction and structure,
never p-values or causal claims. Pure stdlib — never raises on dirty dates or
short series; degrades to empty/None.
"""
from datetime import date, datetime

from xhs_ceramics_analytics.analytics.trends import direction_label, pct_change

_WEEKDAY_ZH = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _parse_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    # Real exports carry dates as integer YYYYMMDD (e.g. 20260401); accept that
    # alongside ISO so day-of-week seasonality and changepoint dates do not degrade.
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def iso_week(value) -> str | None:
    """ISO-week bucket key ``YYYY-Www`` for a date (int ``YYYYMMDD``, ISO, or
    ``datetime``). Shared calendar-week caliber so every module buckets identically.
    Returns ``None`` on missing/unparseable input; never raises."""
    parsed = _parse_date(value)
    if parsed is None:
        return None
    year, week, _ = parsed.isocalendar()
    return f"{year}-W{week:02d}"


def iso_date(value) -> str | None:
    """Canonical day key ``YYYY-MM-DD`` for a date (int ``YYYYMMDD``, ISO, slash, or
    ``datetime``). Shared day-level caliber so two tables with different date formats
    (e.g. calendar_events vs business_overview_daily) match on the same key. Returns
    ``None`` on missing/unparseable input; never raises."""
    parsed = _parse_date(value)
    return parsed.isoformat() if parsed is not None else None


def week_over_week(series: list[tuple[str, float]]) -> list[dict]:
    """Aggregate a date-sorted (date, value) series into 7-day buckets with WoW deltas.

    Buckets are consecutive 7-row windows over the sorted series (calendar gaps are
    ignored — buckets are by row count, robust to missing days). Fewer than 7 rows
    → empty list.
    """
    ordered = sorted(series, key=lambda t: str(t[0]))
    if len(ordered) < 7:
        return []
    buckets: list[dict] = []
    previous: float | None = None
    for start in range(0, len(ordered) - len(ordered) % 7, 7):
        window = ordered[start : start + 7]
        total = sum(v for _, v in window)
        delta = None if previous is None else total - previous
        buckets.append(
            {
                "week_start": str(window[0][0]),
                "week_end": str(window[-1][0]),
                "total": total,
                "delta": delta,
                "pct": None if previous is None else pct_change(previous, total),
                "direction": direction_label(delta),
            }
        )
        previous = total
    return buckets


_MIN_POINTS_FOR_DETREND = 14


def dow_seasonality(series: list[tuple[str, float]], detrend: bool = True) -> dict:
    """Weekday seasonality — mean *residual* per weekday after removing the trend.

    Reporting weekday means on raw levels lets an overall up/down trend leak in: on
    a rising series the latest weekday looks "peak" purely because of when it falls.
    With ``detrend=True`` (and ≥14 points) we subtract the OLS trend first, so a
    weekday is peak only if it is *systematically* high once the trend is removed.
    Series too short to detrend reliably fall back to raw levels (``detrended``:
    False). Unparseable dates are skipped; no parseable date → empty dict.

    Returns {"by_weekday", "peak_dow", "trough_dow", "detrended"} or {}.
    """
    dated = [(d, v) for raw, v in series if (d := _parse_date(raw)) is not None]
    if not dated:
        return {}
    detrended = detrend and len(dated) >= _MIN_POINTS_FOR_DETREND
    if detrended:
        ordered = sorted(dated, key=lambda t: t[0])
        residuals = _ols_residuals([v for _, v in ordered])
        points = [(d, r) for (d, _), r in zip(ordered, residuals)]
    else:
        points = dated
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for d, value in points:
        wd = d.weekday()
        sums[wd] = sums.get(wd, 0.0) + value
        counts[wd] = counts.get(wd, 0) + 1
    by_weekday = {_WEEKDAY_ZH[wd]: sums[wd] / counts[wd] for wd in sorted(counts)}
    peak = max(by_weekday, key=by_weekday.get)
    trough = min(by_weekday, key=by_weekday.get)
    return {
        "by_weekday": by_weekday,
        "peak_dow": peak,
        "trough_dow": trough,
        "detrended": detrended,
    }


def _ols_residuals(values: list[float]) -> list[float]:
    """Residuals of an OLS fit over the point index. Flat fit on degenerate input."""
    n = len(values)
    if n < 2:
        return list(values)
    mean_x = (n - 1) / 2.0
    mean_y = sum(values) / n
    var_x = sum((i - mean_x) ** 2 for i in range(n))
    if var_x <= 0:
        return [v - mean_y for v in values]
    slope = sum((i - mean_x) * (values[i] - mean_y) for i in range(n)) / var_x
    intercept = mean_y - slope * mean_x
    return [values[i] - (intercept + slope * i) for i in range(n)]


def week_over_week_calendar(series: list[tuple[str, float]]) -> list[dict]:
    """Bucket a (date, value) series by *real* ISO week (Mon–Sun), not row count.

    Row-count bucketing drifts whenever days are missing — a "week" stops being
    Monday–Sunday. Here each point falls into its ``date.isocalendar()`` (year,
    week); buckets are ordered chronologically with ``days_in_bucket`` reflecting
    gaps. If no date parses we degrade to the row-count :func:`week_over_week`
    (each row flagged ``calendar_aligned=False``) rather than returning nothing.
    """
    grouped: dict[tuple[int, int], list[tuple[object, float]]] = {}
    for raw, value in series:
        d = _parse_date(raw)
        if d is None:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        grouped.setdefault((iso_year, iso_week), []).append((d, value))
    if not grouped:
        fallback = week_over_week(series)
        for row in fallback:
            row["calendar_aligned"] = False
        return fallback
    buckets: list[dict] = []
    previous: float | None = None
    for (iso_year, iso_week) in sorted(grouped):
        points = sorted(grouped[(iso_year, iso_week)], key=lambda t: t[0])
        total = sum(v for _, v in points)
        delta = None if previous is None else total - previous
        buckets.append(
            {
                "iso_year": iso_year,
                "iso_week": iso_week,
                "week_start": str(points[0][0]),
                "week_end": str(points[-1][0]),
                "days_in_bucket": len(points),
                "total": total,
                "delta": delta,
                "pct": None if previous is None else pct_change(previous, total),
                "direction": direction_label(delta),
                "calendar_aligned": True,
            }
        )
        previous = total
    return buckets


_MIN_POINTS_FOR_ANOMALY = 7


def anomaly_days(series: list[tuple[str, float]], sigma: float = 2.0) -> list[dict]:
    """Flag days whose value deviates beyond ``±sigma`` of the detrended residual spread.

    Anomaly detection on raw levels lets a rising/falling trend leak in — the last days
    of an upward series would all look "high". Here we subtract the OLS trend first
    (shared :func:`_ols_residuals`), measure the residual standard deviation, and flag
    only points whose residual z-score exceeds ``±sigma``. This is an observational hint
    ("this day stands out"), not a causal or predictive claim — a flagged day usually
    reflects a promotion, stock-out, or data gap.

    Returns a date-sorted list of ``{date, value, residual, z, direction}`` where
    ``direction`` is 高于预期/低于预期. Degrades to ``[]`` when fewer than
    ``_MIN_POINTS_FOR_ANOMALY`` points parse or the residual spread is ~zero (a clean
    line has nothing anomalous). Unparseable dates/values are skipped; never raises.
    """
    dated = [
        (d, float(v))
        for raw, v in series
        if v is not None and (d := _parse_date(raw)) is not None
    ]
    if len(dated) < _MIN_POINTS_FOR_ANOMALY:
        return []
    ordered = sorted(dated, key=lambda t: t[0])
    residuals = _ols_residuals([v for _, v in ordered])
    n = len(residuals)
    mean_r = sum(residuals) / n
    var_r = sum((r - mean_r) ** 2 for r in residuals) / n
    std_r = var_r**0.5
    if std_r <= 1e-9:
        return []  # a clean trend/flat line — no residual spread to flag against
    flags: list[dict] = []
    for (d, value), residual in zip(ordered, residuals):
        z = (residual - mean_r) / std_r
        if abs(z) < sigma:
            continue
        flags.append(
            {
                "date": d.isoformat(),
                "value": value,
                "residual": residual,
                "z": z,
                "direction": "高于预期" if z > 0 else "低于预期",
            }
        )
    return flags


def changepoint(values: list[float], min_segment: int = 3) -> dict:
    """Largest mean-shift split: the index where before/after means differ most.

    Returns {"index", "before_mean", "after_mean", "shift"}; index is the first
    position of the *after* segment. Both segments must have at least
    ``min_segment`` points, so a lone extreme endpoint cannot masquerade as a
    structural break. Series too short to form two such segments → {"index": None}.
    Observational — flags where the level moved, not why.
    """
    # A segment must hold at least one point; clamp so a 0/negative caller can
    # never drive the ``prefix / i`` division below to a ZeroDivisionError.
    min_segment = max(1, min_segment)
    n = len(values)
    none_result = {"index": None, "before_mean": None, "after_mean": None, "shift": None}
    if n < 2 * min_segment:
        return none_result
    best = {"index": None, "before_mean": None, "after_mean": None, "shift": None}
    # Compare on the *magnitude* of the mean shift but store the signed value;
    # keeping these separate matters for monotonic-decreasing series, where a
    # signed sentinel would let every later index beat a negative running best.
    best_abs = -1.0
    total = sum(values)
    prefix = sum(values[:min_segment])
    for i in range(min_segment, n - min_segment + 1):
        before = prefix / i
        after = (total - prefix) / (n - i)
        magnitude = abs(after - before)
        if magnitude > best_abs:
            best_abs = magnitude
            best = {
                "index": i,
                "before_mean": before,
                "after_mean": after,
                "shift": after - before,
            }
        prefix += values[i]
    return best if best["index"] is not None else none_result


def changepoints(
    values: list[float],
    min_segment: int = 3,
    max_k: int = 3,
    min_rel_shift: float = 0.15,
) -> list[dict]:
    """Up to ``max_k`` mean-shift changepoints via recursive binary segmentation.

    A single-changepoint scan reports only the largest break; a 90-day series can
    hold several. This splits the largest break, then recurses into each side,
    accepting a break only when its shift is at least ``min_rel_shift`` of the
    series' overall level (so noise wiggles never register). Returns a
    position-sorted list of {index, before_mean, after_mean, shift, rel_shift};
    empty for constant or too-short series. Never raises.
    """
    n = len(values)
    if n < 2 * max(1, min_segment) or max_k <= 0:
        return []
    scale = abs(sum(values) / n) or 1.0
    found: list[dict] = []

    def _recurse(lo: int, hi: int) -> None:
        # Operate on the sub-window values[lo:hi]; require room for two segments.
        if len(found) >= max_k or (hi - lo) < 2 * min_segment:
            return
        cp = changepoint(values[lo:hi], min_segment=min_segment)
        idx = cp.get("index")
        if idx is None:
            return
        rel = abs(cp["shift"]) / scale
        if rel < min_rel_shift:
            return
        abs_idx = lo + idx
        found.append(
            {
                "index": abs_idx,
                "before_mean": cp["before_mean"],
                "after_mean": cp["after_mean"],
                "shift": cp["shift"],
                "rel_shift": rel,
            }
        )
        _recurse(lo, abs_idx)
        _recurse(abs_idx, hi)

    _recurse(0, n)
    return sorted(found, key=lambda c: c["index"])[:max_k]
