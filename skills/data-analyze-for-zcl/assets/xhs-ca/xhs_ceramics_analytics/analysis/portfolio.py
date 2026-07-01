from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows, limitations = (
            _fetch_portfolio_mix(con)
            if _table_exists(con, "content_features")
            else ([], ["缺少 content_features 表。"])
        )
    finally:
        con.close()

    sample_size = sum(int(row["notes"]) for row in rows)
    top_role = rows[0]["copy_angle"] if rows else None
    if not rows:
        limitations.append("没有可用的 content_features.copy_angle 数据。")

    return AnalysisResult(
        task_id="content_portfolio_optimization",
        title="内容组合优化",
        findings=[
            Finding(
                title="文案角度组合已统计",
                conclusion=(
                    f"已统计 {sample_size} 篇笔记，覆盖 {len(rows)} 类文案角度。"
                ),
                evidence_strength=score_evidence(
                    sample_size, has_controls=False, confounder_count=1
                ),
                key_numbers={
                    "notes": sample_size,
                    "roles": len(rows),
                    "top_role": top_role,
                },
                caveats=["角度占比描述的是已发布内容供给，不是受控需求。"],
                recommended_action=(
                    "将占比不足且阅读率或收藏率更强的角度，作为下周内容档期候选。"
                )
                if rows
                else "先补充带 copy_angle 的 content_features 数据，再优化内容组合。",
            )
        ],
        tables={"portfolio_mix": rows},
        limitations=limitations,
    )


def _fetch_portfolio_mix(con) -> tuple[list[dict[str, object]], list[str]]:
    content_columns = _table_columns(con, "content_features")
    if "copy_angle" not in content_columns:
        return [], ["content_features 表缺少 copy_angle，无法生成组合分析。"]

    note_columns = _table_columns(con, "notes") if _table_exists(con, "notes") else set()
    can_join_notes = (
        "note_id" in content_columns
        and {"note_id", "reads", "collects"}.issubset(note_columns)
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
        limitations: list[str] = []
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
        limitations = []
        if _table_exists(con, "notes"):
            limitations.append(
                "notes 表缺少 note_id、reads 或 collects，组合指标留空。"
            )

    columns = result.columns
    rows = [_clean_row(dict(zip(columns, row, strict=True))) for row in result.fetchall()]
    return rows, limitations


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
