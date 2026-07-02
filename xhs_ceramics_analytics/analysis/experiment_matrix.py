from datetime import date, timedelta
import os
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_SLOTS = ("09:00", "12:00", "15:00", "18:00", "21:00")


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
        limitations.append("使用了兜底 SKU 或兜底文案角度。")

    return AnalysisResult(
        task_id="weekly_experiment_matrix",
        title="每周实验矩阵",
        findings=[
            Finding(
                title="七天实验计划已生成",
                conclusion=(
                    f"已生成 {len(rows)} 个确定性测试档期，覆盖 "
                    f"7 天、每天 {len(_SLOTS)} 个时段。"
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
                caveats=["这是确定性排期矩阵，不代表这些档期一定会胜出。"],
                recommended_action=(
                    "按矩阵发布受控周档期，并用阅读、收藏和评论需求指标比较每个档期。"
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
                [_sku_row("unassigned", "未分配 SKU", None, None)],
                ["daily_sku_sales 表缺少 sku_id，使用兜底 SKU。"],
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
                    "daily_sku_sales 表缺少 units，实验 SKU 指标留空。"
                )
            if "gmv" not in sales_columns:
                limitations.append(
                    "daily_sku_sales 表缺少 gmv，实验 SKU 指标留空。"
                )
            if has_skus and not join_clause:
                limitations.append(
                    "skus 表缺少 sku_id 或 sku_name，使用 sku_id 作为实验 SKU 名称。"
                )
            return rows, limitations

    if _table_exists(con, "skus"):
        sku_columns = _table_columns(con, "skus")
        if "sku_id" not in sku_columns:
            return (
                [_sku_row("unassigned", "未分配 SKU", None, None)],
                ["skus 表缺少 sku_id，使用兜底 SKU。"],
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
                limitations.append("skus 表缺少 sku_name，使用 sku_id 作为实验 SKU 名称。")
            if "price" not in sku_columns:
                limitations.append("skus 表缺少 price，实验 SKU GMV 留空。")
            return rows, limitations

    return [_sku_row("unassigned", "未分配 SKU", None, None)], [
        "没有可用的 SKU 表，使用兜底 SKU。"
    ]


def _fetch_top_angles(con) -> tuple[list[str], list[str]]:
    if not _table_exists(con, "content_features"):
        return ["lifestyle"], ["缺少 content_features 表，使用兜底文案角度。"]

    content_columns = _table_columns(con, "content_features")
    if "copy_angle" not in content_columns:
        return ["lifestyle"], ["content_features 表缺少 copy_angle，使用兜底文案角度。"]

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
                "notes 表缺少 note_id 或 reads，文案角度排序仅使用内容计数。"
            )
    angles = [row[0] for row in result.fetchall()]
    if angles:
        return angles, limitations
    return ["lifestyle"], limitations + ["没有可用的 copy_angle 值，使用兜底文案角度。"]


def _next_planning_date(con) -> tuple[date, list[str]]:
    default_start = _default_planning_start()
    if not _table_exists(con, "notes") or "publish_time" not in _table_columns(con, "notes"):
        return default_start, [
            f"notes 表缺少 publish_time，计划从 {default_start.isoformat()} 开始。"
        ]

    value = con.sql(
        """
        SELECT CAST(MAX(CAST(publish_time AS DATE)) AS VARCHAR)
        FROM notes
        WHERE publish_time IS NOT NULL
        """
    ).fetchone()[0]
    if value is None:
        return default_start, [
            f"没有可用的 publish_time 值，计划从 {default_start.isoformat()} 开始。"
        ]

    candidate = date.fromisoformat(value) + timedelta(days=1)
    return max(candidate, default_start), []


def _default_planning_start() -> date:
    return _today() + timedelta(days=1)


def _today() -> date:
    override = os.environ.get("XHS_CA_TODAY")
    if override:
        return date.fromisoformat(override)
    return date.today()


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
