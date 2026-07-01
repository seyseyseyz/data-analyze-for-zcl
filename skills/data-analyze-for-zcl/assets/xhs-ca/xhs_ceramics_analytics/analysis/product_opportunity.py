from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows, limitations, has_sales = _fetch_product_opportunities(con)
    finally:
        con.close()

    return AnalysisResult(
        task_id="product_opportunity_matrix",
        title="商品机会矩阵",
        findings=[
            Finding(
                title="SKU 机会已排序",
                conclusion="已按销售响应对 SKU 排序，并标记初步机会类型。",
                evidence_strength=(
                    EvidenceStrength.MEDIUM
                    if rows and has_sales
                    else EvidenceStrength.NOT_JUDGABLE
                ),
                key_numbers={"sku_count": len(rows)},
                caveats=["有显式 note-SKU 关联后，内容表现象限会更可靠。"],
            )
        ],
        tables={"product_opportunities": rows},
        limitations=limitations,
    )


def _fetch_product_opportunities(
    con,
) -> tuple[list[dict[str, object]], list[str], bool]:
    has_sales_table = _table_exists(con, "daily_sku_sales")
    sales_columns = _table_columns(con, "daily_sku_sales") if has_sales_table else set()
    has_sales = has_sales_table and {"sku_id", "units", "gmv"}.issubset(sales_columns)

    if _table_exists(con, "skus"):
        sku_columns = _table_columns(con, "skus")
        if "sku_id" not in sku_columns:
            return [], ["skus 表缺少 sku_id 字段。"], False

        name_expr = (
            "COALESCE(CAST(s.sku_name AS VARCHAR), CAST(s.sku_id AS VARCHAR))"
            if "sku_name" in sku_columns
            else "CAST(s.sku_id AS VARCHAR)"
        )
        if has_sales:
            result = con.sql(
                f"""
                WITH sales AS (
                  SELECT
                    CAST(sku_id AS VARCHAR) AS sku_id,
                    SUM(CAST(units AS DOUBLE)) AS units,
                    SUM(CAST(gmv AS DOUBLE)) AS gmv
                  FROM daily_sku_sales
                  GROUP BY 1
                )
                SELECT
                  CAST(s.sku_id AS VARCHAR) AS sku_id,
                  {name_expr} AS sku_name,
                  COALESCE(sales.units, 0.0) AS units,
                  COALESCE(sales.gmv, 0.0) AS gmv,
                  CASE
                    WHEN COALESCE(sales.units, 0.0) >= 3 THEN 'sales_response_present'
                    ELSE 'needs_more_content_or_data'
                  END AS opportunity_type
                FROM skus AS s
                LEFT JOIN sales ON CAST(s.sku_id AS VARCHAR) = sales.sku_id
                ORDER BY gmv DESC NULLS LAST, units DESC NULLS LAST, sku_id
                """
            )
            return _rows(result), [], True

        result = con.sql(
            f"""
            SELECT
              CAST(s.sku_id AS VARCHAR) AS sku_id,
              {name_expr} AS sku_name,
              NULL AS units,
              NULL AS gmv,
              'needs_sales_data' AS opportunity_type
            FROM skus AS s
            ORDER BY sku_id
            """
        )
        limitation = (
            "daily_sku_sales 表的 units/gmv 字段不完整。"
            if has_sales_table
            else "缺少 daily_sku_sales 表。"
        )
        return _rows(result), [limitation], False

    if has_sales:
        result = con.sql(
            """
            SELECT
              CAST(sku_id AS VARCHAR) AS sku_id,
              CAST(sku_id AS VARCHAR) AS sku_name,
              SUM(CAST(units AS DOUBLE)) AS units,
              SUM(CAST(gmv AS DOUBLE)) AS gmv,
              CASE
                WHEN SUM(CAST(units AS DOUBLE)) >= 3 THEN 'sales_response_present'
                ELSE 'needs_more_content_or_data'
              END AS opportunity_type
            FROM daily_sku_sales
            GROUP BY 1, 2
            ORDER BY gmv DESC NULLS LAST, units DESC NULLS LAST, sku_id
            """
        )
        return _rows(result), ["缺少 skus 表，SKU 名称使用 sku_id。"], True

    return [], ["缺少 skus 表和可用的 daily_sku_sales 数据。"], False


def _rows(result) -> list[dict[str, object]]:
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
