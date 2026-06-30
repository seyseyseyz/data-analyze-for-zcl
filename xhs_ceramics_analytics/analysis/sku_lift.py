from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

_WINDOW_SPECS = (
    ("d0_1", -1, 0, 0, 1),
    ("d1_3", -3, 0, 1, 4),
    ("d4_7", -4, 0, 4, 8),
    ("d8_14", -7, 0, 8, 15),
)

_SALES_REQUIRED_COLUMNS = {"date", "sku_id", "units"}
_NOTES_REQUIRED_COLUMNS = {"note_id", "publish_time"}
_LINK_REQUIRED_COLUMNS = {"note_id", "sku_id"}
_SKUS_REQUIRED_COLUMNS = {"sku_id"}

_REAL_LINK_CAVEAT = (
    "Observed lifts are descriptive note-linked sales windows and do not prove causal lift."
)
_CANDIDATE_LINK_CAVEAT = (
    "No explicit note_sku_links table was available, so note-to-SKU matching uses a "
    "single first-SKU candidate fallback with weak attribution."
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
                    "Load daily_sku_sales with date, sku_id, and units before reading lift."
                ),
            )

        link_context = _link_context(con)
        if link_context["query"] is None:
            return _missing_result(
                reason=str(link_context["reason"]),
                caveats=list(link_context["caveats"]),
                recommended_action=str(link_context["recommended_action"]),
            )

        rows = _window_rows(con, str(link_context["query"]))
    finally:
        con.close()

    if not rows:
        return _missing_result(
            reason=(
                "No note-SKU links with publish_time and matching sales rows were available "
                "for lift windows."
            ),
            caveats=list(link_context["caveats"]),
            recommended_action=str(link_context["recommended_action"]),
        )

    evidence_strength = score_evidence(
        len({(row["note_id"], row["sku_id"]) for row in rows}),
        has_controls=False,
        confounder_count=1 if link_context["source"] == "note_sku_links" else 3,
    )
    findings = [
        Finding(
            title="Descriptive note-anchored SKU lift windows",
            conclusion=(
                f"Built descriptive lift windows for "
                f"{len({(row['note_id'], row['sku_id']) for row in rows})} note-SKU links "
                "anchored to note publish dates."
            ),
            evidence_strength=evidence_strength,
            key_numbers=_key_numbers(rows, str(link_context["source"])),
            caveats=list(link_context["caveats"]),
            recommended_action=(
                "Treat these as weak directional signals and add explicit note-SKU linking "
                "or holdout logic before using them for stronger attribution claims."
            ),
        )
    ]

    return AnalysisResult(
        task_id="sku_counterfactual_lift",
        title="SKU Counterfactual Lift",
        findings=findings,
        tables={"sku_lift": rows},
        limitations=[
            "Lift windows are observational and remain sensitive to seasonality, pricing, "
            "stockouts, and overlapping marketing activity."
        ],
    )


def _window_rows(con, link_query: str) -> list[dict[str, object]]:
    result = con.sql(
        f"""
        WITH link_candidates AS (
          {link_query}
        ),
        window_specs AS (
          SELECT *
          FROM (
            VALUES
              ('d0_1', -1, 0, 0, 1),
              ('d1_3', -3, 0, 1, 4),
              ('d4_7', -4, 0, 4, 8),
              ('d8_14', -7, 0, 8, 15)
          ) AS t(window_name, pre_start_day, pre_end_day, post_start_day, post_end_day)
        ),
        windowed AS (
          SELECT
            lc.note_id,
            lc.sku_id,
            CAST(lc.publish_time AS VARCHAR) AS publish_time,
            ws.window_name,
            COALESCE(
              SUM(
                CASE
                  WHEN sales.date >= CAST(lc.publish_time AS DATE) + ws.pre_start_day * INTERVAL '1 day'
                   AND sales.date < CAST(lc.publish_time AS DATE) + ws.pre_end_day * INTERVAL '1 day'
                  THEN CAST(sales.units AS DOUBLE)
                  ELSE 0
                END
              ),
              0.0
            ) AS pre_units,
            COALESCE(
              SUM(
                CASE
                  WHEN sales.date >= CAST(lc.publish_time AS DATE) + ws.post_start_day * INTERVAL '1 day'
                   AND sales.date < CAST(lc.publish_time AS DATE) + ws.post_end_day * INTERVAL '1 day'
                  THEN CAST(sales.units AS DOUBLE)
                  ELSE 0
                END
              ),
              0.0
            ) AS post_units
          FROM link_candidates AS lc
          CROSS JOIN window_specs AS ws
          LEFT JOIN daily_sku_sales AS sales
            ON CAST(sales.sku_id AS VARCHAR) = lc.sku_id
          GROUP BY lc.note_id, lc.sku_id, lc.publish_time, ws.window_name
        )
        SELECT
          note_id,
          sku_id,
          publish_time,
          window_name AS window,
          pre_units,
          post_units,
          post_units - pre_units AS absolute_lift,
          CASE
            WHEN pre_units > 0 THEN (post_units - pre_units) / pre_units
          END AS relative_lift
        FROM windowed
        ORDER BY
          note_id,
          sku_id,
          CASE window_name
            WHEN 'd0_1' THEN 1
            WHEN 'd1_3' THEN 2
            WHEN 'd4_7' THEN 3
            WHEN 'd8_14' THEN 4
            ELSE 99
          END
        """
    )
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _key_numbers(rows: list[dict[str, object]], link_source: str) -> dict[str, object]:
    key_numbers: dict[str, object] = {
        "note_sku_links": len({(row["note_id"], row["sku_id"]) for row in rows}),
        "windows": len(rows),
        "link_source": link_source,
    }
    first_long_tail = next((row for row in rows if row["window"] == "d8_14"), None)
    if first_long_tail is not None:
        key_numbers["first_d8_14_post_units"] = first_long_tail["post_units"]
        key_numbers["first_d8_14_absolute_lift"] = first_long_tail["absolute_lift"]
    return key_numbers


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
                "so lift windows can anchor to real note dates."
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
        task_id="sku_counterfactual_lift",
        title="SKU Counterfactual Lift",
        findings=[
            Finding(
                title="SKU lift not judgable",
                conclusion=(
                    "Could not assemble note-anchored SKU lift windows from the available data."
                ),
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={"note_sku_links": 0, "windows": 0},
                caveats=caveats,
                recommended_action=recommended_action,
            )
        ],
        tables={"sku_lift": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
