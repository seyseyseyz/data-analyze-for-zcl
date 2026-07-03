"""Daily-series decomposition helpers — WoW, day-of-week, changepoint."""
from xhs_ceramics_analytics.analytics.timeseries import (
    changepoint,
    dow_seasonality,
    week_over_week,
)


def _dates(start_day: int, n: int) -> list[str]:
    return [f"2026-04-{start_day + i:02d}" for i in range(n)]


def test_week_over_week_buckets_and_delta():
    # 14 days: week1 sums to 7, week2 sums to 14 → +7 delta, 上升.
    series = [(d, 1.0) for d in _dates(1, 7)] + [(d, 2.0) for d in _dates(8, 7)]
    weeks = week_over_week(series)
    assert len(weeks) == 2
    assert weeks[0]["total"] == 7.0
    assert weeks[1]["total"] == 14.0
    assert weeks[1]["delta"] == 7.0
    assert weeks[1]["direction"] == "上升"
    assert weeks[0]["delta"] is None


def test_week_over_week_short_series_empty():
    assert week_over_week([("2026-04-01", 1.0), ("2026-04-02", 2.0)]) == []


def test_dow_seasonality_peak_and_trough():
    # 2026-04-06 is a Monday. Weekdays high (10), weekend low (1).
    series = []
    for i in range(14):
        d = f"2026-04-{6 + i:02d}"
        weekday = i % 7  # 0..6 starting Monday
        series.append((d, 1.0 if weekday >= 5 else 10.0))
    result = dow_seasonality(series)
    assert result["peak_dow"] in ("周一", "周二", "周三", "周四", "周五")
    assert result["trough_dow"] in ("周六", "周日")


def test_dow_seasonality_unparseable_dates_safe():
    assert dow_seasonality([("not-a-date", 5.0), ("also-bad", 3.0)]) == {}


def test_changepoint_detects_step():
    # Flat at 1.0 for 5 points, then jumps to 10.0 for 5 → shift near index 5.
    values = [1.0] * 5 + [10.0] * 5
    cp = changepoint(values)
    assert cp["index"] == 5
    assert cp["shift"] > 8.0
    assert cp["after_mean"] > cp["before_mean"]


def test_changepoint_short_series_none():
    assert changepoint([1.0, 2.0])["index"] is None
