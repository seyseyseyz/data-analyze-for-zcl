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
    "观测到的销量变化只是笔记关联销售窗口的描述性结果，不能证明因果。"
)
_CANDIDATE_LINK_CAVEAT = (
    "缺少显式 note_sku_links 表，笔记到 SKU 的匹配使用首个 SKU 候选兜底，归因较弱。"
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
                    "先导入包含 date、sku_id 和 units 的 daily_sku_sales，再读取销量观察窗口。"
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
                "没有可用于销量观察窗口的 note-SKU 关联、publish_time 和匹配销售数据。"
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

    evidence_strength = score_evidence(
        len({(row["note_id"], row["sku_id"]) for row in rows}),
        has_controls=False,
        confounder_count=1 if link_context["source"] == "note_sku_links" else 3,
    )
    findings = [
        Finding(
            title="笔记锚定的 SKU 销量响应窗口",
            conclusion=(
                f"已基于笔记发布时间，为 "
                f"{len({(row['note_id'], row['sku_id']) for row in rows})} 组 note-SKU 关联"
                "生成发布前后的销量观察窗口。"
            ),
            evidence_strength=evidence_strength,
            evidence_reason=_evidence_reason(str(link_context["source"])),
            key_numbers=_key_numbers(rows, str(link_context["source"])),
            caveats=list(link_context["caveats"]),
            recommended_action=(
                "先把这些结果当作弱方向信号；如果要做更强归因，需要补充显式 note-SKU 关联或留出对照逻辑。"
            ),
        )
    ]

    return AnalysisResult(
        task_id="sku_counterfactual_lift",
        title="SKU 销量响应",
        findings=findings,
        tables={"sku_lift": rows},
        limitations=[
            "销量响应窗口是观测性结果，仍会受到季节性、价格、缺货和重叠营销活动影响。"
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
            ) AS post_units,
            COUNT(
              DISTINCT CASE
                WHEN (
                  sales.date >= CAST(lc.publish_time AS DATE) + ws.pre_start_day * INTERVAL '1 day'
                  AND sales.date < CAST(lc.publish_time AS DATE) + ws.pre_end_day * INTERVAL '1 day'
                ) OR (
                  sales.date >= CAST(lc.publish_time AS DATE) + ws.post_start_day * INTERVAL '1 day'
                  AND sales.date < CAST(lc.publish_time AS DATE) + ws.post_end_day * INTERVAL '1 day'
                )
                THEN sales.date
              END
            ) AS matched_sales_days
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
          matched_sales_days,
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


def _has_matching_sales_dates(rows: list[dict[str, object]]) -> bool:
    return any((row.get("matched_sales_days") or 0) > 0 for row in rows)


def _strip_internal_columns(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in row.items() if key != "matched_sales_days"}
        for row in rows
    ]


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
                "note_sku_links 已存在，但缺少可用的 note_id/sku_id 关联或 notes.publish_time。"
            ),
            "recommended_action": (
                "补齐 note_sku_links.note_id、note_sku_links.sku_id 和 notes.publish_time，"
                "让销量观察窗口能锚定真实笔记日期。"
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
        task_id="sku_counterfactual_lift",
        title="SKU 销量响应",
        findings=[
            Finding(
                title="SKU 销量响应不可判断",
                conclusion=(
                    "无法从当前数据组装笔记锚定的 SKU 销量观察窗口。"
                ),
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                evidence_reason=(
                    "缺少销量、发布时间或 note-SKU 关联数据，"
                    "当前结果只适合指导先补哪类数据。"
                ),
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


def _evidence_reason(link_source: str) -> str:
    if link_source == "note_sku_links":
        return (
            "有显式 note-SKU 关联和发布前后销量窗口，"
            "但缺少受控对照，所以适合作为当前经营判断的辅助证据。"
        )
    return (
        "有发布前后销量窗口，但 note-SKU 关联由候选 SKU 兜底，"
        "适合先转成下周受控实验验证。"
    )


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
