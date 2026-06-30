from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        result = con.sql(
            """
            WITH sku_sales AS (
              SELECT
                s.sku_id,
                s.sku_name,
                COALESCE(SUM(d.units), 0) AS units,
                COALESCE(SUM(d.gmv), 0) AS gmv
              FROM skus s
              LEFT JOIN daily_sku_sales d USING(sku_id)
              GROUP BY 1, 2
            )
            SELECT
              sku_id,
              sku_name,
              units,
              gmv,
              CASE
                WHEN units >= 3 THEN 'sales_response_present'
                ELSE 'needs_more_content_or_data'
              END AS opportunity_type
            FROM sku_sales
            ORDER BY gmv DESC NULLS LAST
            """
        )
        columns = result.columns
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()

    return AnalysisResult(
        task_id="product_opportunity_matrix",
        title="Product Opportunity Matrix",
        findings=[
            Finding(
                title="SKU opportunities ranked",
                conclusion=(
                    "The task ranked SKUs by sales response and flagged initial "
                    "opportunity types."
                ),
                evidence_strength=(
                    EvidenceStrength.MEDIUM if rows else EvidenceStrength.NOT_JUDGABLE
                ),
                key_numbers={"sku_count": len(rows)},
                caveats=[
                    "Content performance quadrants become stronger after note-SKU "
                    "links are available."
                ],
            )
        ],
        tables={"product_opportunities": rows},
    )
