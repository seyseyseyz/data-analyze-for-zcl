"""Daily-series decomposition helpers — WoW, day-of-week, changepoint."""
from xhs_ceramics_analytics.analytics.timeseries import (
    anomaly_days,
    changepoint,
    changepoints,
    dow_seasonality,
    iso_date,
    iso_week,
    week_over_week,
    week_over_week_calendar,
)


def test_iso_week_keys_align_across_date_forms():
    # ISO / slash / integer YYYYMMDD all resolve to the same ISO-week bucket.
    assert iso_week("2026-04-06") == iso_week(20260406) == iso_week("2026/04/06")
    # 2026-04-06 is a Monday → ISO week 15; the following Sunday shares the bucket.
    assert iso_week("2026-04-06") == "2026-W15"
    assert iso_week("2026-04-12") == "2026-W15"
    assert iso_week("2026-04-13") == "2026-W16"


def test_iso_week_degrades_on_bad_input():
    assert iso_week(None) is None
    assert iso_week("not-a-date") is None


def test_iso_date_normalizes_across_forms():
    # int YYYYMMDD, ISO, and slash forms all map to the same canonical day key.
    assert iso_date(20260406) == iso_date("2026-04-06") == iso_date("2026/04/06")
    assert iso_date("2026-04-06") == "2026-04-06"


def test_iso_date_degrades_on_bad_input():
    assert iso_date(None) is None
    assert iso_date("not-a-date") is None


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


def test_changepoint_min_segment_excludes_single_point_tail():
    # A lone extreme final point must NOT become the changepoint (endpoint artifact).
    values = [10.0] * 20 + [1000.0]
    cp = changepoint(values)
    # With the default min-segment guard the after-segment must have >= 3 points,
    # so index cannot be the last position (n-1 = 20).
    assert cp["index"] is None or cp["index"] <= len(values) - 3


def test_changepoint_min_segment_none_when_too_short_for_two_segments():
    # 5 points with min_segment=3 cannot form two >=3 segments.
    assert changepoint([1.0, 2.0, 3.0, 4.0, 5.0], min_segment=3)["index"] is None


def test_parse_date_accepts_integer_yyyymmdd():
    # Real business_overview_daily dates arrive as integer YYYYMMDD, not ISO.
    series = [(20260406 + i, 10.0 if i % 7 < 5 else 1.0) for i in range(14)]
    result = dow_seasonality(series)
    # Previously integer dates were unparseable → {}; now they must yield weekdays.
    assert result != {}
    assert result["peak_dow"] in ("周一", "周二", "周三", "周四", "周五")


# --- A2: detrended day-of-week seasonality -----------------------------------
def test_dow_seasonality_detrends_before_weekday_means():
    # Strong upward trend PLUS a genuine Wednesday bump. Without detrending the
    # rising trend would make the latest weekday (whatever falls last) look peak;
    # detrending must recover Wednesday as the systematic high.
    # 2026-04-06 is a Monday; build 28 days with +2/day trend and +8 every Wed.
    series = []
    for i in range(28):
        day = 6 + i
        val = 1.0 + 2.0 * i  # steep trend
        if i % 7 == 2:  # Wednesday
            val += 8.0
        series.append((f"2026-04-{day:02d}" if day <= 30 else f"2026-05-{day - 30:02d}", val))
    result = dow_seasonality(series, detrend=True)
    assert result.get("detrended") is True
    assert result["peak_dow"] == "周三"


def test_dow_seasonality_short_series_falls_back_to_levels():
    # < 14 points: cannot reliably detrend, must degrade (not raise) and flag it.
    series = [(f"2026-04-{6 + i:02d}", float(i)) for i in range(7)]
    result = dow_seasonality(series, detrend=True)
    assert result == {} or result.get("detrended") is False


