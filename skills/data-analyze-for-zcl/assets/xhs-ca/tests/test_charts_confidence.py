"""A2: chart de-emphasis is driven by reader confidence, not causal strength.

Every real-data finding is causally WEAK (no controls), so keying greying off
EvidenceStrength faded every chart. These tests lock in that a large-sample,
descriptively-HIGH finding renders a normal (solid) chart, while a thin,
LOW-reliability one still de-emphasises.
"""
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting import charts


def _core_result(reliability: DescriptiveReliability) -> AnalysisResult:
    rows = [{"date": f"2026-04-{i + 1:02d}", "gmv": 1000 + i * 25} for i in range(6)]
    finding = Finding(
        title="GMV 趋势",
        conclusion="c",
        evidence_strength=EvidenceStrength.WEAK,  # causally weak, as all real data is
        descriptive_reliability=reliability,
    )
    return AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[finding],
        tables={"business_trend": rows},
    )


def test_large_sample_observational_chart_not_greyed():
    svg = str(charts.for_result(_core_result(DescriptiveReliability.HIGH)))
    assert svg  # a chart is produced
    assert "stroke-dasharray" not in svg  # WEAK+HIGH no longer renders as a "broken" dashed chart
    assert "url(#ca-hatch)" not in svg


def test_low_reliability_chart_still_de_emphasized():
    svg = str(charts.for_result(_core_result(DescriptiveReliability.LOW)))
    assert svg
    assert "stroke-dasharray" in svg  # thin data still visibly de-emphasised
