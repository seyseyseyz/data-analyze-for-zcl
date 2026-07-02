from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.db.sql_helpers import numeric_expr
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence


def classify_budget_action(
    spend: float | None,
    clicks: float | None,
    gmv: float | None,
    roas: float | None,
    active_days: int,
) -> str:
    if spend is None or spend <= 0 or clicks is None:
        return "needs_data"
    if gmv is None or roas is None:
        return "needs_data"
    if active_days < 2 and roas >= 3:
        return "hold"
    if spend >= 100 and roas >= 3 and gmv > 0:
        return "increase"
    if spend >= 100 and (clicks < 20 or gmv <= 0 or roas < 1):
        return "reduce"
    return "hold"


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "ad_performance_daily"):
            return _missing_result("缺少 ad_performance_daily 表。")
        source = "ad_metrics" if _table_exists(con, "ad_metrics") else "ad_performance_daily"
        rows = _efficiency_rows(con, source)
    finally:
        con.close()

    for row in rows:
        row["budget_action"] = classify_budget_action(
            _float_or_none(row.get("spend")),
            _float_or_none(row.get("clicks")),
            _float_or_none(row.get("gmv_optional")),
            _float_or_none(row.get("roas_calc")),
            int(row.get("paid_active_days") or 0),
        )

    total_spend = sum(float(row.get("spend") or 0) for row in rows)
    total_gmv = sum(float(row.get("gmv_optional") or 0) for row in rows)
    has_return = any(row.get("gmv_optional") is not None for row in rows)
    evidence_strength = score_evidence(
        sample_size=sum(int(row.get("paid_active_days") or 0) for row in rows),
        has_controls=has_return,
        confounder_count=1 if has_return else 3,
    )

    return AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[
            Finding(
                title="投放消耗和投产效率已汇总",
                conclusion=(
                    f"已汇总 {len(rows)} 个投放对象，总消耗 {round(total_spend, 2)}，"
                    f"可见成交金额 {round(total_gmv, 2)}。"
                ),
                evidence_strength=evidence_strength,
                evidence_reason=_evidence_reason(has_return),
                key_numbers={
                    "rows": len(rows),
                    "spend": round(total_spend, 2),
                    "gmv_optional": round(total_gmv, 2) if has_return else None,
                },
                caveats=_caveats(rows, has_return),
                recommended_action=_recommended_action(rows, has_return),
            )
        ],
        tables={"paid_traffic_efficiency": rows},
        limitations=[],
    )


def _efficiency_rows(con, source: str) -> list[dict[str, object]]:
    columns = _table_columns(con, source)
    dimensions = [
        column
        for column in (
            "campaign_name_optional",
            "creative_name_optional",
            "note_id_optional",
            "sku_id_optional",
        )
        if column in columns
    ]
    if not dimensions:
        dimensions = ["platform_source"] if "platform_source" in columns else []

    select_dimensions = ", ".join(dimensions) + "," if dimensions else ""
    group_dimensions = ", ".join(str(index + 1) for index in range(len(dimensions)))
    group_clause = f"GROUP BY {group_dimensions}" if group_dimensions else ""

    spend_expr = numeric_expr(columns, "spend")
    impressions_expr = numeric_expr(columns, "impressions")
    clicks_expr = numeric_expr(columns, "clicks")
    gmv_expr = numeric_expr(columns, "gmv_optional")

    result = con.sql(
        f"""
        SELECT
          {select_dimensions}
          COUNT(DISTINCT CAST(date AS DATE)) AS paid_active_days,
          SUM({spend_expr}) AS spend,
          SUM({impressions_expr}) AS impressions,
          SUM({clicks_expr}) AS clicks,
          SUM({gmv_expr}) AS gmv_optional,
          CASE WHEN SUM({spend_expr}) > 0
            THEN SUM({gmv_expr}) * 1.0 / SUM({spend_expr})
          END AS roas_calc,
          CASE WHEN SUM({impressions_expr}) > 0
            THEN SUM({clicks_expr}) * 1.0 / SUM({impressions_expr})
          END AS ctr_calc,
          CASE WHEN SUM({clicks_expr}) > 0
            THEN SUM({spend_expr}) * 1.0 / SUM({clicks_expr})
          END AS cpc_calc
        FROM {source}
        {group_clause}
        ORDER BY roas_calc DESC NULLS LAST, spend DESC NULLS LAST
        LIMIT 20
        """
    )
    return [_clean_row(dict(zip(result.columns, row, strict=True))) for row in result.fetchall()]


def _clean_row(row: dict[str, object]) -> dict[str, object]:
    cleaned = dict(row)
    for key in ("spend", "impressions", "clicks", "gmv_optional", "roas_calc", "ctr_calc", "cpc_calc"):
        if cleaned.get(key) is not None:
            cleaned[key] = round(float(cleaned[key]), 4)
    if cleaned.get("paid_active_days") is not None:
        cleaned["paid_active_days"] = int(cleaned["paid_active_days"])
    return cleaned


def _recommended_action(rows: list[dict[str, object]], has_return: bool) -> str:
    if not rows:
        return "先导入包含消耗、曝光、点击的投放数据。"
    if not has_return:
        return "当前只能看点击效率；下一次导出请补充成交金额、成交订单数或 ROI 字段。"
    increase = [row for row in rows if row.get("budget_action") == "increase"]
    reduce = [row for row in rows if row.get("budget_action") == "reduce"]
    if increase:
        return "优先小幅增加高投产对象预算，同时保留日级观察，避免只凭单日波动放量。"
    if reduce:
        return "先压低高消耗低回报对象预算，把预算转给有点击和成交信号的对象。"
    return "保持当前预算，继续观察更多天数后再决定放量或缩量。"


def _caveats(rows: list[dict[str, object]], has_return: bool) -> list[str]:
    caveats = ["投放效率来自后台导出，不等同于内容或商品的因果影响。"]
    if not has_return:
        caveats.append("缺少成交金额或投产字段，不能判断 ROAS。")
    if any(int(row.get("paid_active_days") or 0) < 2 for row in rows):
        caveats.append("部分对象只有单日数据，预算动作需要保守执行。")
    return caveats


def _evidence_reason(has_return: bool) -> str:
    if has_return:
        return "投放消耗和成交金额可用，可用于预算效率判断；仍需注意平台归因口径。"
    return "只有投放消耗或点击数据，适合判断流量效率，不能判断投产。"


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=[
            Finding(
                title="投放效率不可判断",
                conclusion="当前没有可识别的投放效果导出表。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                evidence_reason="缺少投放事实表，不能计算消耗、点击或投产。",
                key_numbers={"rows": 0},
                caveats=[reason],
                recommended_action="先导入包含日期、消耗、曝光或点击字段的投放导出。",
            )
        ],
        tables={"paid_traffic_efficiency": []},
        limitations=[reason],
    )


def _float_or_none(value: object | None) -> float | None:
    return float(value) if value is not None else None


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
