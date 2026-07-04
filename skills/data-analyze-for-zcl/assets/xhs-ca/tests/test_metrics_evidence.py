from xhs_ceramics_analytics.analysis.paid_traffic import classify_budget_action
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import (
    DescriptiveReliability,
    EvidenceStrength,
    score_evidence,
    score_reliability,
)


def test_score_evidence_strong():
    assert (
        score_evidence(sample_size=40, has_controls=True, confounder_count=0)
        == EvidenceStrength.STRONG
    )


def test_score_evidence_medium():
    assert (
        score_evidence(sample_size=15, has_controls=True, confounder_count=1)
        == EvidenceStrength.MEDIUM
    )


def test_score_evidence_weak_for_inferred_small_sample():
    assert (
        score_evidence(sample_size=3, has_controls=False, confounder_count=2)
        == EvidenceStrength.WEAK
    )


def test_score_evidence_not_judgable_for_zero_sample():
    assert (
        score_evidence(sample_size=0, has_controls=True, confounder_count=0)
        == EvidenceStrength.NOT_JUDGABLE
    )


def test_score_evidence_medium_at_minimum_sample_without_controls():
    assert (
        score_evidence(sample_size=10, has_controls=False, confounder_count=1)
        == EvidenceStrength.WEAK
    )


def test_score_evidence_strong_at_minimum_sample():
    assert (
        score_evidence(sample_size=30, has_controls=True, confounder_count=0)
        == EvidenceStrength.STRONG
    )


def test_score_evidence_not_judgable_for_negative_confounders():
    assert (
        score_evidence(sample_size=10, has_controls=True, confounder_count=-1)
        == EvidenceStrength.NOT_JUDGABLE
    )


# --- descriptive reliability: orthogonal to causal strength ---------------
# The causal axis (score_evidence) caps observational findings at WEAK no matter
# how much data backs them. That mislabels a large-n, tight-CI description as if
# it were a hunch. score_reliability answers the *other* question — how precisely
# is this quantity pinned down for the period described — driven by n + CI width.


def test_reliability_high_for_large_n_tight_ci():
    # 7181 orders, refund rate CI 15.2%–16.9% (±<1pp) → a precise description.
    assert (
        score_reliability(sample_size=7181, ci_low=0.152, ci_high=0.169)
        == DescriptiveReliability.HIGH
    )


def test_reliability_low_for_small_n_wide_ci():
    assert (
        score_reliability(sample_size=12, ci_low=0.05, ci_high=0.55)
        == DescriptiveReliability.LOW
    )


def test_reliability_low_when_ci_wide_despite_large_n():
    # Big denominator but a rare event → still an imprecise rate.
    assert (
        score_reliability(sample_size=5000, ci_low=0.01, ci_high=0.45)
        == DescriptiveReliability.LOW
    )


def test_reliability_falls_back_to_volume_without_ci():
    assert score_reliability(sample_size=250) == DescriptiveReliability.HIGH
    assert score_reliability(sample_size=45) == DescriptiveReliability.MEDIUM
    assert score_reliability(sample_size=8) == DescriptiveReliability.LOW


def test_reliability_not_applicable_without_sample():
    assert score_reliability(sample_size=0) == DescriptiveReliability.NOT_APPLICABLE
    assert score_reliability(sample_size=None) == DescriptiveReliability.NOT_APPLICABLE


def test_reliability_is_orthogonal_to_causal_strength():
    # Same finding: causal evidence WEAK (no controls) yet description HIGH reliability.
    causal = score_evidence(sample_size=7181, has_controls=False, confounder_count=1)
    reliability = score_reliability(sample_size=7181, ci_low=0.152, ci_high=0.169)
    assert causal == EvidenceStrength.WEAK
    assert reliability == DescriptiveReliability.HIGH


def test_finding_carries_descriptive_reliability_defaulting_none():
    bare = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK)
    assert bare.descriptive_reliability is None
    scored = Finding(
        title="t",
        conclusion="c",
        evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=DescriptiveReliability.HIGH,
    )
    assert scored.descriptive_reliability == DescriptiveReliability.HIGH


def test_finding_default_mutable_fields_are_isolated():
    first = Finding(
        title="first",
        conclusion="one",
        evidence_strength=EvidenceStrength.WEAK,
    )
    second = Finding(
        title="second",
        conclusion="two",
        evidence_strength=EvidenceStrength.WEAK,
    )

    first.key_numbers["sample_size"] = 3
    first.caveats.append("small sample")

    assert second.key_numbers == {}
    assert second.caveats == []


def test_analysis_result_default_mutable_fields_are_isolated():
    first = AnalysisResult(task_id="one", title="First", findings=[])
    second = AnalysisResult(task_id="two", title="Second", findings=[])

    first.tables["summary"] = [{"count": 1}]
    first.limitations.append("limited data")

    assert second.tables == {}
    assert second.limitations == []


def test_classify_budget_action_increase():
    assert classify_budget_action(200, 120, 1000, 5.0, 2) == "increase"


def test_classify_budget_action_reduce_for_spend_without_return():
    assert classify_budget_action(200, 10, 0, 0.0, 2) == "reduce"


def test_classify_budget_action_needs_data_without_clicks():
    assert classify_budget_action(200, None, None, None, 2) == "needs_data"


def test_classify_budget_action_hold_for_one_day_signal():
    assert classify_budget_action(200, 120, 1000, 5.0, 1) == "hold"
