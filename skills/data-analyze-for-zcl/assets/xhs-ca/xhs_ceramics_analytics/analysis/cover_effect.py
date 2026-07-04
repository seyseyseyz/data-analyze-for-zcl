from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.evidence import score_evidence
from xhs_ceramics_analytics.evidence import score_reliability


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows, limitations = _fetch_cover_effects(con)
    finally:
        con.close()

    evidence_strength = (
        score_evidence(len(rows), has_controls=False, confounder_count=1)
        if rows and _has_metric_evidence(rows)
        else EvidenceStrength.NOT_JUDGABLE
    )
    descriptive_reliability = score_reliability(len(rows))
    return AnalysisResult(
        task_id="cover_style_effect",
        title="封面风格效果",
        findings=[
            Finding(
                title="封面类型已排序",
                conclusion="已按平均阅读数和收藏数对封面构图类型进行排序。",
                evidence_strength=evidence_strength,
                descriptive_reliability=descriptive_reliability,
                key_numbers={"cover_groups": len(rows)},
                caveats=["在加入 SKU 和发布时间控制前，这个排序仍是描述性结果。"],
            )
        ],
        tables={"cover_effects": rows},
        limitations=limitations,
    )


def _fetch_cover_effects(con) -> tuple[list[dict[str, object]], list[str]]:
    if not _table_exists(con, "content_features"):
        return [], ["缺少 content_features 表。"]

    content_columns = _table_columns(con, "content_features")
    if "composition_type" not in content_columns:
        return [], ["content_features 表缺少 composition_type 字段。"]

    can_join_notes = (
        "note_id" in content_columns
        and _table_exists(con, "notes")
        and "note_id" in _table_columns(con, "notes")
    )
    if not can_join_notes:
        result = con.sql(
            """
            SELECT
              COALESCE(NULLIF(TRIM(CAST(composition_type AS VARCHAR)), ''), 'unknown')
                AS composition_type,
              COUNT(*) AS notes,
              NULL AS avg_reads,
              NULL AS avg_collects
            FROM content_features
            GROUP BY 1
            ORDER BY notes DESC, composition_type
            """
        )
        return _rows(result), ["笔记指标不可用，封面排序仅使用特征计数。"]

    note_columns = _table_columns(con, "notes")
    avg_reads = "AVG(CAST(n.reads AS DOUBLE))" if "reads" in note_columns else "NULL"
    avg_collects = (
        "AVG(CAST(n.collects AS DOUBLE))" if "collects" in note_columns else "NULL"
    )
    result = con.sql(
        f"""
        SELECT
          COALESCE(NULLIF(TRIM(CAST(f.composition_type AS VARCHAR)), ''), 'unknown')
            AS composition_type,
          COUNT(*) AS notes,
          {avg_reads} AS avg_reads,
          {avg_collects} AS avg_collects
        FROM content_features f
        LEFT JOIN notes n ON CAST(f.note_id AS VARCHAR) = CAST(n.note_id AS VARCHAR)
        GROUP BY 1
        ORDER BY avg_reads DESC NULLS LAST, notes DESC, composition_type
        """
    )
    limitations = []
    if "reads" not in note_columns or "collects" not in note_columns:
        limitations.append("notes 表的阅读/收藏指标不完整。")
    rows = _rows(result)
    if rows and not _has_metric_evidence(rows):
        limitations.append("没有匹配的笔记指标，封面效果不可判断。")
    return rows, limitations


def _rows(result) -> list[dict[str, object]]:
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _has_metric_evidence(rows: list[dict[str, object]]) -> bool:
    return any(
        row.get("avg_reads") is not None or row.get("avg_collects") is not None
        for row in rows
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
