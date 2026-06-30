from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        daily_posts = con.sql(
            """
            SELECT
              CAST(publish_time AS DATE) AS date,
              COUNT(*) AS posts,
              AVG(reads) AS avg_reads
            FROM notes
            WHERE publish_time IS NOT NULL
            GROUP BY 1
            ORDER BY 1
            """
        ).fetchdf().to_dict(orient="records")
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
                    "Small fixture data limits baseline reliability. Full account data should "
                    "improve evidence strength."
                ],
            )
        ],
        tables={"daily_posts": daily_posts},
    )
