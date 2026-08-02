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


def test_gmv_chart_labels_round_money_to_whole_yuan():
    # The chart path shares the 过万用万 money rule (like table/prose); a GMV bar ≥1万
    # reads 80.0万 / 41.4万, never 800,357.48 with spurious cents (noise). Uses the
    # channel rank-bar chart, which labels every bar (unlike the trend line, which
    # labels only the last point).
    rows = [
        {"carrier_zh": "笔记", "gmv": 800357.48},
        {"carrier_zh": "商城", "gmv": 414126.02},
    ]
    finding = Finding(
        title="渠道结构",
        conclusion="c",
        evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=DescriptiveReliability.HIGH,
    )
    result = AnalysisResult(
        task_id="channel_structure_diagnosis",
        title="渠道结构",
        findings=[finding],
        tables={"channel_scale": rows},
    )
    svg = str(charts.for_result(result))
    assert "414,126.02" not in svg
    assert "800,357.48" not in svg
    assert "41.4万" in svg
    assert "80.0万" in svg
