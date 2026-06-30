from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.html import render_html
from xhs_ceramics_analytics.reporting.markdown import render_markdown


def test_render_markdown_uses_chinese_report_labels():
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
    assert "# 小红书陶瓷账号分析报告" in report
    assert "证据强度：强" in report
    assert "关键数字：" in report
    assert "建议动作：" in report
    assert "表格 `table_count`: 0 行" not in report
    assert "Evidence:" not in report
    assert "Proceed with analysis." in report


def test_render_html_escapes_unsafe_markdown_content():
    html = render_html(
        [
            AnalysisResult(
                task_id="unsafe_content",
                title="Unsafe Content",
                findings=[
                    Finding(
                        title="Escaped content",
                        conclusion="<script>alert(1)</script>",
                        evidence_strength=EvidenceStrength.WEAK,
                    )
                ],
            )
        ]
    )

    assert "<!doctype html>" in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
