from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("缺少 notes 表。")
        columns = _table_columns(con, "notes")
        if "note_id" not in columns:
            return _missing_result("notes 表缺少 note_id 字段。")

        reads_expr = "CAST(reads AS DOUBLE)" if "reads" in columns else "NULL"
        impressions_expr = (
            "CAST(impressions AS DOUBLE)" if "impressions" in columns else "NULL"
        )
        likes_expr = "CAST(likes AS DOUBLE)" if "likes" in columns else "NULL"
        collects_expr = "CAST(collects AS DOUBLE)" if "collects" in columns else "NULL"
        comments_expr = "CAST(comments AS DOUBLE)" if "comments" in columns else "NULL"
        result = con.sql(
            f"""
            SELECT
              CAST(note_id AS VARCHAR) AS note_id,
              {reads_expr} AS reads,
              CASE
                WHEN {impressions_expr} > 0 THEN {reads_expr} * 1.0 / {impressions_expr}
              END AS read_rate,
              CASE WHEN {reads_expr} > 0 THEN {likes_expr} * 1.0 / {reads_expr} END
                AS like_rate,
              CASE WHEN {reads_expr} > 0 THEN {collects_expr} * 1.0 / {reads_expr} END
                AS collect_rate,
              CASE WHEN {reads_expr} > 0 THEN {comments_expr} * 1.0 / {reads_expr} END
                AS comment_rate
            FROM notes
            ORDER BY reads DESC
            """
        )
        result_columns = result.columns
        rows = [dict(zip(result_columns, row, strict=True)) for row in result.fetchall()]
        limitations = _metric_limitations(columns)
    finally:
        con.close()
    return AnalysisResult(
        task_id="note_funnel",
        title="笔记漏斗",
        findings=[
            Finding(
                title="漏斗指标已计算",
                conclusion=(
                    "已在分母可用的情况下计算阅读率、点赞率、收藏率和评论率。"
                ),
                evidence_strength=(
                    EvidenceStrength.MEDIUM
                    if rows and not limitations
                    else EvidenceStrength.NOT_JUDGABLE
                ),
                key_numbers={"notes": len(rows)},
                caveats=[],
            )
        ],
        tables={"note_funnel": rows},
        limitations=limitations,
    )


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="note_funnel",
        title="笔记漏斗",
        findings=[
            Finding(
                title="漏斗指标不可计算",
                conclusion="需要笔记 ID 和互动指标后，才能计算笔记漏斗。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"notes": 0},
                caveats=["漏斗数据缺失应视为导入缺口。"],
                recommended_action="导出包含 impressions、reads、likes、collects 和 comments 的 notes 数据。",
            )
        ],
        tables={"note_funnel": []},
        limitations=[reason],
    )


def _metric_limitations(columns: set[str]) -> list[str]:
    missing = [
        column
        for column in ("impressions", "reads", "likes", "collects", "comments")
        if column not in columns
    ]
    return [f"笔记表缺少漏斗指标字段：{', '.join(missing)}。"] if missing else []


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
