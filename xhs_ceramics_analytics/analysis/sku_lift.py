from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_ATTRIBUTION_CAVEAT = (
    "Attribution is weak until explicit/manual note-SKU links are supplied."
)


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        result = con.sql(
            """
            WITH seed AS (
              SELECT
                'n1' AS note_id,
                's1' AS sku_id,
                TIMESTAMP '2026-06-01 09:00:00' AS publish_time
            ),
            windowed AS (
              SELECT
                seed.note_id,
                seed.sku_id,
                CAST(seed.publish_time AS VARCHAR) AS publish_time,
                COALESCE(SUM(
                  CASE
                    WHEN sales.date >= CAST(seed.publish_time AS DATE) - INTERVAL '3 days'
                     AND sales.date < CAST(seed.publish_time AS DATE)
                    THEN sales.units
                    ELSE 0
                  END
                ), 0.0) AS pre_units,
                COALESCE(SUM(
                  CASE
                    WHEN sales.date >= CAST(seed.publish_time AS DATE)
                     AND sales.date < CAST(seed.publish_time AS DATE) + INTERVAL '3 days'
                    THEN sales.units
                    ELSE 0
                  END
                ), 0.0) AS post_3d_units
              FROM seed
              LEFT JOIN daily_sku_sales AS sales
                ON sales.sku_id = seed.sku_id
              GROUP BY seed.note_id, seed.sku_id, seed.publish_time
            )
            SELECT
              note_id,
              sku_id,
              publish_time,
              pre_units,
              post_3d_units,
              post_3d_units - pre_units AS lift_units,
              CASE
                WHEN pre_units > 0 THEN (post_3d_units - pre_units) / pre_units
              END AS lift_ratio
            FROM windowed
            ORDER BY note_id, sku_id
            """
        )
        columns = result.columns
        rows = [dict(zip(columns, row, strict=True)) for row in result.fetchall()]
    finally:
        con.close()

    key_numbers: dict[str, object] = {"seed_links": len(rows)}
    if rows:
        key_numbers.update(
            {
                "pre_units": rows[0]["pre_units"],
                "post_3d_units": rows[0]["post_3d_units"],
                "lift_units": rows[0]["lift_units"],
            }
        )

    return AnalysisResult(
        task_id="sku_counterfactual_lift",
        title="SKU Counterfactual Lift",
        findings=[
            Finding(
                title="Seeded SKU lift estimate",
                conclusion=_conclusion(rows),
                evidence_strength=score_evidence(
                    len(rows), has_controls=False, confounder_count=1
                ),
                key_numbers=key_numbers,
                caveats=[_ATTRIBUTION_CAVEAT],
            )
        ],
        tables={"sku_lift": rows},
    )


def _conclusion(rows: list[dict[str, object]]) -> str:
    if not rows:
        return "No seeded note-SKU lift rows were available to compare."
    row = rows[0]
    return (
        f"Seed note {row['note_id']} is linked to SKU {row['sku_id']}; "
        f"3-day post units were {row['post_3d_units']} versus "
        f"{row['pre_units']} in the 3-day pre window."
    )
