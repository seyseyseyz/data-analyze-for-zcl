from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence


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


from xhs_ceramics_analytics.analysis.paid_traffic import classify_budget_action


def test_classify_budget_action_increase():
    assert classify_budget_action(200, 120, 1000, 5.0, 2) == "increase"


def test_classify_budget_action_reduce_for_spend_without_return():
    assert classify_budget_action(200, 10, 0, 0.0, 2) == "reduce"


def test_classify_budget_action_needs_data_without_clicks():
    assert classify_budget_action(200, None, None, None, 2) == "needs_data"


def test_classify_budget_action_hold_for_one_day_signal():
    assert classify_budget_action(200, 120, 1000, 5.0, 1) == "hold"
