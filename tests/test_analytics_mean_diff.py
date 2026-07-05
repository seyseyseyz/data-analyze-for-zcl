# tests/test_analytics_mean_diff.py
"""Welch's two-mean test — unequal-variance t plus a z-based CI on the difference."""
import pytest

from xhs_ceramics_analytics.analytics.confidence import mean_diff_test


def test_clear_difference_is_significant():
    # Tight, well-separated samples → large |t|, significant, CI excludes 0.
    a = [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.1, 9.9]
    b = [8.6, 8.8, 8.5, 8.7, 8.6, 8.5, 8.7, 8.6]
    r = mean_diff_test(a, b)
    assert r["diff"] == pytest.approx(1.375, abs=0.05)
    assert r["significant"] is True
    assert r["ci_low"] > 0 and r["ci_high"] > 0


def test_overlapping_samples_not_significant():
    a = [10.0, 8.0, 12.0, 9.0, 11.0]
    b = [10.5, 8.5, 11.5, 9.5, 10.0]
    r = mean_diff_test(a, b)
    assert r["significant"] is False
    assert r["ci_low"] < 0 < r["ci_high"]


def test_degrades_on_thin_or_dirty_input():
    assert mean_diff_test([1.0], [2.0, 3.0]) == {
        "mean_a": None, "mean_b": None, "diff": None, "t": None,
        "df": None, "significant": False, "ci_low": None, "ci_high": None,
    }
    # NaN/inf dropped, not propagated.
    r = mean_diff_test([10.0, float("nan"), 10.0, 10.0], [8.0, 8.0, float("inf"), 8.0])
    assert r["diff"] == pytest.approx(2.0, abs=1e-9)


def test_zero_variance_zero_se_degrades():
    # Both samples constant and equal → SE 0 → not judgable, never divides by zero.
    r = mean_diff_test([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
    assert r["significant"] is False
    assert r["t"] is None
