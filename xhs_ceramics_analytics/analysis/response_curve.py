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
              sku_id,
              COALESCE(SUM(
                CASE
                  WHEN date >= DATE '2026-06-01' AND date < DATE '2026-06-02'
                  THEN units
                  ELSE 0
                END
              ), 0.0) AS d0_1_units,
              COALESCE(SUM(
                CASE
                  WHEN date >= DATE '2026-06-02' AND date < DATE '2026-06-05'
                  THEN units
                  ELSE 0
                END
              ), 0.0) AS d1_3_units,
              COALESCE(SUM(
                CASE
                  WHEN date >= DATE '2026-06-05' AND date < DATE '2026-06-09'
                  THEN units
                  ELSE 0
                END
              ), 0.0) AS d4_7_units
            FROM daily_sku_sales
            GROUP BY sku_id
            ORDER BY sku_id
            """
        )
        columns = result.columns
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()

    return AnalysisResult(
        task_id="content_response_curve",
        title="Content Response Curve",
        findings=[
            Finding(
                title="SKU response windows",
                conclusion=(
                    "Calculated fixed response windows around 2026-06-01 "
                    f"for {len(rows)} SKUs."
                ),
                evidence_strength=EvidenceStrength.WEAK,
                key_numbers={"skus": len(rows)},
                caveats=[
                    "Response windows are descriptive and do not control for seasonality, "
                    "stockouts, or other marketing activity."
                ],
            )
        ],
        tables={"response_windows": rows},
    )
