from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("notes table missing.")
        columns = _table_columns(con, "notes")
        if "publish_time" not in columns:
            return _missing_result("notes.publish_time column missing.")
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
        title="Account Baseline",
        findings=[
            Finding(
                title="Posting baseline",
                conclusion=(
                    f"The dataset contains {sample_size} posts across "
                    f"{len(daily_posts)} active posting days."
                ),
                evidence_strength=score_evidence(
                    sample_size, has_controls=False, confounder_count=1
                ),
                key_numbers={"posts": sample_size, "active_days": len(daily_posts)},
                caveats=[
                    "Sample size and lack of control context limit causal interpretation of "
                    "this baseline."
                ],
            )
        ],
        tables={"daily_posts": daily_posts},
    )


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="account_baseline",
        title="Account Baseline",
        findings=[
            Finding(
                title="Posting baseline unavailable",
                conclusion="Account baseline needs dated note exports before it can be calculated.",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"posts": 0, "active_days": 0},
                caveats=["Missing baseline data should be treated as an import gap."],
                recommended_action="Export notes with publish_time and reads, then rebuild.",
            )
        ],
        tables={"daily_posts": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
