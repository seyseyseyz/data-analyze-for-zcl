from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows = _build_sections(con)
    finally:
        con.close()

    ready_sections = [row for row in rows if row["status"] == "ready"]
    evidence_count = sum(int(row["evidence_count"]) for row in ready_sections)
    limitations = [
        f"{row['section']} 模块缺少源数据。"
        for row in rows
        if row["status"] != "ready"
    ]

    return AnalysisResult(
        task_id="weekly_business_review",
        title="每周经营复盘",
        findings=[
            Finding(
                title="每周复盘模块已汇总",
                conclusion=(
                    f"已汇总 {len(rows)} 个每周复盘模块，其中 "
                    f"{len(ready_sections)} 个有源数据。"
                ),
                evidence_strength=score_evidence(
                    evidence_count, has_controls=False, confounder_count=2
                ),
                key_numbers={
                    "sections": len(rows),
                    "ready_sections": len(ready_sections),
                    "evidence_items": evidence_count,
                },
                caveats=[
                    "每周复盘模块汇总的是描述性输出，不能证明因果关系。"
                ],
                recommended_action=(
                    "将已有数据的模块作为本周经营叙事，把缺失模块转成导入或埋点任务。"
                ),
            )
        ],
        tables={"weekly_sections": rows},
        limitations=limitations,
    )


def _build_sections(con) -> list[dict[str, object]]:
    return [
        _data_quality_section(con),
        _baseline_section(con),
        _funnel_section(con),
        _product_opportunity_section(con),
    ]


def _data_quality_section(con) -> dict[str, object]:
    tables = _table_counts(con)
    empty_tables = [table for table in tables if int(table["rows"]) == 0]
    return {
        "section": "data_quality",
        "source": "data_quality_check",
        "status": "ready" if tables else "missing",
        "metric": "tables_loaded",
        "value": len(tables),
        "evidence_count": len(tables),
        "summary": (
            f"已加载 {len(tables)} 张表；空表："
            f"{', '.join(table['table'] for table in empty_tables) if empty_tables else '无'}。"
        )
        if tables
        else "没有发现 DuckDB 表。",
    }


def _baseline_section(con) -> dict[str, object]:
    if not _table_exists(con, "notes"):
        return _missing_section("baseline", "account_baseline", "缺少 notes 表。")

    columns = _table_columns(con, "notes")
    if not {"note_id", "publish_time", "reads"}.issubset(columns):
        return _missing_section("baseline", "account_baseline", "notes 表字段不完整。")

    row = con.sql(
        """
        SELECT
          COUNT(*) AS posts,
          COUNT(DISTINCT CAST(publish_time AS DATE)) AS active_days,
          CAST(MIN(CAST(publish_time AS DATE)) AS VARCHAR) AS first_date,
          CAST(MAX(CAST(publish_time AS DATE)) AS VARCHAR) AS last_date,
          AVG(CAST(reads AS DOUBLE)) AS avg_reads
        FROM notes
        WHERE publish_time IS NOT NULL
        """
    ).fetchone()
    posts, active_days, first_date, last_date, avg_reads = row
    avg_reads_value = round(float(avg_reads), 2) if avg_reads is not None else None
    return {
        "section": "baseline",
        "source": "account_baseline",
        "status": "ready" if posts else "missing",
        "metric": "posts",
        "value": int(posts),
        "evidence_count": int(posts),
        "summary": (
            f"{int(posts)} 篇笔记覆盖 {int(active_days)} 个活跃发布日，"
            f"日期从 {first_date} 到 {last_date}；平均阅读 {_display_number(avg_reads_value)}。"
        )
        if posts
        else "没有可用的带日期笔记。",
    }


def _funnel_section(con) -> dict[str, object]:
    if not _table_exists(con, "notes"):
        return _missing_section("funnel", "note_funnel", "缺少 notes 表。")

    columns = _table_columns(con, "notes")
    required = {"impressions", "reads", "likes", "collects", "comments"}
    if not required.issubset(columns):
        return _missing_section("funnel", "note_funnel", "漏斗字段不完整。")

    row = con.sql(
        """
        SELECT
          COUNT(*) AS notes,
          AVG(CASE WHEN impressions > 0 THEN reads * 1.0 / impressions END)
            AS avg_read_rate,
          AVG(CASE WHEN reads > 0 THEN likes * 1.0 / reads END) AS avg_like_rate,
          AVG(CASE WHEN reads > 0 THEN collects * 1.0 / reads END) AS avg_collect_rate,
          AVG(CASE WHEN reads > 0 THEN comments * 1.0 / reads END) AS avg_comment_rate
        FROM notes
        """
    ).fetchone()
    notes, avg_read_rate, avg_like_rate, avg_collect_rate, avg_comment_rate = row
    read_rate = _rounded(avg_read_rate)
    like_rate = _rounded(avg_like_rate)
    collect_rate = _rounded(avg_collect_rate)
    comment_rate = _rounded(avg_comment_rate)
    return {
        "section": "funnel",
        "source": "note_funnel",
        "status": "ready" if notes else "missing",
        "metric": "avg_collect_rate",
        "value": collect_rate,
        "evidence_count": int(notes),
        "summary": (
            f"平均阅读率 {_display_number(read_rate)}，点赞率 {_display_number(like_rate)}，"
            f"收藏率 {_display_number(collect_rate)}，评论率 {_display_number(comment_rate)}。"
        )
        if notes
        else "没有可用的笔记漏斗数据。",
    }


