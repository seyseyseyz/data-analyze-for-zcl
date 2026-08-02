"""Shared descriptive metrics for content-feature groupings."""

_METRICS = (
    "impressions",
    "reads",
    "collects",
    "product_clicks",
    "note_paid_orders",
    "note_gmv",
    "note_refund_amount_pay",
)

_EVIDENCE_FIELDS = (
    "avg_reads",
    "avg_collects",
    "impressions",
    "reads",
    "collects",
    "product_clicks",
    "paid_orders",
    "note_gmv",
    "note_refund_amount_pay",
    "read_rate",
    "collect_rate",
    "read_to_product_click",
    "product_click_to_order",
    "gmv_per_1k_impressions",
    "net_note_gmv",
)


def has_metric_evidence(rows: list[dict[str, object]]) -> bool:
    return any(
        row.get(field) is not None
        for row in rows
        for field in _EVIDENCE_FIELDS
    )


def fetch_group_effects(con, dimension: str) -> tuple[list[dict[str, object]], list[str]]:
    content_columns = _table_columns(con, "content_features")
    if dimension not in content_columns:
        return [], [f"content_features 表缺少 {dimension} 字段。"]

    can_join_notes = (
        "note_id" in content_columns
        and _table_exists(con, "notes")
        and "note_id" in _table_columns(con, "notes")
    )
    if not can_join_notes:
        result = con.sql(
            f"""
            SELECT
              COALESCE(NULLIF(TRIM(CAST({dimension} AS VARCHAR)), ''), 'unknown')
                AS {dimension},
              COUNT(*) AS notes,
              NULL AS matched_notes,
              NULL AS avg_reads,
              NULL AS avg_collects,
              NULL AS impressions,
              NULL AS reads,
              NULL AS collects,
              NULL AS product_clicks,
              NULL AS paid_orders,
              NULL AS note_gmv,
              NULL AS note_refund_amount_pay,
              NULL AS read_rate,
              NULL AS collect_rate,
              NULL AS read_to_product_click,
              NULL AS product_click_to_order,
              NULL AS gmv_per_1k_impressions,
              NULL AS net_note_gmv
            FROM content_features
            GROUP BY 1
            ORDER BY notes DESC, {dimension}
            """
        )
        return _rows(result), ["笔记指标不可用，内容排序仅使用特征计数。"]

    note_columns = _table_columns(con, "notes")
    metric_selects = [
        (
            f"MAX(CAST({metric} AS DOUBLE)) AS {metric}"
            if metric in note_columns
            else f"NULL AS {metric}"
        )
        for metric in _METRICS
    ]
    metric_sql = ",\n              ".join(metric_selects)
    sums = {metric: _sum_expr(note_columns, metric) for metric in _METRICS}
    avg_reads = "AVG(n.reads)" if "reads" in note_columns else "NULL"
    avg_collects = "AVG(n.collects)" if "collects" in note_columns else "NULL"
    result = con.sql(
        f"""
        WITH feature_groups AS (
          SELECT DISTINCT
            CAST(note_id AS VARCHAR) AS note_id,
            COALESCE(NULLIF(TRIM(CAST({dimension} AS VARCHAR)), ''), 'unknown')
              AS {dimension}
          FROM content_features
          WHERE note_id IS NOT NULL
        ),
        note_metrics AS (
          SELECT
            CAST(note_id AS VARCHAR) AS note_id,
            {metric_sql}
          FROM notes
          WHERE note_id IS NOT NULL
          GROUP BY 1
        )
        SELECT
          f.{dimension},
          COUNT(DISTINCT f.note_id) AS notes,
          COUNT(DISTINCT n.note_id) AS matched_notes,
          {avg_reads} AS avg_reads,
          {avg_collects} AS avg_collects,
          {sums["impressions"]} AS impressions,
          {sums["reads"]} AS reads,
          {sums["collects"]} AS collects,
          {sums["product_clicks"]} AS product_clicks,
          {sums["note_paid_orders"]} AS paid_orders,
          {sums["note_gmv"]} AS note_gmv,
          {sums["note_refund_amount_pay"]} AS note_refund_amount_pay,
          CASE WHEN {sums["impressions"]} > 0
            THEN {sums["reads"]} * 1.0 / {sums["impressions"]} END AS read_rate,
          CASE WHEN {sums["reads"]} > 0
            THEN {sums["collects"]} * 1.0 / {sums["reads"]} END AS collect_rate,
          CASE WHEN {sums["reads"]} > 0
            THEN {sums["product_clicks"]} * 1.0 / {sums["reads"]} END
            AS read_to_product_click,
          CASE WHEN {sums["product_clicks"]} > 0
            THEN {sums["note_paid_orders"]} * 1.0 / {sums["product_clicks"]} END
            AS product_click_to_order,
          CASE WHEN {sums["impressions"]} > 0
            THEN {sums["note_gmv"]} * 1000.0 / {sums["impressions"]} END
            AS gmv_per_1k_impressions,
          CASE WHEN {sums["note_gmv"]} IS NOT NULL
              AND {sums["note_refund_amount_pay"]} IS NOT NULL
            THEN {sums["note_gmv"]} - {sums["note_refund_amount_pay"]} END
            AS net_note_gmv
        FROM feature_groups AS f
        LEFT JOIN note_metrics AS n ON f.note_id = n.note_id
        GROUP BY 1
        ORDER BY gmv_per_1k_impressions DESC NULLS LAST,
          read_rate DESC NULLS LAST, notes DESC, f.{dimension}
        """
    )
    rows = [_clean_row(row) for row in _rows(result)]
    limitations = []
    if "reads" not in note_columns or "collects" not in note_columns:
        limitations.append("notes 表的阅读/收藏指标不完整。")
    if rows and not any(row.get("matched_notes") for row in rows):
        limitations.append("没有匹配的笔记指标，内容效果不可判断。")
    return rows, limitations


def _sum_expr(columns: set[str], metric: str) -> str:
    return f"SUM(n.{metric})" if metric in columns else "NULL"


def _clean_row(row: dict[str, object]) -> dict[str, object]:
    cleaned = dict(row)
    for key, value in cleaned.items():
        if isinstance(value, float):
            cleaned[key] = round(value, 4)
    return cleaned


def _rows(result) -> list[dict[str, object]]:
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
