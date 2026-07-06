import math

import pytest

from xhs_ceramics_analytics.analytics.confidence import (
    MIN_ORDERS_FOR_RATE,
    bounded_rate,
    mean_diff_test,
    min_detectable_effect,
    min_n_guard,
    rate_band,
    relative_lift,
    stratified_two_proportion,
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


def test_rate_band_adds_precision_when_whole_percent_collapses():
    # 0.078 and 0.083 both round to 8% — the old formatter printed a degenerate
    # "约 8%–8%". Adaptive precision must keep the two bounds distinguishable.
    band = rate_band(0.078, 0.083)
    assert band != "约 8%–8%"
    assert band == "约 7.8%–8.3%"


def test_rate_band_collapses_to_single_point_when_bounds_equal():
    # genuinely identical bounds (huge n) read as one value, not "约 8%–8%".
    assert rate_band(0.08, 0.08) == "约 8%"


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


def test_two_proportion_zero_se_reports_diff_but_no_significance():
    # Both rates are 0 → pooled SE is zero. The observed diff is still reported (0.0);
    # only the z test and significance null out. This pins the contract the docstring
    # describes (NOT "all-None", which only the non-positive-denominator case is).
    r = two_proportion(0, 100, 0, 50)
    assert r["diff"] == 0.0
    assert r["z"] is None
    assert r["significant"] is False


def test_mean_diff_zero_variance_reports_means_but_no_significance():
    # Both samples are constant → pooled SE is zero. The means and diff are observable
    # and reported; only t/df/CI/significance null out. Contrasts with the <2-value
    # case, which is the true all-None degradation.
    r = mean_diff_test([5.0, 5.0, 5.0], [3.0, 3.0, 3.0])
    assert r["diff"] == 2.0
    assert r["mean_a"] == 5.0 and r["mean_b"] == 3.0
    assert r["t"] is None and r["ci_low"] is None
    assert r["significant"] is False
    # The genuine all-None case:
    assert mean_diff_test([5.0], [3.0])["diff"] is None


def test_wilson_never_raises_when_k_exceeds_n():
    # k>n can arise when k and n come from different source columns or reverse
    # derivation; the helper must clamp instead of raising sqrt-of-negative.
    lo, hi = wilson_interval(5000, 100)
    assert 0.0 <= lo <= hi <= 1.0
    # Clamped to p=1.0, so the interval hugs the upper bound.
    assert hi == pytest.approx(1.0, abs=0.001)


def test_wilson_clamps_negative_k_to_zero():
    lo, hi = wilson_interval(-10, 100)
    assert lo == 0.0 and 0.0 <= hi < 1.0


def test_two_proportion_never_raises_when_k_exceeds_n():
    # Mixed-source numerators/denominators must not crash the whole report.
    r = two_proportion(5000, 100, 10, 200)
    assert set(r) == {"diff", "z", "significant", "ci_overlap"}
    assert r["diff"] is not None


def test_bounded_rate_passes_through_fraction():
    assert bounded_rate(0.5) == pytest.approx(0.5)
    assert bounded_rate(1.0) == pytest.approx(1.0)
    assert bounded_rate(0.0) == 0.0


def test_bounded_rate_normalises_percentage_to_fraction():
    assert bounded_rate(50) == pytest.approx(0.5)
    assert bounded_rate(3.5) == pytest.approx(0.035)


def test_bounded_rate_rejects_dirty_values():
    assert bounded_rate(None) is None
    assert bounded_rate(-0.1) is None
    assert bounded_rate(150) is None


# --- A4: stratified two-proportion (Cochran–Mantel–Haenszel) -----------------
def test_stratified_two_proportion_resists_simpson_reversal():
    # Each stratum has A ≈ B, but pooling makes A look far better because A's
    # denominators concentrate where the base rate is high. CMH must NOT flag it.
    strata = [
        {"k1": 90, "n1": 100, "k2": 9, "n2": 10},    # both ~0.90
        {"k1": 10, "n1": 100, "k2": 90, "n2": 1000},  # both ~0.10 / 0.09
    ]
    result = stratified_two_proportion(strata)
    assert result["n_strata"] == 2
    assert result["significant"] is False


def test_stratified_two_proportion_flags_consistent_gap():
    strata = [
        {"k1": 80, "n1": 100, "k2": 50, "n2": 100},
        {"k1": 82, "n1": 100, "k2": 48, "n2": 100},
    ]
    result = stratified_two_proportion(strata)
    assert result["significant"] is True
    assert result["pooled_diff"] > 0


def test_stratified_two_proportion_degrades_safely():
    assert stratified_two_proportion([])["significant"] is False
    # A degenerate single-row stratum (T-1 == 0) is skipped, never raises.
    assert stratified_two_proportion([{"k1": 1, "n1": 1, "k2": 0, "n2": 0}])["n_strata"] == 0


# --- A6: relative lift with CI + minimum detectable effect -------------------
def test_relative_lift_point_and_interval():
    lift = relative_lift(60, 100, 40, 100)  # 0.60 vs 0.40 → +50%
    assert lift["lift"] == pytest.approx(0.5, abs=0.001)
    assert lift["lift_ci_low"] < lift["lift"] < lift["lift_ci_high"]


def test_relative_lift_degrades_on_zero_denominator():
    assert relative_lift(1, 0, 1, 10)["lift"] is None
    assert relative_lift(1, 10, 0, 10)["lift"] is None  # divide by p2==0


def test_min_detectable_effect_shrinks_with_sample():
    small = min_detectable_effect(50, 50, 0.2)
    big = min_detectable_effect(5000, 5000, 0.2)
    assert small is not None and big is not None
    assert big < small


def test_min_detectable_effect_degrades():
    assert min_detectable_effect(0, 100, 0.2) is None
    assert min_detectable_effect(100, 100, 0.0) is None


def test_bounded_rate_coerces_percent_string_and_rejects_nan():
    assert bounded_rate("12%") == 0.12
    assert bounded_rate("0.2") == 0.2
    assert bounded_rate(float("nan")) is None
    assert bounded_rate("—") is None


def test_stratified_two_proportion_survives_nan_cells():
    result = stratified_two_proportion(
        [{"k1": float("nan"), "n1": 100, "k2": 10, "n2": 100},
         {"k1": 20, "n1": 100, "k2": 5, "n2": 100}]
    )
    # The NaN-poisoned stratum is skipped, the clean one is used — no NaN escapes.
    assert result["n_strata"] == 1
    assert result["mh_chi2"] is not None
    assert math.isfinite(result["mh_chi2"])
