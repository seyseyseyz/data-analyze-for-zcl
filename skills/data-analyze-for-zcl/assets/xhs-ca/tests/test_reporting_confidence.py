from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.confidence import reader_confidence
from xhs_ceramics_analytics.reporting.domains import APPENDIX_DOMAIN_INTRO
from xhs_ceramics_analytics.reporting.formatting import field_label


def _finding(strength, reliability):
    return Finding(
        title="t",
        conclusion="c",
        evidence_strength=strength,
        descriptive_reliability=reliability,
    )


def test_large_sample_observational_reads_high_not_low():
    # The real-data default: causal WEAK but descriptively HIGH → 商家看到"高".
    rc = reader_confidence(_finding(EvidenceStrength.WEAK, DescriptiveReliability.HIGH))
    assert rc.level == "high"
    assert rc.label == "高"
    assert rc.de_emphasize is False
    # 因果口径作为脚注保留,不作为主标签.
    assert rc.causal_caveat is not None


def test_low_reliability_de_emphasizes():
    rc = reader_confidence(_finding(EvidenceStrength.WEAK, DescriptiveReliability.LOW))
    assert rc.level == "low"
    assert rc.de_emphasize is True


def test_medium_reliability_reads_medium():
    rc = reader_confidence(_finding(EvidenceStrength.WEAK, DescriptiveReliability.MEDIUM))
    assert rc.level == "medium"
    assert rc.de_emphasize is False


def test_not_judgable_stays_not_judgable():
    rc = reader_confidence(_finding(EvidenceStrength.NOT_JUDGABLE, None))
    assert rc.level == "not_judgable"
    assert rc.label == "暂不下定论"
    assert rc.de_emphasize is True
    assert rc.causal_caveat is None


def test_falls_back_to_softened_evidence_when_no_reliability():
    # 未评描述精度时,不该恒为低.
    rc = reader_confidence(_finding(EvidenceStrength.MEDIUM, None))
    assert rc.level == "medium"
    assert rc.de_emphasize is False


def test_not_applicable_reliability_falls_back_to_evidence():
    rc = reader_confidence(
        _finding(EvidenceStrength.WEAK, DescriptiveReliability.NOT_APPLICABLE)
    )
    assert rc.level == "low"


def test_appendix_intro_uses_unified_confidence_word():
    # The appendix says it annotates every conclusion with a confidence rating —
    # that rating IS the folded 置信度, so the prose must not reintroduce 可信度.
    assert "置信度" in APPENDIX_DOMAIN_INTRO
    assert "可信度" not in APPENDIX_DOMAIN_INTRO


def test_evidence_strength_column_labelled_as_raw_causal_axis():
    # The evidence_strength column carries the RAW causal tier (强/中/弱), not the
    # folded reader 置信度. Its label must name the causal axis honestly and never
    # collide with either the retired 可信度 or the folded 置信度 vocabulary.
    label = field_label("evidence_strength")
    assert label == "证据强度"
    assert "可信度" not in label
