from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        result = con.sql(
            """
            SELECT
              note_id,
              reads,
              CASE WHEN impressions > 0 THEN reads * 1.0 / impressions END AS read_rate,
              CASE WHEN reads > 0 THEN likes * 1.0 / reads END AS like_rate,
              CASE WHEN reads > 0 THEN collects * 1.0 / reads END AS collect_rate,
              CASE WHEN reads > 0 THEN comments * 1.0 / reads END AS comment_rate
            FROM notes
            ORDER BY reads DESC
            """
        )
        columns = result.columns
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()
    return AnalysisResult(
        task_id="note_funnel",
        title="Note Funnel",
        findings=[
            Finding(
                title="Funnel metrics calculated",
                conclusion=(
                    "The skill calculated read, like, collect, and comment rates where "
                    "denominators exist."
                ),
                evidence_strength=(
                    EvidenceStrength.MEDIUM if rows else EvidenceStrength.NOT_JUDGABLE
                ),
                key_numbers={"notes": len(rows)},
                caveats=[],
            )
        ],
        tables={"note_funnel": rows},
    )
