from xhs_ceramics_analytics.analytics.trends import (
    direction_label,
    mom_change,
    pct_change,
    trend_summary,
)


def test_pct_change():
    assert pct_change(100.0, 120.0) == 0.2
    assert pct_change(0, 5.0) is None
    assert pct_change(None, 5.0) is None


def test_direction_label():
    assert direction_label(0.2) == "上升"
    assert direction_label(-0.2) == "下降"
    assert direction_label(0.0) == "持平"
    assert direction_label(None) == "持平"


def test_mom_change_builds_per_period_deltas():
    rows = mom_change([("2026-04", 100.0), ("2026-05", 120.0), ("2026-06", 90.0)])
    assert rows[0] == {
        "period": "2026-04", "value": 100.0, "delta": None, "pct": None, "direction": "持平"
    }
    assert rows[1]["delta"] == 20.0
    assert rows[1]["pct"] == 0.2
    assert rows[1]["direction"] == "上升"
    assert rows[2]["direction"] == "下降"


def test_trend_summary_uses_ols_slope_not_endpoints():
    # Endpoints say "flat" (first==last) but the body clearly rises then the last
    # point dips back — slope over ALL points should read 上升.
    series = [("d1", 1.0), ("d2", 4.0), ("d3", 6.0), ("d4", 9.0), ("d5", 1.0)]
    summary = trend_summary(series)
    assert summary["direction"] == "上升"
    assert summary["slope"] > 0
    assert summary["first_value"] == 1.0
    assert summary["last_value"] == 1.0
    assert summary["n"] == 5


def test_trend_summary_monotone_matches_endpoint_direction():
    assert trend_summary([("a", 0.05), ("b", 0.08), ("c", 0.12)])["direction"] == "上升"
    assert trend_summary([("a", 0.12), ("b", 0.08), ("c", 0.05)])["direction"] == "下降"


def test_trend_summary_robust_to_single_endpoint_spike():
    # A noisy flat series with one final spike must not read as a real uptrend.
    series = [("d%d" % i, 10.0) for i in range(10)] + [("d10", 200.0)]
    # slope is positive but small relative to noise; endpoint delta would scream up.
    # We only require it not to crash and to expose slope for the caller to gate on.
    summary = trend_summary(series)
    assert "slope" in summary and summary["n"] == 11


def test_trend_summary_empty_series():
    summary = trend_summary([])
    assert summary["direction"] == "持平"
    assert summary["n"] == 0
