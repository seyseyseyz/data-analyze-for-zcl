from xhs_ceramics_analytics.analytics.elasticity import (
    saturation_point,
    spend_response_curve,
)


def _objects():
    """16 objects across 4 spend quantile bins; ROAS falls as spend rises so the
    response curve saturates (marginal ROAS crosses below break-even in bin 2)."""
    plan = [
        (25.0, 5.0),    # low spend, high ROAS
        (115.0, 3.0),
        (315.0, 1.5),
        (1015.0, 0.8),  # high spend, below-break-even ROAS
    ]
    obs = []
    for base_spend, roas in plan:
        for offset in (0.0, 10.0, 20.0, 30.0):
            spend = base_spend + offset
            obs.append((spend, spend * roas))
    return obs


def test_spend_response_curve_bins_and_marginal_roas():
    curve = spend_response_curve(_objects(), bins=4)
    assert len(curve) == 4
    assert [r["bin"] for r in curve] == [0, 1, 2, 3]
    assert all(r["n"] == 4 for r in curve)
    # first bin has no predecessor → no marginal
    assert curve[0]["marginal_roas"] is None
    # average ROAS falls monotonically across ascending spend bins
    roas_seq = [r["avg_roas"] for r in curve]
    assert roas_seq == sorted(roas_seq, reverse=True)
    # marginal ROAS declines and eventually drops below break-even
    assert curve[1]["marginal_roas"] > 1.0
    assert curve[2]["marginal_roas"] < 1.0


def test_saturation_point_flags_diminishing_returns():
    curve = spend_response_curve(_objects(), bins=4)
    sat = saturation_point(curve)
    assert sat["saturation_bin"] == 2
    assert sat["break_even_spend"] is not None
    assert sat["diminishing"] is True


def test_no_saturation_when_returns_stay_above_break_even():
    # ROAS constant at 4 everywhere → marginal stays well above 1, never saturates.
    obs = [(s, s * 4.0) for s in (10, 20, 30, 40, 100, 110, 120, 130,
                                  300, 310, 320, 330, 1000, 1010, 1020, 1030)]
    curve = spend_response_curve(obs, bins=4)
    sat = saturation_point(curve)
    assert sat["saturation_bin"] is None


def test_degrades_on_too_few_objects():
    assert spend_response_curve([(100.0, 300.0), (200.0, 400.0)], bins=4) == []
    assert saturation_point([]) == {
        "saturation_bin": None,
        "break_even_spend": None,
        "diminishing": None,
    }


def test_ignores_non_finite_and_nonpositive_spend():
    obs = _objects() + [
        (float("nan"), 100.0),
        (float("inf"), 100.0),
        (0.0, 50.0),
        (-10.0, 50.0),
        (None, 100.0),
        (100.0, None),
    ]
    curve = spend_response_curve(obs, bins=4)
    # dirty rows dropped → same clean 16-object binning
    assert sum(r["n"] for r in curve) == 16