# --- A3: calendar-aligned week buckets ---------------------------------------
def test_week_over_week_calendar_aligns_to_iso_weeks():
    # 2026-04-06 is Monday. Two full ISO weeks Mon..Sun.
    series = [(f"2026-04-{6 + i:02d}", 1.0) for i in range(7)]  # ISO week A
    series += [(f"2026-04-{13 + i:02d}", 2.0) for i in range(7)]  # ISO week B
    weeks = week_over_week_calendar(series)
    assert len(weeks) == 2
    assert weeks[0]["days_in_bucket"] == 7
    assert weeks[0]["total"] == 7.0
    assert weeks[1]["total"] == 14.0
    assert weeks[1]["delta"] == 7.0
    assert weeks[0]["calendar_aligned"] is True


def test_week_over_week_calendar_handles_missing_days():
    # A week with only 4 present days must bucket by real ISO week, not row count.
    series = [
        ("2026-04-06", 1.0), ("2026-04-08", 1.0), ("2026-04-09", 1.0), ("2026-04-10", 1.0),
        ("2026-04-13", 5.0), ("2026-04-14", 5.0),
    ]
    weeks = week_over_week_calendar(series)
    assert weeks[0]["days_in_bucket"] == 4  # Mon,Wed,Thu,Fri of week A
    assert weeks[0]["total"] == 4.0
    assert weeks[1]["total"] == 10.0


def test_week_over_week_calendar_unparseable_falls_back():
    weeks = week_over_week_calendar([("bad", 1.0)] * 14)
    # No parseable dates → degrade to row-count bucketing, flagged.
    assert weeks == [] or weeks[0]["calendar_aligned"] is False


# --- A5: recursive multi-changepoint -----------------------------------------
def test_changepoints_detects_two_steps():
    # Up-plateau-down: 1→10 at idx 8, 10→1 at idx 16.
    values = [1.0] * 8 + [10.0] * 8 + [1.0] * 8
    cps = changepoints(values, max_k=3)
    assert len(cps) == 2
    idxs = sorted(c["index"] for c in cps)
    assert idxs[0] in (7, 8, 9)
    assert idxs[1] in (15, 16, 17)


def test_changepoints_constant_series_empty():
    assert changepoints([5.0] * 20) == []


def test_changepoints_respects_max_k():
    values = ([1.0] * 5 + [9.0] * 5) * 4  # many oscillations
    cps = changepoints(values, max_k=2)
    assert len(cps) <= 2


def test_changepoints_short_series_empty():
    assert changepoints([1.0, 2.0]) == []


# --- D1: ±2σ anomaly-day flags (detrended residual outliers) ------------------
def test_anomaly_days_flags_detrended_outlier():
    # A flat series with one spike on 2026-04-10: the spike is the only >2σ point.
    series = [(f"2026-04-{d:02d}", 100.0) for d in range(1, 21)]
    series[9] = ("2026-04-10", 400.0)  # index 9 → the 10th day, a large positive shock
    flags = anomaly_days(series, sigma=2.0)
    dates = {f["date"] for f in flags}
    assert "2026-04-10" in dates
    spike = next(f for f in flags if f["date"] == "2026-04-10")
    assert spike["direction"] == "高于预期"
    assert spike["z"] > 2.0


def test_anomaly_days_ignores_trend_no_false_positive():
    # A clean rising line has zero residual — no point should be flagged anomalous.
    series = [(f"2026-04-{d:02d}", float(d)) for d in range(1, 21)]
    assert anomaly_days(series, sigma=2.0) == []


def test_anomaly_days_detects_negative_shock_direction():
    series = [(f"2026-04-{d:02d}", 100.0) for d in range(1, 21)]
    series[5] = ("2026-04-06", 5.0)  # a sharp drop
    flags = anomaly_days(series, sigma=2.0)
    drop = next(f for f in flags if f["date"] == "2026-04-06")
    assert drop["direction"] == "低于预期"
    assert drop["z"] < -2.0


def test_anomaly_days_degrades_on_short_series():
    # Too few points to estimate a residual spread → no flags, never raises.
    assert anomaly_days([("2026-04-01", 1.0), ("2026-04-02", 9.0)]) == []


def test_anomaly_days_never_raises_on_dirty_input():
    assert anomaly_days([("bad", None), (None, 5.0), ("2026-04-01", 1.0)]) == []
    assert anomaly_days([]) == []
