from datetime import date, timedelta
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_SLOTS = ("09:00", "12:00", "15:00", "18:00", "21:00")


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        skus = _fetch_top_skus(con)
        angles = _fetch_top_angles(con)
        start_date = _next_planning_date(con)
    finally:
        con.close()

    rows = _build_plan(start_date, skus, angles)
    uses_fallback = any(sku["sku_id"] == "unassigned" for sku in skus) or angles == [
        "lifestyle"
    ]
    evidence_inputs = 0 if uses_fallback else len(skus) + len(angles)

    return AnalysisResult(
        task_id="weekly_experiment_matrix",
        title="Weekly Experiment Matrix",
        findings=[
            Finding(
                title="Seven-day experiment plan generated",
                conclusion=(
                    f"Generated {len(rows)} deterministic test slots across "
                    f"7 days and {len(_SLOTS)} daily slots."
                ),
                evidence_strength=score_evidence(
                    evidence_inputs, has_controls=False, confounder_count=2
                ),
                key_numbers={
                    "planned_rows": len(rows),
                    "days": 7,
                    "slots_per_day": len(_SLOTS),
                    "unique_skus": len({row["sku_id"] for row in rows}),
                    "content_angles": len({row["copy_angle"] for row in rows}),
                },
                caveats=[
                    "This is a deterministic planning matrix, not evidence that slots will win."
                ],
                recommended_action=(
                    "Publish the matrix as controlled weekly slots and compare each slot "
                    "against read, collect, and comment demand metrics."
                ),
            )
        ],
        tables={"experiment_plan": rows},
        limitations=["Fallback SKU or angle was used."] if uses_fallback else [],
    )


def _fetch_top_skus(con) -> list[dict[str, object]]:
    if _table_exists(con, "daily_sku_sales"):
        has_skus = _table_exists(con, "skus")
        join_clause = (
            "LEFT JOIN skus AS s ON CAST(d.sku_id AS VARCHAR) = CAST(s.sku_id AS VARCHAR)"
            if has_skus
            else ""
        )
        name_expr = "COALESCE(MAX(CAST(s.sku_name AS VARCHAR)), CAST(d.sku_id AS VARCHAR))"
        if not has_skus:
            name_expr = "CAST(d.sku_id AS VARCHAR)"
        result = con.sql(
            f"""
            SELECT
              CAST(d.sku_id AS VARCHAR) AS sku_id,
              {name_expr} AS sku_name,
              SUM(CAST(d.units AS DOUBLE)) AS units,
              SUM(CAST(d.gmv AS DOUBLE)) AS gmv
            FROM daily_sku_sales AS d
            {join_clause}
            GROUP BY 1
            ORDER BY units DESC NULLS LAST, gmv DESC NULLS LAST, sku_id
            LIMIT 5
            """
        )
        rows = [
            _sku_row(sku_id, sku_name, units, gmv)
            for sku_id, sku_name, units, gmv in result.fetchall()
        ]
        if rows:
            return rows

    if _table_exists(con, "skus"):
        result = con.sql(
            """
            SELECT
              CAST(sku_id AS VARCHAR) AS sku_id,
              CAST(sku_name AS VARCHAR) AS sku_name,
              NULL AS units,
              CAST(price AS DOUBLE) AS gmv
            FROM skus
            ORDER BY gmv DESC NULLS LAST, sku_id
            LIMIT 5
            """
        )
        rows = [
            _sku_row(sku_id, sku_name, units, gmv)
            for sku_id, sku_name, units, gmv in result.fetchall()
        ]
        if rows:
            return rows

    return [_sku_row("unassigned", "Unassigned SKU", None, None)]


def _fetch_top_angles(con) -> list[str]:
    if not _table_exists(con, "content_features"):
        return ["lifestyle"]

    content_columns = _table_columns(con, "content_features")
    if "copy_angle" not in content_columns:
        return ["lifestyle"]

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
              AVG(CAST(n.reads AS DOUBLE)) AS avg_reads
            FROM content_features AS cf
            LEFT JOIN notes AS n ON CAST(cf.note_id AS VARCHAR) = CAST(n.note_id AS VARCHAR)
            GROUP BY 1
            ORDER BY notes DESC, avg_reads DESC NULLS LAST, copy_angle
            LIMIT 5
            """
        )
    else:
        result = con.sql(
            """
            SELECT
              COALESCE(NULLIF(TRIM(CAST(copy_angle AS VARCHAR)), ''), 'unknown')
                AS copy_angle,
              COUNT(*) AS notes
            FROM content_features
            GROUP BY 1
            ORDER BY notes DESC, copy_angle
            LIMIT 5
            """
        )
    angles = [row[0] for row in result.fetchall()]
    return angles or ["lifestyle"]


def _next_planning_date(con) -> date:
    if not _table_exists(con, "notes") or "publish_time" not in _table_columns(con, "notes"):
        return date(2026, 1, 1)

    value = con.sql(
        """
        SELECT CAST(MAX(CAST(publish_time AS DATE)) AS VARCHAR)
        FROM notes
        WHERE publish_time IS NOT NULL
        """
    ).fetchone()[0]
    if value is None:
        return date(2026, 1, 1)
    return date.fromisoformat(value) + timedelta(days=1)


def _build_plan(
    start_date: date, skus: list[dict[str, object]], angles: list[str]
) -> list[dict[str, object]]:
    rows = []
    for day_offset in range(7):
        plan_date = start_date + timedelta(days=day_offset)
        for slot_offset, slot_time in enumerate(_SLOTS):
            absolute_slot = day_offset * len(_SLOTS) + slot_offset
            sku = skus[absolute_slot % len(skus)]
            angle = angles[(day_offset + slot_offset) % len(angles)]
            rows.append(
                {
                    "date": plan_date.isoformat(),
                    "day_index": day_offset + 1,
                    "slot_index": slot_offset + 1,
                    "slot_time": slot_time,
                    "sku_id": sku["sku_id"],
                    "sku_name": sku["sku_name"],
                    "copy_angle": angle,
                    "experiment_seed": f"{plan_date.isoformat()}-{slot_time}-{sku['sku_id']}-{angle}",
                    "success_metric": "collect_rate",
                }
            )
    return rows


def _sku_row(
    sku_id: str, sku_name: str | None, units: object | None, gmv: object | None
) -> dict[str, object]:
    return {
        "sku_id": sku_id,
        "sku_name": sku_name or sku_id,
        "units": round(float(units), 4) if units is not None else None,
        "gmv": round(float(gmv), 4) if gmv is not None else None,
    }


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
