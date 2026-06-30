from datetime import date, timedelta
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_SLOTS = ("09:00", "12:00", "15:00", "18:00", "21:00")
DEFAULT_PLANNING_START = date(2026, 7, 1)


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        skus, sku_limitations = _fetch_top_skus(con)
        angles, angle_limitations = _fetch_top_angles(con)
        start_date, planning_limitations = _next_planning_date(con)
    finally:
        con.close()

    rows = _build_plan(start_date, skus, angles)
    uses_fallback = any(sku["sku_id"] == "unassigned" for sku in skus) or angles == [
        "lifestyle"
    ]
    evidence_inputs = 0 if uses_fallback else len(skus) + len(angles)
    limitations = [*sku_limitations, *angle_limitations, *planning_limitations]
    if uses_fallback:
        limitations.append("Fallback SKU or angle was used.")

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
        limitations=limitations,
    )


def _fetch_top_skus(con) -> tuple[list[dict[str, object]], list[str]]:
    if _table_exists(con, "daily_sku_sales"):
        sales_columns = _table_columns(con, "daily_sku_sales")
        if "sku_id" not in sales_columns:
            return (
                [_sku_row("unassigned", "Unassigned SKU", None, None)],
                ["daily_sku_sales.sku_id missing; using fallback SKU."],
            )
        has_skus = _table_exists(con, "skus")
        sku_columns = _table_columns(con, "skus") if has_skus else set()
        join_clause = (
            "LEFT JOIN skus AS s ON CAST(d.sku_id AS VARCHAR) = CAST(s.sku_id AS VARCHAR)"
            if has_skus and {"sku_id", "sku_name"}.issubset(sku_columns)
            else ""
        )
        name_expr = (
            "COALESCE(MAX(CAST(s.sku_name AS VARCHAR)), CAST(d.sku_id AS VARCHAR))"
            if join_clause
            else "CAST(d.sku_id AS VARCHAR)"
        )
        units_expr = (
            "SUM(CAST(d.units AS DOUBLE))"
            if "units" in sales_columns
            else "NULL"
        )
        gmv_expr = (
            "SUM(CAST(d.gmv AS DOUBLE))"
            if "gmv" in sales_columns
            else "NULL"
        )
        result = con.sql(
            f"""
            SELECT
              CAST(d.sku_id AS VARCHAR) AS sku_id,
              {name_expr} AS sku_name,
              {units_expr} AS units,
              {gmv_expr} AS gmv
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
            limitations = []
            if "units" not in sales_columns:
                limitations.append(
                    "daily_sku_sales.units missing; experiment SKU metrics left null."
                )
            if "gmv" not in sales_columns:
                limitations.append(
                    "daily_sku_sales.gmv missing; experiment SKU metrics left null."
                )
            if has_skus and not join_clause:
                limitations.append(
                    "skus missing sku_id or sku_name; using sku_id as experiment SKU label."
                )
            return rows, limitations

    if _table_exists(con, "skus"):
        sku_columns = _table_columns(con, "skus")
        if "sku_id" not in sku_columns:
            return (
                [_sku_row("unassigned", "Unassigned SKU", None, None)],
                ["skus.sku_id missing; using fallback SKU."],
            )
        result = con.sql(
            f"""
            SELECT
              CAST(sku_id AS VARCHAR) AS sku_id,
              {("CAST(sku_name AS VARCHAR)" if "sku_name" in sku_columns else "CAST(sku_id AS VARCHAR)")} AS sku_name,
              NULL AS units,
              {("CAST(price AS DOUBLE)" if "price" in sku_columns else "NULL")} AS gmv
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
            limitations = []
            if "sku_name" not in sku_columns:
                limitations.append("skus.sku_name missing; using sku_id as experiment SKU label.")
            if "price" not in sku_columns:
                limitations.append("skus.price missing; experiment SKU GMV left null.")
            return rows, limitations

    return [_sku_row("unassigned", "Unassigned SKU", None, None)], [
        "No SKU tables were available; using fallback SKU."
    ]


def _fetch_top_angles(con) -> tuple[list[str], list[str]]:
    if not _table_exists(con, "content_features"):
        return ["lifestyle"], ["content_features missing; using fallback copy angle."]

    content_columns = _table_columns(con, "content_features")
    if "copy_angle" not in content_columns:
        return ["lifestyle"], ["content_features.copy_angle missing; using fallback copy angle."]

    can_join_notes = (
        "note_id" in content_columns
        and _table_exists(con, "notes")
        and {"note_id", "reads"}.issubset(_table_columns(con, "notes"))
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
        limitations: list[str] = []
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
        limitations = []
        if _table_exists(con, "notes"):
            limitations.append(
                "notes.note_id or notes.reads missing; copy-angle ranking used content-only counts."
            )
    angles = [row[0] for row in result.fetchall()]
    if angles:
        return angles, limitations
    return ["lifestyle"], limitations + ["No copy_angle values were available; using fallback copy angle."]


def _next_planning_date(con) -> tuple[date, list[str]]:
    if not _table_exists(con, "notes") or "publish_time" not in _table_columns(con, "notes"):
        return DEFAULT_PLANNING_START, [
            f"notes.publish_time missing; planning starts at {DEFAULT_PLANNING_START.isoformat()}."
        ]

    value = con.sql(
        """
        SELECT CAST(MAX(CAST(publish_time AS DATE)) AS VARCHAR)
        FROM notes
        WHERE publish_time IS NOT NULL
        """
    ).fetchone()[0]
    if value is None:
        return DEFAULT_PLANNING_START, [
            f"No publish_time values were available; planning starts at {DEFAULT_PLANNING_START.isoformat()}."
        ]

    candidate = date.fromisoformat(value) + timedelta(days=1)
    return max(candidate, DEFAULT_PLANNING_START), []


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
