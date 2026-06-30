from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_MIN_CONFIDENT_READS = 50.0


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        metrics = _fetch_note_metrics(con) if _table_exists(con, "notes") else []
    finally:
        con.close()

    rows = _rank_candidates(metrics)
    top_candidate = rows[0]["note_id"] if rows else None

    return AnalysisResult(
        task_id="reshoot_repost_candidates",
        title="Reshoot Repost Candidates",
        findings=[
            Finding(
                title="Collect-heavy notes ranked for reshoot",
                conclusion=(
                    f"Ranked {len(rows)} notes by collect rate with a lower-read bonus."
                ),
                evidence_strength=score_evidence(
                    len(metrics), has_controls=False, confounder_count=1
                ),
                key_numbers={
                    "candidate_notes": len(rows),
                    "top_candidate": top_candidate,
                },
                caveats=[
                    "High collect rate can reflect niche intent; reshoot priority still needs "
                    "creative review.",
                    "Tiny-sample notes are downweighted and marked for more data before they "
                    "lead the queue.",
                ],
                recommended_action=(
                    "Reshoot the top candidate with a clearer opening frame and compare "
                    "read rate before reposting more variants."
                )
                if rows
                else "Collect readable note metrics before selecting reshoot candidates.",
            )
        ],
        tables={"reshoot_candidates": rows},
        limitations=[] if rows else ["No readable note metrics were available."],
    )


def _fetch_note_metrics(con) -> list[dict[str, object]]:
    columns = _table_columns(con, "notes")
    required = {"note_id", "reads", "collects"}
    if not required.issubset(columns):
        return []

    title_expr = "CAST(title AS VARCHAR)" if "title" in columns else "CAST(note_id AS VARCHAR)"
    result = con.sql(
        f"""
        SELECT
          CAST(note_id AS VARCHAR) AS note_id,
          {title_expr} AS title,
          CAST(reads AS DOUBLE) AS reads,
          CAST(collects AS DOUBLE) AS collects
        FROM notes
        WHERE reads IS NOT NULL
          AND collects IS NOT NULL
          AND reads > 0
        ORDER BY note_id
        """
    )
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _rank_candidates(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    if not metrics:
        return []

    max_reads = max(float(row["reads"]) for row in metrics)
    ranked = []
    for row in metrics:
        reads = float(row["reads"])
        collects = float(row["collects"])
        collect_rate = collects / reads if reads else 0.0
        confidence_weight = reads / (reads + _MIN_CONFIDENT_READS)
        conservative_collect_rate = collect_rate * confidence_weight
        read_gap_to_max = (max_reads - reads) / max_reads if max_reads else 0.0
        needs_more_data = reads < _MIN_CONFIDENT_READS
        opportunity_score = conservative_collect_rate * 100 + read_gap_to_max * 0.25
        ranked.append(
            {
                "note_id": row["note_id"],
                "title": row["title"],
                "reads": int(reads),
                "collects": int(collects),
                "collect_rate": round(collect_rate, 4),
                "conservative_collect_rate": round(conservative_collect_rate, 4),
                "confidence_weight": round(confidence_weight, 4),
                "read_gap_to_max": round(read_gap_to_max, 4),
                "opportunity_score": round(opportunity_score, 4),
                "needs_more_data": needs_more_data,
                "reason": (
                    "high_collect_rate_low_read_ceiling"
                    if not needs_more_data
                    else "promising_but_needs_more_reads"
                ),
            }
        )

    ranked.sort(
        key=lambda row: (
            bool(row["needs_more_data"]),
            -float(row["opportunity_score"]),
            -float(row["conservative_collect_rate"]),
            -float(row["collect_rate"]),
            -int(row["reads"]),
            str(row["note_id"]),
        )
    )
    return [
        {"rank": index, **row}
        for index, row in enumerate(ranked[:10], start=1)
    ]


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
