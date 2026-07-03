from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength

TASK_ID = "search_efficiency_diagnosis"
TITLE = "搜索效率诊断"


def run(db_path: Path) -> AnalysisResult:
    """Scaffold placeholder — replaced by the full §5 implementation.

    See docs/superpowers/specs/2026-07-03-search-efficiency-diagnosis-design.md.
    """
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=[
            Finding(
                title=f"{TITLE}（待实现）",
                conclusion="模块脚手架已就位，完整诊断实现中。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            )
        ],
    )
