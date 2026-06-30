from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("notes table missing.")
        columns = _table_columns(con, "notes")
        if "note_id" not in columns:
            return _missing_result("notes.note_id column missing.")

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
        title="Note Funnel",
        findings=[
            Finding(
                title="Funnel metrics calculated",
                conclusion=(
                    "The skill calculated read, like, collect, and comment rates where "
                    "denominators exist."
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
        title="Note Funnel",
        findings=[
            Finding(
                title="Funnel metrics unavailable",
                conclusion="Note funnel needs note IDs and engagement metrics before rates can be calculated.",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"notes": 0},
                caveats=["Missing funnel data should be treated as an import gap."],
                recommended_action="Export notes with impressions, reads, likes, collects, and comments.",
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
    return [f"notes columns missing for funnel rates: {', '.join(missing)}."] if missing else []


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
