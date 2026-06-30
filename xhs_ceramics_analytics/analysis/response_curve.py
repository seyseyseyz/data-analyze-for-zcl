from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

_SALES_REQUIRED_COLUMNS = {"date", "sku_id", "units"}
_NOTES_REQUIRED_COLUMNS = {"note_id", "publish_time"}
_LINK_REQUIRED_COLUMNS = {"note_id", "sku_id"}
_SKUS_REQUIRED_COLUMNS = {"sku_id"}

_REAL_LINK_CAVEAT = (
    "Response windows are descriptive note-linked sales windows and do not isolate causal impact."
)
_CANDIDATE_LINK_CAVEAT = (
    "No explicit note_sku_links table was available, so response windows use a first-SKU "
    "candidate fallback with very weak attribution."
)


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        sales_issue = _sales_readiness_issue(con)
        if sales_issue is not None:
            return _missing_result(
                reason=sales_issue,
                caveats=[_REAL_LINK_CAVEAT],
                recommended_action=(
                    "Load daily_sku_sales with date, sku_id, and units before reading response "
                    "windows."
                ),
            )

        link_context = _link_context(con)
        if link_context["query"] is None:
            return _missing_result(
                reason=str(link_context["reason"]),
                caveats=list(link_context["caveats"]),
                recommended_action=str(link_context["recommended_action"]),
            )

        rows = _response_rows(con, str(link_context["query"]))
    finally:
        con.close()

    if not rows:
        return _missing_result(
            reason=(
                "No note-SKU links with publish_time and matching sales rows were available "
                "for response windows."
            ),
            caveats=list(link_context["caveats"]),
            recommended_action=str(link_context["recommended_action"]),
        )

    return AnalysisResult(
        task_id="content_response_curve",
        title="Content Response Curve",
        findings=[
            Finding(
                title="Descriptive note-anchored response windows",
                conclusion=(
                    f"Built note-anchored response windows for {len(rows)} note-SKU rows using "
                    "publish-date windows instead of a fixed calendar anchor."
                ),
                evidence_strength=score_evidence(
                    len(rows),
                    has_controls=False,
                    confounder_count=1 if link_context["source"] == "note_sku_links" else 3,
                ),
                key_numbers={
                    "note_sku_rows": len(rows),
                    "link_source": link_context["source"],
                    "d8_14_rows": sum(1 for row in rows if row["d8_14_units"] is not None),
                },
                caveats=list(link_context["caveats"]),
                recommended_action=(
                    "Use these windows as weak timing diagnostics, then validate promising "
                    "patterns with explicit linking or a controlled experiment."
                ),
            )
        ],
        tables={"response_windows": rows},
        limitations=[
            "Response windows remain observational and can be distorted by overlapping notes, "
            "stockouts, or demand shifts unrelated to the focal content."
        ],
    )


