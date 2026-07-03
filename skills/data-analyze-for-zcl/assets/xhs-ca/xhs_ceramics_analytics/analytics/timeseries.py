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
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


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


def dow_seasonality(series: list[tuple[str, float]]) -> dict:
    """Mean value per weekday (parsed from the date). Unparseable dates are skipped.

    Returns {"by_weekday": {周一..周日: mean}, "peak_dow", "trough_dow"} or an
    empty dict when no date parses.
    """
    sums: dict[int, float] = {}
    counts: dict[int, int] = {}
    for raw, value in series:
        d = _parse_date(raw)
        if d is None:
            continue
        wd = d.weekday()
        sums[wd] = sums.get(wd, 0.0) + value
        counts[wd] = counts.get(wd, 0) + 1
    if not counts:
        return {}
    by_weekday = {_WEEKDAY_ZH[wd]: sums[wd] / counts[wd] for wd in sorted(counts)}
    peak = max(by_weekday, key=by_weekday.get)
    trough = min(by_weekday, key=by_weekday.get)
    return {"by_weekday": by_weekday, "peak_dow": peak, "trough_dow": trough}


def changepoint(values: list[float]) -> dict:
    """Largest mean-shift split: the index where before/after means differ most.

    Returns {"index", "before_mean", "after_mean", "shift"}; index is the first
    position of the *after* segment. Fewer than 4 points → {"index": None}.
    Observational — flags where the level moved, not why.
    """
    n = len(values)
    if n < 4:
        return {"index": None, "before_mean": None, "after_mean": None, "shift": None}
    best = {"index": None, "before_mean": None, "after_mean": None, "shift": -1.0}
    prefix = 0.0
    total = sum(values)
    for i in range(1, n):
        prefix += values[i - 1]
        before = prefix / i
        after = (total - prefix) / (n - i)
        shift = abs(after - before)
        if shift > best["shift"]:
            best = {
                "index": i,
                "before_mean": before,
                "after_mean": after,
                "shift": after - before,
            }
    return best
