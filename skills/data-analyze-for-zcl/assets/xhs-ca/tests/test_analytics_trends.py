from xhs_ceramics_analytics.analytics.trends import direction_label, mom_change, pct_change


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
