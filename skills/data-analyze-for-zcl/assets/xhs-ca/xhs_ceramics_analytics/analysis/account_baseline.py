from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("缺少 notes 表。")
        columns = _table_columns(con, "notes")
        if "publish_time" not in columns:
            return _missing_result("notes 表缺少 publish_time 字段。")
        reads_expr = "AVG(CAST(reads AS DOUBLE))" if "reads" in columns else "NULL"
        result = con.sql(
            f"""
            SELECT
              CAST(CAST(publish_time AS DATE) AS VARCHAR) AS date,
              COUNT(*) AS posts,
              {reads_expr} AS avg_reads
            FROM notes
            WHERE publish_time IS NOT NULL
            GROUP BY 1
            ORDER BY 1
            """
        )
        daily_posts = [
            {"date": date, "posts": posts, "avg_reads": avg_reads}
            for date, posts, avg_reads in result.fetchall()
        ]
    finally:
        con.close()
    sample_size = int(sum(row["posts"] for row in daily_posts))
    return AnalysisResult(
        task_id="account_baseline",
        title="账号基线",
        findings=[
            Finding(
                title="发布基线",
                conclusion=(
                    f"当前数据包含 {qty(sample_size)} 篇笔记，覆盖 "
                    f"{qty(len(daily_posts))} 个有发布记录的日期。"
                ),
                evidence_strength=score_evidence(
                    sample_size, has_controls=False, confounder_count=1
                ),
                key_numbers={"posts": sample_size, "active_days": len(daily_posts)},
                caveats=[
                    "样本量和对照上下文有限，这个基线只能做描述性判断。"
                ],
            )
        ],
        tables={"daily_posts": daily_posts},
    )


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="account_baseline",
        title="账号基线",
        findings=[
            Finding(
                title="发布基线不可计算",
                conclusion="需要带发布时间的笔记导出数据后，才能计算账号基线。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"posts": 0, "active_days": 0},
                caveats=["基线数据缺失应视为导入缺口。"],
                recommended_action="导出包含 publish_time 和 reads 的 notes 数据，然后重新构建。"
            )
        ],
        tables={"daily_posts": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
