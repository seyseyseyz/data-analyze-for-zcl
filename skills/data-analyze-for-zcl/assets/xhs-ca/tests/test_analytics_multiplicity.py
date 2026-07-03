"""BH-FDR + one-sided binomial helpers — small-sample honesty for outlier scans."""
from xhs_ceramics_analytics.analytics.multiplicity import (
    benjamini_hochberg,
    expected_false_positives,
    one_sided_binomial_p,
)


def test_bh_textbook_example():
    # Classic BH example: sorted p-values with a clear cut.
    pvals = [0.001, 0.008, 0.039, 0.041, 0.9]
    survived = benjamini_hochberg(pvals, alpha=0.05)
    # p<=(k/5)*0.05: ranks 1..4 clear (0.001<=.01, .008<=.02, .039<=.03? no).
    # rank3: .039<=.03 false; rank4: .041<=.04 false -> max_rank from rank2=.008<=.02,
    # but rank1 .001<=.01 true. Largest k satisfying: rank2 (.008<=.02) -> survivors 1..2.
    assert survived == [True, True, False, False, False]


def test_bh_all_insignificant():
    assert benjamini_hochberg([0.9, 0.8, 1.0], alpha=0.05) == [False, False, False]


def test_bh_handles_none_and_empty():
    assert benjamini_hochberg([], alpha=0.05) == []
    out = benjamini_hochberg([0.001, None, 0.002], alpha=0.05)
    assert out[1] is False
    assert out[0] is True and out[2] is True


def test_bh_preserves_input_order():
    # Unsorted input; survivors must map back to original positions.
    pvals = [0.9, 0.001, 0.8, 0.002]
    survived = benjamini_hochberg(pvals, alpha=0.05)
    assert survived == [False, True, False, True]


def test_one_sided_binomial_monotonic_in_k():
    # More successes over the same n → smaller upper-tail p (stronger evidence).
    p_low = one_sided_binomial_p(15, 100, 0.10)
    p_high = one_sided_binomial_p(30, 100, 0.10)
    assert p_high < p_low
    assert 0.0 <= p_high <= 1.0 and 0.0 <= p_low <= 1.0


def test_one_sided_binomial_below_baseline_is_one():
    # Observed at/below H0 proportion → no upper-tail evidence.
    assert one_sided_binomial_p(5, 100, 0.10) == 1.0
    assert one_sided_binomial_p(10, 100, 0.10) == 1.0


def test_one_sided_binomial_degenerate_inputs_safe():
    assert one_sided_binomial_p(5, 0, 0.1) == 1.0
    assert one_sided_binomial_p(5, 10, 0.0) == 1.0
    assert one_sided_binomial_p(5, 10, 1.0) == 1.0


def test_expected_false_positives():
    assert expected_false_positives(100, 0.05) == 5.0
    assert expected_false_positives(0, 0.05) == 0.0