def _response_rows(con, link_query: str) -> list[dict[str, object]]:
    result = con.sql(
        f"""
        WITH link_candidates AS (
          {link_query}
        )
        SELECT
          lc.note_id,
          lc.sku_id,
          CAST(lc.publish_time AS VARCHAR) AS publish_time,
          COALESCE(
            SUM(
              CASE
                WHEN sales.date >= CAST(lc.publish_time AS DATE)
                 AND sales.date < CAST(lc.publish_time AS DATE) + INTERVAL '1 day'
                THEN CAST(sales.units AS DOUBLE)
                ELSE 0
              END
            ),
            0.0
          ) AS d0_1_units,
          COALESCE(
            SUM(
              CASE
                WHEN sales.date >= CAST(lc.publish_time AS DATE) + INTERVAL '1 day'
                 AND sales.date < CAST(lc.publish_time AS DATE) + INTERVAL '4 days'
                THEN CAST(sales.units AS DOUBLE)
                ELSE 0
              END
            ),
            0.0
          ) AS d1_3_units,
          COALESCE(
            SUM(
              CASE
                WHEN sales.date >= CAST(lc.publish_time AS DATE) + INTERVAL '4 days'
                 AND sales.date < CAST(lc.publish_time AS DATE) + INTERVAL '8 days'
                THEN CAST(sales.units AS DOUBLE)
                ELSE 0
              END
            ),
            0.0
          ) AS d4_7_units,
          COALESCE(
            SUM(
              CASE
                WHEN sales.date >= CAST(lc.publish_time AS DATE) + INTERVAL '8 days'
                 AND sales.date < CAST(lc.publish_time AS DATE) + INTERVAL '15 days'
                THEN CAST(sales.units AS DOUBLE)
                ELSE 0
              END
            ),
            0.0
          ) AS d8_14_units
        FROM link_candidates AS lc
        LEFT JOIN daily_sku_sales AS sales
          ON CAST(sales.sku_id AS VARCHAR) = lc.sku_id
        GROUP BY lc.note_id, lc.sku_id, lc.publish_time
        ORDER BY lc.note_id, lc.sku_id, lc.publish_time
        """
    )
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _link_context(con) -> dict[str, object]:
    if _table_exists(con, "note_sku_links"):
        link_columns = _table_columns(con, "note_sku_links")
        notes_columns = _table_columns(con, "notes") if _table_exists(con, "notes") else set()
        if _LINK_REQUIRED_COLUMNS.issubset(link_columns) and _NOTES_REQUIRED_COLUMNS.issubset(
            notes_columns
        ):
            return {
                "query": """
                    SELECT DISTINCT
                      CAST(l.note_id AS VARCHAR) AS note_id,
                      CAST(l.sku_id AS VARCHAR) AS sku_id,
                      CAST(n.publish_time AS TIMESTAMP) AS publish_time
                    FROM note_sku_links AS l
                    INNER JOIN notes AS n
                      ON CAST(n.note_id AS VARCHAR) = CAST(l.note_id AS VARCHAR)
                    WHERE l.note_id IS NOT NULL
                      AND l.sku_id IS NOT NULL
                      AND n.publish_time IS NOT NULL
                """,
                "source": "note_sku_links",
                "caveats": [_REAL_LINK_CAVEAT],
                "reason": None,
                "recommended_action": None,
            }
        return {
            "query": None,
            "source": None,
            "caveats": [_REAL_LINK_CAVEAT],
            "reason": (
                "note_sku_links exists but usable note_id/sku_id links with notes.publish_time "
                "were not available."
            ),
            "recommended_action": (
                "Populate note_sku_links.note_id, note_sku_links.sku_id, and notes.publish_time "
                "so response windows can anchor to real note dates."
            ),
        }

    if _table_exists(con, "notes") and _table_exists(con, "skus"):
        notes_columns = _table_columns(con, "notes")
        skus_columns = _table_columns(con, "skus")
        if _NOTES_REQUIRED_COLUMNS.issubset(notes_columns) and _SKUS_REQUIRED_COLUMNS.issubset(
            skus_columns
        ):
            return {
                "query": """
                    SELECT
                      CAST(n.note_id AS VARCHAR) AS note_id,
                      CAST(s.sku_id AS VARCHAR) AS sku_id,
                      CAST(n.publish_time AS TIMESTAMP) AS publish_time
                    FROM (
                      SELECT note_id, publish_time
                      FROM notes
                      WHERE note_id IS NOT NULL AND publish_time IS NOT NULL
                      ORDER BY publish_time, note_id
                      LIMIT 25
                    ) AS n
                    CROSS JOIN (
                      SELECT sku_id
                      FROM skus
                      WHERE sku_id IS NOT NULL
                      ORDER BY sku_id
                      LIMIT 1
                    ) AS s
                """,
                "source": "candidate_first_sku",
                "caveats": [_REAL_LINK_CAVEAT, _CANDIDATE_LINK_CAVEAT],
                "reason": None,
                "recommended_action": None,
            }

    return {
        "query": None,
        "source": None,
        "caveats": [_REAL_LINK_CAVEAT],
        "reason": (
            "Could not derive note-SKU links with publish_time. note_sku_links was unavailable "
            "and notes/skus were insufficient for even a conservative candidate fallback."
        ),
        "recommended_action": (
            "Load note_sku_links or provide notes(note_id, publish_time) plus skus(sku_id) "
            "to enable weak candidate linking."
        ),
    }


def _sales_readiness_issue(con) -> str | None:
    if not _table_exists(con, "daily_sku_sales"):
        return "daily_sku_sales table is missing."
    columns = _table_columns(con, "daily_sku_sales")
    missing = sorted(_SALES_REQUIRED_COLUMNS - columns)
    if missing:
        return "daily_sku_sales is missing required columns: " + ", ".join(missing) + "."
    return None


def _missing_result(
    reason: str,
    caveats: list[str],
    recommended_action: str,
) -> AnalysisResult:
    return AnalysisResult(
        task_id="content_response_curve",
        title="Content Response Curve",
        findings=[
            Finding(
                title="Response curve not judgable",
                conclusion=(
                    "Could not assemble note-anchored response windows from the available data."
                ),
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"note_sku_rows": 0},
                caveats=caveats,
                recommended_action=recommended_action,
            )
        ],
        tables={"response_windows": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
