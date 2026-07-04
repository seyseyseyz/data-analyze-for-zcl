"""GMV multiplicative attribution bridge — LMDI decomposition."""
import pytest

from xhs_ceramics_analytics.analytics.decomposition import gmv_bridge, gmv_bridge_series


def _period(visitors, conversion, aov):
    return {"visitors": visitors, "conversion": conversion, "aov": aov}


def test_gmv_bridge_contributions_sum_to_delta():
    # GMV = visitors * conversion * aov.
    p0 = _period(1000.0, 0.10, 200.0)   # GMV = 20000
    p1 = _period(1200.0, 0.12, 210.0)   # GMV = 30240
    bridge = gmv_bridge(p0, p1)
    total = (
        bridge["contrib_traffic"]
        + bridge["contrib_conversion"]
        + bridge["contrib_aov"]
    )
    assert bridge["delta_gmv"] == pytest.approx(30240.0 - 20000.0, abs=1e-6)
    assert total == pytest.approx(bridge["delta_gmv"], abs=1e-6)
    assert abs(bridge["residual"]) < 1e-6


def test_gmv_bridge_identifies_dominant_factor():
    # Only traffic moves; it must be the dominant factor and own ~all of ΔGMV.
    p0 = _period(1000.0, 0.10, 200.0)
    p1 = _period(2000.0, 0.10, 200.0)
    bridge = gmv_bridge(p0, p1)
    assert bridge["dominant_factor"] == "traffic"
    assert bridge["contrib_traffic"] == pytest.approx(bridge["delta_gmv"], abs=1e-6)
    assert bridge["contrib_conversion"] == pytest.approx(0.0, abs=1e-6)


def test_gmv_bridge_derives_factors_from_gmv_visitors_buyers():
    # Alternate input form: conversion/aov reverse-derived from gmv/visitors/buyers.
    p0 = {"gmv": 20000.0, "visitors": 1000.0, "buyers": 100.0}
    p1 = {"gmv": 30240.0, "visitors": 1200.0, "buyers": 144.0}
    bridge = gmv_bridge(p0, p1)
    total = (
        bridge["contrib_traffic"]
        + bridge["contrib_conversion"]
        + bridge["contrib_aov"]
    )
    assert total == pytest.approx(bridge["delta_gmv"], abs=1e-3)


def test_gmv_bridge_no_change_is_all_zero():
    p = _period(1000.0, 0.10, 200.0)
    bridge = gmv_bridge(p, p)
    assert bridge["delta_gmv"] == pytest.approx(0.0)
    assert bridge["contrib_traffic"] == pytest.approx(0.0)
    assert bridge["dominant_factor"] is None


def test_gmv_bridge_partial_on_missing_factor():
    # A zero/absent factor cannot be log-decomposed → partial, never raises.
    p0 = _period(0.0, 0.10, 200.0)
    p1 = _period(1000.0, 0.12, 210.0)
    bridge = gmv_bridge(p0, p1)
    assert bridge["partial"] is True


def test_gmv_bridge_series_chains_adjacent_periods():
    periods = [
        _period(1000.0, 0.10, 200.0),
        _period(1100.0, 0.11, 205.0),
        _period(1200.0, 0.12, 210.0),
    ]
    steps = gmv_bridge_series(periods)
    assert len(steps) == 2
    for step in steps:
        total = step["contrib_traffic"] + step["contrib_conversion"] + step["contrib_aov"]
        assert total == pytest.approx(step["delta_gmv"], abs=1e-6)


def test_gmv_bridge_series_short_input():
    assert gmv_bridge_series([]) == []
    assert gmv_bridge_series([_period(1.0, 0.1, 10.0)]) == []
