from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows = _fetch_portfolio_mix(con) if _table_exists(con, "content_features") else []
    finally:
        con.close()

    sample_size = sum(int(row["notes"]) for row in rows)
    top_role = rows[0]["copy_angle"] if rows else None
    limitations = [] if rows else ["No content_features.copy_angle rows were available."]

    return AnalysisResult(
        task_id="content_portfolio_optimization",
        title="Content Portfolio Optimization",
        findings=[
            Finding(
                title="Copy-angle portfolio counted",
                conclusion=(
                    f"Counted {sample_size} notes across {len(rows)} copy-angle roles."
                ),
                evidence_strength=score_evidence(
                    sample_size, has_controls=False, confounder_count=1
                ),
                key_numbers={
                    "notes": sample_size,
                    "roles": len(rows),
                    "top_role": top_role,
                },
                caveats=[
                    "Role mix describes observed publishing supply, not controlled demand."
                ],
                recommended_action=(
                    "Use underrepresented roles with stronger read or collect rates as "
                    "candidates for next-week content slots."
                )
                if rows
                else "Add content_features rows with copy_angle before optimizing mix.",
            )
        ],
        tables={"portfolio_mix": rows},
        limitations=limitations,
    )


def _fetch_portfolio_mix(con) -> list[dict[str, object]]:
    content_columns = _table_columns(con, "content_features")
    if "copy_angle" not in content_columns:
        return []

    can_join_notes = (
        "note_id" in content_columns
        and _table_exists(con, "notes")
        and "note_id" in _table_columns(con, "notes")
    )
    if can_join_notes:
        result = con.sql(
            """
            SELECT
              COALESCE(NULLIF(TRIM(CAST(cf.copy_angle AS VARCHAR)), ''), 'unknown')
                AS copy_angle,
              COUNT(*) AS notes,
              COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS mix_share,
              AVG(CAST(n.reads AS DOUBLE)) AS avg_reads,
              AVG(CASE WHEN n.reads > 0 THEN n.collects * 1.0 / n.reads END)
                AS avg_collect_rate
            FROM content_features AS cf
            LEFT JOIN notes AS n ON CAST(cf.note_id AS VARCHAR) = CAST(n.note_id AS VARCHAR)
            GROUP BY 1
            ORDER BY notes DESC, avg_reads DESC NULLS LAST, copy_angle
            """
        )
    else:
        result = con.sql(
            """
            SELECT
              COALESCE(NULLIF(TRIM(CAST(copy_angle AS VARCHAR)), ''), 'unknown')
                AS copy_angle,
              COUNT(*) AS notes,
              COUNT(*) * 1.0 / SUM(COUNT(*)) OVER () AS mix_share,
              NULL AS avg_reads,
              NULL AS avg_collect_rate
            FROM content_features
            GROUP BY 1
            ORDER BY notes DESC, copy_angle
            """
        )

    columns = result.columns
    return [_clean_row(dict(zip(columns, row, strict=True))) for row in result.fetchall()]


def _clean_row(row: dict[str, object]) -> dict[str, object]:
    cleaned = dict(row)
    for key in ("mix_share", "avg_reads", "avg_collect_rate"):
        if cleaned[key] is not None:
            cleaned[key] = round(float(cleaned[key]), 4)
    return cleaned


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
