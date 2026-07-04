"""Distribution primitives — quantiles, describe, histogram, bimodality."""
import pytest

from xhs_ceramics_analytics.analytics.distribution import (
    band_of,
    bimodality_coefficient,
    describe,
    histogram,
    quantile_edges,
    quantiles,
)


def test_quantiles_linear_interpolation():
    q = quantiles([1.0, 2.0, 3.0, 4.0], (0.25, 0.5, 0.75))
    assert q[0.5] == pytest.approx(2.5)
    assert q[0.25] == pytest.approx(1.75)
    assert q[0.75] == pytest.approx(3.25)


def test_quantiles_empty_safe():
    assert quantiles([], (0.5,)) == {0.5: None}


def test_describe_reports_spread():
    d = describe([10.0, 20.0, 30.0, 40.0, 50.0])
    assert d["n"] == 5
    assert d["mean"] == pytest.approx(30.0)
    assert d["median"] == pytest.approx(30.0)
    assert d["min"] == 10.0 and d["max"] == 50.0
    assert d["iqr"] == pytest.approx(d["p75"] - d["p25"])
    assert d["cv"] is not None and d["cv"] > 0


def test_describe_empty_all_none():
    d = describe([])
    assert d["n"] == 0
    assert d["mean"] is None and d["median"] is None and d["cv"] is None


def test_histogram_fixed_edges_price_bands():
    values = [10.0, 40.0, 60.0, 150.0, 500.0]
    bins = histogram(values, [0, 50, 100, 200])  # last bin is [200, +inf)
    assert len(bins) == 4
    assert bins[0]["count"] == 2  # 10, 40
    assert bins[1]["count"] == 1  # 60
    assert bins[-1]["count"] == 1  # 500
    assert sum(b["count"] for b in bins) == 5
    assert bins[0]["share"] == pytest.approx(0.4)


def test_histogram_int_bins_equal_width():
    bins = histogram([0.0, 1.0, 2.0, 3.0, 4.0], 2)
    assert len(bins) == 2
    assert sum(b["count"] for b in bins) == 5


def test_histogram_empty_safe():
    assert histogram([], [0, 10]) == [] or all(b["count"] == 0 for b in histogram([], [0, 10]))


def test_bimodality_flags_two_peaks():
    # Two well-separated clusters → Sarle's coefficient above the 0.555 threshold.
    bimodal = [1.0] * 20 + [100.0] * 20
    assert bimodality_coefficient(bimodal) > 0.555


def test_bimodality_unimodal_below_threshold():
    # Roughly bell-shaped, single peak.
    unimodal = [5, 6, 6, 7, 7, 7, 8, 8, 8, 8, 9, 9, 9, 10, 10, 11]
    b = bimodality_coefficient([float(v) for v in unimodal])
    assert b is not None and b < 0.555


def test_bimodality_degrades_on_constant_or_empty():
    assert bimodality_coefficient([]) is None
    assert bimodality_coefficient([5.0, 5.0, 5.0]) is None  # zero variance


# ---- quantile_edges / band_of: shared price-band caliber --------------------


def test_quantile_edges_four_equal_count_bands():
    # 8 evenly spaced values → 4 quartile bands. First edge is the min; the three
    # interior edges are the 25/50/75 quantile cut points.
    values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    edges = quantile_edges(values, 4)
    assert len(edges) == 4
    assert edges[0] == 10.0  # min is the first left edge
    # Edges are non-decreasing so histogram bins never invert.
    assert edges == sorted(edges)


def test_quantile_edges_insufficient_values_returns_empty():
    # Fewer than n usable values → cannot form n bands.
    assert quantile_edges([5.0, 6.0], 4) == []
    assert quantile_edges([], 4) == []


def test_quantile_edges_and_histogram_are_one_caliber():
    # The whole point of the shared caliber: feeding quantile_edges into histogram
    # produces exactly n bands whose counts sum to the sample size.
    values = [float(v) for v in range(1, 101)]
    edges = quantile_edges(values, 4)
    bins = histogram(values, edges)
    assert len(bins) == 4
    assert sum(b["count"] for b in bins) == 100


def test_band_of_left_closed_matches_histogram():
    edges = [0.0, 50.0, 100.0, 200.0]
    assert band_of(-5.0, edges) == 0   # below first edge folds into bin 0
    assert band_of(0.0, edges) == 0
    assert band_of(49.9, edges) == 0
    assert band_of(50.0, edges) == 1   # left-closed: equal to edge → upper band
    assert band_of(150.0, edges) == 2
    assert band_of(200.0, edges) == 3  # top band closed above (+inf)
    assert band_of(9999.0, edges) == 3


def test_band_of_empty_edges_returns_none():
    assert band_of(10.0, []) is None


def test_describe_and_quantiles_drop_nan_instead_of_poisoning():
    stats = describe([1.0, 2.0, 3.0, float("nan")])
    assert stats["mean"] == 2.0
    q = quantiles([3.0, 1.0, float("nan"), 2.0])
    assert q[0.5] == 2.0
