import pytest

from xhs_ceramics_analytics.analytics.confidence import (
    MIN_ORDERS_FOR_RATE,
    min_n_guard,
    rate_band,
    two_proportion,
    wilson_interval,
)


def test_wilson_known_value():
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=0.001)
    assert hi == pytest.approx(0.7634, abs=0.001)


def test_wilson_clamps_and_handles_zero_n():
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = wilson_interval(0, 5)
    assert lo == 0.0 and 0.0 < hi < 1.0


def test_min_n_guard():
    assert min_n_guard(MIN_ORDERS_FOR_RATE) is True
    assert min_n_guard(29) is False
    assert min_n_guard(None) is False


def test_rate_band_reads_as_percent_range():
    assert rate_band(0.2366, 0.7634) == "约 24%–76%"


def test_two_proportion_significant_non_overlapping():
    r = two_proportion(30, 100, 5, 100)
    assert r["diff"] == pytest.approx(0.25, abs=0.001)
    assert r["z"] == pytest.approx(4.65, abs=0.05)
    assert r["significant"] is True
    assert r["ci_overlap"] is False


def test_two_proportion_not_significant_overlapping():
    r = two_proportion(10, 100, 12, 100)
    assert r["significant"] is False
    assert r["ci_overlap"] is True


def test_two_proportion_guards_zero_n():
    r = two_proportion(0, 0, 5, 10)
    assert r == {"diff": None, "z": None, "significant": False, "ci_overlap": True}
