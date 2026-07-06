"""强/中/弱 display tag from the two evidence axes + claim kind."""
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.trust_routing import confidence_tag


def test_mechanism_is_always_weak():
    # Even a "strong-looking" mechanism claim caps at 弱 on single-window data.
    assert confidence_tag(
        EvidenceStrength.STRONG, DescriptiveReliability.HIGH, "mechanism"
    ) == "弱"


def test_high_reliability_measurement_is_strong():
    assert confidence_tag(
        EvidenceStrength.WEAK, DescriptiveReliability.HIGH, "measurement"
    ) == "强"


def test_strong_evidence_measurement_is_strong():
    assert confidence_tag(
        EvidenceStrength.STRONG, DescriptiveReliability.MEDIUM, "sizing"
    ) == "强"


def test_medium_reliability_is_medium():
    assert confidence_tag(
        EvidenceStrength.WEAK, DescriptiveReliability.MEDIUM, "measurement"
    ) == "中"


def test_low_reliability_is_weak():
    assert confidence_tag(
        EvidenceStrength.WEAK, DescriptiveReliability.LOW, "measurement"
    ) == "弱"
