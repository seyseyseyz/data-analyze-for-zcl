import pytest

from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.contracts.finding_contract import assert_finding_contract
from xhs_ceramics_analytics.evidence import EvidenceStrength


def test_strong_without_confounders_raises():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.STRONG,
        next_test="下周A/B",
    )
    with pytest.raises(ValueError, match="confounders"):
        assert_finding_contract(finding)


def test_medium_without_next_test_raises():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.MEDIUM,
        confounders=["季节性"],
    )
    with pytest.raises(ValueError, match="next_test"):
        assert_finding_contract(finding)


def test_strong_with_full_contract_passes():
    finding = Finding(
        title="t", conclusion="c", evidence_strength=EvidenceStrength.STRONG,
        confounders=["季节性"], next_test="下周A/B",
    )
    assert assert_finding_contract(finding) is None


def test_weak_is_exempt():
    finding = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK)
    assert assert_finding_contract(finding) is None
