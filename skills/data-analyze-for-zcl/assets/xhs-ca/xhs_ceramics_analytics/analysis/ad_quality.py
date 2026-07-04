from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence
from xhs_ceramics_analytics.evidence import score_reliability


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "ad_performance_daily"):
            return _missing_result("缺少 ad_performance_daily 表。")
        rows = _quality_rows(con)
    finally:
        con.close()

    row = rows[0] if rows else {}
    sample_size = int(row.get("rows") or 0)
    has_gmv = bool(row.get("has_gmv_metrics"))
    evidence_strength = score_evidence(
        sample_size=sample_size,
        has_controls=has_gmv,
        confounder_count=1 if has_gmv else 2,
    )
    descriptive_reliability = score_reliability(sample_size)

    return AnalysisResult(
        task_id="ad_data_quality_check",
        title="投放数据可用性检查",
        findings=[
            Finding(
                title="投放导出已完成结构检查",
                conclusion=(
                    f"当前投放表有 {qty(sample_size)} 行，识别为 {row.get('detected_grain', 'unknown')} 粒度。"
                ),
                evidence_strength=evidence_strength,
                descriptive_reliability=descriptive_reliability,
                evidence_reason=(
                    "该检查只判断字段和粒度可用性，不判断投放效果好坏。"
                ),
                key_numbers={
                    "rows": sample_size,
                    "total_spend": row.get("total_spend"),
                    "detected_grain": row.get("detected_grain"),
                },
                caveats=_quality_caveats(row),
                recommended_action=_recommended_next_import(row),
            )
        ],
        tables={"ad_data_quality": rows},
        limitations=[],
    )


def _quality_rows(con) -> list[dict[str, object]]:
    columns = _table_columns(con, "ad_performance_daily")
    spend_expr = _sum_expr(columns, "spend")
    result = con.sql(
        f"""
        SELECT
          COUNT(*) AS rows,
          MIN(CAST(date AS DATE)) AS first_date,
          MAX(CAST(date AS DATE)) AS last_date,
          {spend_expr} AS total_spend
        FROM ad_performance_daily
        """
    )
    rows, first_date, last_date, total_spend = result.fetchone()
    quality = {
        "rows": int(rows),
        "first_date": str(first_date) if first_date is not None else None,
        "last_date": str(last_date) if last_date is not None else None,
        "total_spend": round(float(total_spend), 4) if total_spend is not None else None,
        "detected_grain": _detect_grain(columns),
        "has_exposure_metrics": "impressions" in columns,
        "has_click_metrics": {"impressions", "clicks"}.issubset(columns),
        "has_conversion_metrics": bool({"conversions_optional", "orders_optional"} & columns),
        "has_gmv_metrics": bool({"gmv_optional", "roi_optional", "roas_optional"} & columns),
        "note_link_rows": _non_null_count(con, "note_id_optional", columns),
        "sku_link_rows": _non_null_count(con, "sku_id_optional", columns),
        "campaign_link_rows": _non_null_count(con, "campaign_name_optional", columns),
        "creative_link_rows": _non_null_count(con, "creative_name_optional", columns),
    }
    return [quality]


def _detect_grain(columns: set[str]) -> str:
    if "sku_id_optional" in columns:
        return "sku"
    if "product_id_optional" in columns:
        return "product"
    if "note_id_optional" in columns or "note_url_optional" in columns:
        return "note"
    if "creative_id_optional" in columns or "creative_name_optional" in columns:
        return "creative"
    if "unit_id_optional" in columns or "unit_name_optional" in columns:
        return "unit"
    if "campaign_id_optional" in columns or "campaign_name_optional" in columns:
        return "campaign"
    return "unknown"


def _recommended_next_import(row: dict[str, object]) -> str:
    if not row.get("has_click_metrics"):
        return "下一次导出请勾选曝光量和点击量，先补齐基础点击效率。"
    if not row.get("has_gmv_metrics"):
        return "下一次导出请勾选成交金额、成交订单数或 ROI 字段，才能判断投产。"
    if not row.get("note_link_rows") and not row.get("sku_link_rows"):
        return "如果后台支持，请补充笔记ID、笔记链接、商品ID 或 SKU ID，提升关联分析可信度。"
    return "当前投放导出可用于投放效率分析；后续可继续补充更细的创意或 SKU 维度。"


def _quality_caveats(row: dict[str, object]) -> list[str]:
    caveats = []
    if not row.get("has_gmv_metrics"):
        caveats.append("缺少 GMV/ROI/ROAS 字段，不能判断投产。")
    if not row.get("note_link_rows") and not row.get("sku_link_rows"):
        caveats.append("缺少笔记或 SKU 关联，只能做投放平台侧效率分析。")
    return caveats


def _sum_expr(columns: set[str], column: str) -> str:
    if column not in columns:
        return "NULL"
    return f"SUM(CAST({column} AS DOUBLE))"


def _non_null_count(con, column: str, columns: set[str]) -> int:
    if column not in columns:
        return 0
    return int(
        con.sql(
            f"SELECT COUNT(*) FROM ad_performance_daily WHERE {column} IS NOT NULL"
        ).fetchone()[0]
    )


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="ad_data_quality_check",
        title="投放数据可用性检查",
        findings=[
            Finding(
                title="投放数据不可判断",
                conclusion="当前没有可识别的投放效果导出表。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                evidence_reason="缺少投放事实表，当前结果只适合指导补数。",
                key_numbers={"rows": 0},
                caveats=[reason],
                recommended_action="先导入包含日期、消耗、曝光或点击字段的投放导出。",
            )
        ],
        tables={"ad_data_quality": []},
        limitations=[reason],
    )


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
