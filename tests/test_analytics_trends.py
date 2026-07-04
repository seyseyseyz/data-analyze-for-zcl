from xhs_ceramics_analytics.analytics.trends import (
    direction_from_summary,
    direction_label,
    mom_change,
    pct_change,
    trend_extrapolation,
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


# --- A1: slope-significance gating (added, backward-compatible) ---------------
def test_trend_summary_exposes_significance_fields():
    strong = trend_summary([("d%d" % i, float(i)) for i in range(10)])
    assert strong["significant"] is True
    assert strong["t_stat"] is not None and abs(strong["t_stat"]) > 2
    assert strong["slope_se"] is not None
    # rel_slope is the whole-window relative change, dimension-free.
    assert strong["rel_slope"] is not None and strong["rel_slope"] > 0


def test_trend_summary_flat_noise_not_significant():
    values = [10.0, 9.8, 10.2, 9.9, 10.1, 10.0, 9.7, 10.3]
    summary = trend_summary([("d%d" % i, v) for i, v in enumerate(values)])
    # Tiny wobble around a flat mean must not read as a real trend.
    assert summary["significant"] is False


def test_trend_summary_short_series_significant_false():
    # Fewer than 3 points cannot support a residual-based t-test.
    assert trend_summary([("a", 1.0), ("b", 5.0)])["significant"] is False


def test_direction_from_summary_gates_on_significance():
    strong = trend_summary([("d%d" % i, float(i)) for i in range(10)])
    assert direction_from_summary(strong) == "上升"
    noisy_vals = [10.0, 9.8, 10.2, 9.9, 10.1, 10.0, 9.7, 10.3]
    noisy = trend_summary([("d%d" % i, v) for i, v in enumerate(noisy_vals)])
    assert direction_from_summary(noisy) == "趋势不明"
    falling = trend_summary([("d%d" % i, float(9 - i)) for i in range(10)])
    assert direction_from_summary(falling) == "下降"


def test_trend_summary_perfect_fit_no_zero_division():
    # Zero-residual perfect line: slope_se == 0 must not raise; treat as significant.
    summary = trend_summary([("d%d" % i, 2.0 * i) for i in range(6)])
    assert summary["significant"] is True


# --- D1: short-horizon trend extrapolation (observational hint, not a promise) -
def test_trend_extrapolation_projects_significant_upward_trend():
    series = [("d%d" % i, 100.0 + 10.0 * i) for i in range(10)]
    out = trend_extrapolation(series, horizon=3)
    assert out is not None
    # last value is 190; slope 10/step; 3 steps ahead → 220.
    assert out["projected_value"] == 220.0
    assert out["horizon"] == 3
    assert out["direction"] == "上升"


def test_trend_extrapolation_returns_none_when_trend_not_significant():
    noisy = [("d%d" % i, v) for i, v in enumerate([10.0, 9.8, 10.2, 9.9, 10.1, 10.0, 9.7, 10.3])]
    # A flat-but-wobbly series has no significant slope → no projection promised.
    assert trend_extrapolation(noisy) is None


def test_trend_extrapolation_short_series_none():
    assert trend_extrapolation([("a", 1.0), ("b", 5.0)]) is None
    assert trend_extrapolation([]) is None


def test_trend_extrapolation_non_negative_floor():
    # A steep decline projected forward can cross zero; non-negative floor clamps it.
    series = [("d%d" % i, 100.0 - 15.0 * i) for i in range(10)]  # 100..-35
    out = trend_extrapolation(series, horizon=5, non_negative=True)
    assert out is not None
    assert out["projected_value"] == 0.0
    assert out["direction"] == "下降"
