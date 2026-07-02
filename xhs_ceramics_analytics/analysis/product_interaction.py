from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows, limitations = _fetch_interactions(con)
    finally:
        con.close()

    return AnalysisResult(
        task_id="product_content_interaction",
        title="商品与内容交互",
        findings=[
            Finding(
                title="内容组合已排序",
                conclusion="已对封面构图与文案角度组合做初步交互对比。",
                evidence_strength=(
                    EvidenceStrength.WEAK
                    if rows and _has_metric_evidence(rows)
                    else EvidenceStrength.NOT_JUDGABLE
                ),
                key_numbers={"combinations": len(rows)},
                caveats=["需要显式 note-SKU 关联后，商品交互证据才会更强。"],
            )
        ],
        tables={"product_interactions": rows},
        limitations=limitations,
    )


def _fetch_interactions(con) -> tuple[list[dict[str, object]], list[str]]:
    if not _table_exists(con, "content_features"):
        return [], ["缺少 content_features 表。"]

    content_columns = _table_columns(con, "content_features")
    required = {"composition_type", "copy_angle"}
    if not required.issubset(content_columns):
        return [], ["content_features 表的 composition_type/copy_angle 字段不完整。"]

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
              COALESCE(NULLIF(TRIM(CAST(copy_angle AS VARCHAR)), ''), 'unknown')
                AS copy_angle,
              COUNT(*) AS notes,
              NULL AS avg_reads,
              NULL AS avg_collects
            FROM content_features
            GROUP BY 1, 2
            ORDER BY notes DESC, composition_type, copy_angle
            """
        )
        return _rows(result), ["笔记指标不可用，交互视图仅使用特征计数。"]

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
          COALESCE(NULLIF(TRIM(CAST(f.copy_angle AS VARCHAR)), ''), 'unknown')
            AS copy_angle,
          COUNT(*) AS notes,
          {avg_reads} AS avg_reads,
          {avg_collects} AS avg_collects
        FROM content_features f
        LEFT JOIN notes n ON CAST(f.note_id AS VARCHAR) = CAST(n.note_id AS VARCHAR)
        GROUP BY 1, 2
        ORDER BY avg_reads DESC NULLS LAST, notes DESC, composition_type, copy_angle
        """
    )
    limitations = []
    if "reads" not in note_columns or "collects" not in note_columns:
        limitations.append("notes 表的阅读/收藏指标不完整。")
    rows = _rows(result)
    if rows and not _has_metric_evidence(rows):
        limitations.append("没有匹配的笔记指标，内容交互效果不可判断。")
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
