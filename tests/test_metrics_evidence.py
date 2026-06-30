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
