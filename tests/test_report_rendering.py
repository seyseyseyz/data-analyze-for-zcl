from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.markdown import render_markdown


def test_render_markdown_includes_evidence_strength():
    report = render_markdown(
        [
            AnalysisResult(
                task_id="data_quality_check",
                title="Data Quality Check",
                findings=[
                    Finding(
                        title="Imported tables are available",
                        conclusion="Detected standard tables.",
                        evidence_strength=EvidenceStrength.STRONG,
                        key_numbers={"table_count": 7},
                        caveats=[],
                        recommended_action="Proceed with analysis.",
                    )
                ],
            )
        ]
    )
    assert "# Xiaohongshu Ceramics Analytics Report" in report
    assert "Evidence: strong" in report
    assert "Proceed with analysis." in report
