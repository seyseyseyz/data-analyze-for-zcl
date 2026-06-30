from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        result = con.sql(
            """
            SELECT
              f.copy_angle,
              COUNT(*) AS notes,
              AVG(n.reads) AS avg_reads,
              AVG(n.collects) AS avg_collects
            FROM content_features f
            JOIN notes n USING(note_id)
            GROUP BY 1
            ORDER BY avg_collects DESC
            """
        )
        columns = result.columns
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()

    return AnalysisResult(
        task_id="copy_angle_effect",
        title="Copy Angle Effect",
        findings=[
            Finding(
                title="Copy angles ranked",
                conclusion=(
                    "Copy angle groups were ranked by average reads and collects."
                ),
                evidence_strength=score_evidence(
                    len(rows), has_controls=False, confounder_count=1
                ),
                key_numbers={"copy_groups": len(rows)},
                caveats=[
                    "This ranking is descriptive until product and timing controls "
                    "are added."
                ],
            )
        ],
        tables={"copy_effects": rows},
    )
