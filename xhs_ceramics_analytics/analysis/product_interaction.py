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
              f.composition_type,
              f.copy_angle,
              COUNT(*) AS notes,
              AVG(n.reads) AS avg_reads,
              AVG(n.collects) AS avg_collects
            FROM content_features f
            JOIN notes n USING(note_id)
            GROUP BY 1, 2
            ORDER BY avg_reads DESC
            """
        )
        columns = result.columns
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()

    return AnalysisResult(
        task_id="product_content_interaction",
        title="Product and Content Interaction",
        findings=[
            Finding(
                title="Content combinations ranked",
                conclusion=(
                    "The task compared cover and copy combinations as an initial "
                    "interaction view."
                ),
                evidence_strength=EvidenceStrength.WEAK,
                key_numbers={"combinations": len(rows)},
                caveats=[
                    "Product joins need explicit note-SKU links for stronger "
                    "interaction evidence."
                ],
            )
        ],
        tables={"product_interactions": rows},
    )
