from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength

TASK_ID = "audience_structure_diagnosis"
TITLE = "人群结构诊断"


def run(db_path: Path) -> AnalysisResult:
    """Scaffold placeholder — replaced by the full §6 implementation.

    See docs/superpowers/specs/2026-07-03-audience-structure-diagnosis-design.md.
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
