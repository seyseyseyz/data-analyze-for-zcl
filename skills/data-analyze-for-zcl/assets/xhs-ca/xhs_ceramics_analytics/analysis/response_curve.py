from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence
from xhs_ceramics_analytics.evidence import score_reliability

_SALES_REQUIRED_COLUMNS = {"date", "sku_id", "units"}
_NOTES_REQUIRED_COLUMNS = {"note_id", "publish_time"}
_LINK_REQUIRED_COLUMNS = {"note_id", "sku_id"}
_SKUS_REQUIRED_COLUMNS = {"sku_id"}

_REAL_LINK_CAVEAT = (
    "响应窗口是笔记关联销售窗口的描述性结果，不能隔离因果影响。"
)
_CANDIDATE_LINK_CAVEAT = (
    "缺少显式 note_sku_links 表，响应窗口使用首个 SKU 候选兜底，归因很弱。"
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
                    "先导入包含 date、sku_id 和 units 的 daily_sku_sales，再读取响应窗口。"
                ),
            )

        link_context = _link_context(con)
        if link_context["query"] is None:
            return _missing_result(
                reason=str(link_context["reason"]),
                caveats=list(link_context["caveats"]),
                recommended_action=str(link_context["recommended_action"]),
            )

        has_title = _table_exists(con, "notes") and "title" in _table_columns(con, "notes")
        rows = _response_rows(con, str(link_context["query"]), has_title)
    finally:
        con.close()

    if not rows:
        return _missing_result(
            reason=(
                "没有可用于响应窗口的 note-SKU 关联、publish_time 和匹配销售数据。"
            ),
            caveats=list(link_context["caveats"]),
            recommended_action=str(link_context["recommended_action"]),
        )
    if not _has_matching_sales_dates(rows):
        return _missing_result(
            reason="没有匹配销售日期，无法区分真实 0 销量和销售数据缺失。",
            caveats=list(link_context["caveats"]),
            recommended_action="先补齐这些 note-SKU 关联在观察窗口内的 SKU 日销售记录。",
        )
    rows = _strip_internal_columns(rows)

    return AnalysisResult(
        task_id="content_response_curve",
        title="内容响应曲线",
        findings=[
            Finding(
                title="笔记锚定的描述性响应窗口",
                conclusion=(
                    f"已为 {qty(len(rows))} 行 note-SKU 数据生成笔记锚定响应窗口，"
                    "使用发布时间窗口而不是固定日历锚点。"
                ),
                evidence_strength=score_evidence(
                    len(rows),
                    has_controls=False,
                    confounder_count=1 if link_context["source"] == "note_sku_links" else 3,
                ),
                descriptive_reliability=score_reliability(len(rows)),
                evidence_reason=_evidence_reason(str(link_context["source"])),
                key_numbers={
                    "note_sku_rows": len(rows),
                    "link_source": link_context["source"],
                    "d8_14_rows": sum(1 for row in rows if row["d8_14_units"] is not None),
                },
                caveats=list(link_context["caveats"]),
                recommended_action=(
                    "先把这些窗口作为弱时间诊断，再用显式关联或受控实验验证有希望的模式。"
                ),
            )
        ],
        tables={"response_windows": rows},
        limitations=[
            "响应窗口仍是观测性结果，可能被重叠笔记、缺货或与目标内容无关的需求变化扭曲。"
        ],
    )


def _response_rows(con, link_query: str, has_title: bool) -> list[dict[str, object]]:
    # Display the human note title; fall back to the internal id only when the
    # notes export carries no title column (graceful degradation).
    if has_title:
        note_select = "COALESCE(n_meta.title, lc.note_id) AS note_title"
        note_join = (
            "LEFT JOIN notes AS n_meta "
            "ON CAST(n_meta.note_id AS VARCHAR) = lc.note_id"
        )
        group_extra = ", n_meta.title"
    else:
        note_select = "lc.note_id AS note_title"
        note_join = ""
        group_extra = ""
    result = con.sql(
        f"""
        WITH link_candidates AS (
          {link_query}
        )
        SELECT
          {note_select},
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
          ) AS d8_14_units,
          COUNT(
            DISTINCT CASE
              WHEN sales.date >= CAST(lc.publish_time AS DATE)
               AND sales.date < CAST(lc.publish_time AS DATE) + INTERVAL '15 days'
              THEN sales.date
            END
          ) AS matched_sales_days
        FROM link_candidates AS lc
        LEFT JOIN daily_sku_sales AS sales
          ON CAST(sales.sku_id AS VARCHAR) = lc.sku_id
        {note_join}
        GROUP BY lc.note_id, lc.sku_id, lc.publish_time{group_extra}
        ORDER BY lc.note_id, lc.sku_id, lc.publish_time
        """
    )
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _has_matching_sales_dates(rows: list[dict[str, object]]) -> bool:
    return any((row.get("matched_sales_days") or 0) > 0 for row in rows)


def _strip_internal_columns(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in row.items() if key != "matched_sales_days"}
        for row in rows
    ]


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
                "note_sku_links 已存在，但缺少可用的 note_id/sku_id 关联或 notes.publish_time。"
            ),
            "recommended_action": (
                "补齐 note_sku_links.note_id、note_sku_links.sku_id 和 notes.publish_time，"
                "让响应窗口能锚定真实笔记日期。"
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
            "无法推导带 publish_time 的 note-SKU 关联；note_sku_links 不可用，notes/skus "
            "也不足以支持保守候选兜底。"
        ),
        "recommended_action": (
            "导入 note_sku_links，或至少提供 notes(note_id, publish_time) 与 skus(sku_id)，"
            "以启用弱候选关联。"
        ),
    }


def _sales_readiness_issue(con) -> str | None:
    if not _table_exists(con, "daily_sku_sales"):
        return "缺少 daily_sku_sales 表。"
    columns = _table_columns(con, "daily_sku_sales")
    missing = sorted(_SALES_REQUIRED_COLUMNS - columns)
    if missing:
        return "daily_sku_sales 表缺少必要字段：" + ", ".join(missing) + "。"
    return None


def _missing_result(
    reason: str,
    caveats: list[str],
    recommended_action: str,
) -> AnalysisResult:
    return AnalysisResult(
        task_id="content_response_curve",
        title="内容响应曲线",
        findings=[
            Finding(
                title="响应曲线不可判断",
                conclusion=(
                    "无法从当前数据组装笔记锚定的响应窗口。"
                ),
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                evidence_reason=(
                    "缺少销量、发布时间或 note-SKU 关联数据，"
                    "当前结果只适合指导先补哪类数据。"
                ),
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


def _evidence_reason(link_source: str) -> str:
    if link_source == "note_sku_links":
        return (
            "有显式 note-SKU 关联和笔记发布时间窗口，"
            "但仍是观测性响应曲线，适合辅助判断后续实验节奏。"
        )
    return (
        "有笔记发布时间和 SKU 数据，但 note-SKU 关联由候选 SKU 兜底，"
        "适合先作为时间窗口线索，再用受控实验验证。"
    )


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
