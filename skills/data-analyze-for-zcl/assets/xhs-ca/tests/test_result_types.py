from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.evidence import EvidenceStrength


def test_finding_defaults_new_contract_fields_to_empty():
    finding = Finding(title="t", conclusion="c", evidence_strength=EvidenceStrength.WEAK)
    assert finding.confounders == []
    assert finding.next_test is None
    assert finding.appendix is None


def test_finding_accepts_full_contract():
    finding = Finding(
        title="t",
        conclusion="c",
        evidence_strength=EvidenceStrength.STRONG,
        confounders=["季节性需求上升"],
        next_test="下周只改文案角度做 A/B",
        appendix="口径：退款后GMV=支付时间口径",
    )
    assert finding.confounders == ["季节性需求上升"]
    assert finding.next_test.startswith("下周")


def test_analysis_result_carries_subsections_and_examples():
    sub = Subsection(title="买前确认区", body="高退款SKU", table_name="sku_performance")
    result = AnalysisResult(
        task_id="x",
        title="X",
        findings=[],
        subsections=[sub],
        named_examples=[{"label": "鱼盘12寸", "detail": "退款率偏高"}],
    )
    assert result.subsections[0].title == "买前确认区"
    assert result.subsections[0].findings == []
    assert result.named_examples[0]["label"] == "鱼盘12寸"