def _product_opportunity_section(con) -> dict[str, object]:
    if not _table_exists(con, "daily_sku_sales"):
        return _missing_section(
            "product_opportunity",
            "product_opportunity_matrix",
            "缺少 daily_sku_sales 表。",
        )

    sales_columns = _table_columns(con, "daily_sku_sales")
    if "sku_id" not in sales_columns:
        return _missing_section(
            "product_opportunity",
            "product_opportunity",
            "daily_sku_sales 表缺少 sku_id。",
        )

    has_skus = _table_exists(con, "skus")
    sku_columns = _table_columns(con, "skus") if has_skus else set()
    join_clause = (
        "LEFT JOIN skus AS s ON CAST(d.sku_id AS VARCHAR) = CAST(s.sku_id AS VARCHAR)"
        if has_skus and {"sku_id", "sku_name"}.issubset(sku_columns)
        else ""
    )
    name_expr = (
        "COALESCE(MAX(CAST(s.sku_name AS VARCHAR)), CAST(d.sku_id AS VARCHAR))"
        if join_clause
        else "CAST(d.sku_id AS VARCHAR)"
    )
    units_expr = (
        "SUM(CAST(d.units AS DOUBLE))"
        if "units" in sales_columns
        else "NULL"
    )
    gmv_expr = (
        "SUM(CAST(d.gmv AS DOUBLE))"
        if "gmv" in sales_columns
        else "NULL"
    )
    metric_predicates = []
    if "units" in sales_columns:
        metric_predicates.append("d.units IS NOT NULL")
    if "gmv" in sales_columns:
        metric_predicates.append("d.gmv IS NOT NULL")
    metric_where = " OR ".join(metric_predicates) or "FALSE"
    row = con.sql(
        f"""
        SELECT
          CAST(d.sku_id AS VARCHAR) AS sku_id,
          {name_expr} AS sku_name,
          {units_expr} AS units,
          {gmv_expr} AS gmv,
          COUNT(*) AS sales_days
        FROM daily_sku_sales AS d
        {join_clause}
        WHERE d.sku_id IS NOT NULL
          AND ({metric_where})
        GROUP BY 1
        ORDER BY units DESC NULLS LAST, gmv DESC NULLS LAST, sku_id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return _missing_section(
            "product_opportunity",
            "product_opportunity_matrix",
            "daily_sku_sales 表为空或没有可用的 SKU 销售记录。",
        )

    sku_id, sku_name, units, gmv, sales_days = row
    return {
        "section": "product_opportunity",
        "source": "product_opportunity_matrix",
        "status": "ready",
        "metric": "top_sku_units",
        "value": round(float(units), 4) if units is not None else None,
        "evidence_count": int(sales_days),
        "summary": (
            f"{sku_name} ({sku_id}) 在观测 SKU 销售中领先，销量 "
            f"{_display_number(_rounded(units))}，GMV {_display_number(_rounded(gmv, 2))}。"
        ),
    }


def _missing_section(section: str, source: str, summary: str) -> dict[str, object]:
    return {
        "section": section,
        "source": source,
        "status": "missing",
        "metric": None,
        "value": None,
        "evidence_count": 0,
        "summary": summary,
    }


def _table_counts(con) -> list[dict[str, object]]:
    rows = []
    for (table_name,) in con.sql("SHOW TABLES").fetchall():
        row_count = con.sql(
            f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}"
        ).fetchone()[0]
        rows.append({"table": table_name, "rows": int(row_count)})
    return rows


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}


def _rounded(value: object | None, digits: int = 4) -> float | None:
    return round(float(value), digits) if value is not None else None


def _display_number(value: object | None) -> str:
    return "未知" if value is None else str(value)


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
