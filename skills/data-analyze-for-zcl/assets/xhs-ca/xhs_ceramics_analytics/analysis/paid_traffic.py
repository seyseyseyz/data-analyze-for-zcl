from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.elasticity import saturation_point, spend_response_curve
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.db.sql_helpers import numeric_expr
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence
from xhs_ceramics_analytics.evidence import score_reliability

MIN_SPEND_FOR_ACTION = 100
# Hard ROAS cutoffs are a *fallback* per-object tag only; the primary放量/缩量 signal
# is the data-driven saturation point from the spend→GMV response curve (C6).
HIGH_ROAS_THRESHOLD = 3
LOW_ROAS_THRESHOLD = 1
LOW_CLICK_THRESHOLD = 20
MIN_ACTIVE_DAYS_FOR_ACTION = 2

# Spend→GMV response curve resolution and reader-facing band labels.
_RESPONSE_BINS = 4
_SPEND_BAND_LABELS = ["低投放", "中低投放", "中高投放", "高投放"]


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
    if active_days < MIN_ACTIVE_DAYS_FOR_ACTION and roas >= HIGH_ROAS_THRESHOLD:
        return "hold"
    if (
        spend >= MIN_SPEND_FOR_ACTION
        and roas >= HIGH_ROAS_THRESHOLD
        and gmv > 0
    ):
        return "increase"
    if spend >= MIN_SPEND_FOR_ACTION and (
        clicks < LOW_CLICK_THRESHOLD
        or gmv <= 0
        or roas < LOW_ROAS_THRESHOLD
    ):
        return "reduce"
    return "hold"


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "ad_performance_daily"):
            return _missing_result("缺少 ad_performance_daily 表。")
        source = "ad_metrics" if _table_exists(con, "ad_metrics") else "ad_performance_daily"
        rows = _efficiency_rows(con, source)
        response_observations = _spend_gmv_observations(con, source)
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
    descriptive_reliability = score_reliability(
        sum(int(row.get("paid_active_days") or 0) for row in rows)
    )

    findings = [
        Finding(
            title="投放消耗和投产效率已汇总",
            conclusion=(
                f"已汇总 {qty(len(rows))} 个投放对象，总消耗 {money(total_spend)}，"
                f"可见成交金额 {money(total_gmv)}。"
            ),
            evidence_strength=evidence_strength,
            descriptive_reliability=descriptive_reliability,
            evidence_reason=_evidence_reason(has_return),
            key_numbers={
                "rows": len(rows),
                "spend": round(total_spend, 2),
                "gmv_optional": round(total_gmv, 2) if has_return else None,
            },
            caveats=_caveats(rows, has_return),
            recommended_action=_recommended_action(rows, has_return),
        )
    ]
    tables = {"paid_traffic_efficiency": rows}
    limitations: list[str] = []

    elasticity_finding, response_rows = _elasticity_finding(
        response_observations if has_return else [], limitations
    )
    if elasticity_finding is not None:
        findings.append(elasticity_finding)
        tables["paid_spend_response"] = response_rows

    return AnalysisResult(
        task_id="paid_traffic_efficiency",
        title="投放效率分析",
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _elasticity_finding(
    observations: list[tuple[float, float]], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    """投放弹性与饱和点 — 花费→成交响应曲线的边际 ROAS 递减 + 饱和点.

    Replaces hand-set HIGH/LOW ROAS cutoffs with a data-driven turning point:
    quantile-bins objects by spend and reads where marginal ROAS crosses below
    break-even. Cross-sectional & observational, degrade-gated (需 ≥4 个有花费对象).
    """
    if not observations:
        return None, []
    curve = spend_response_curve(observations, bins=_RESPONSE_BINS)
    if len(curve) < 2:
        limitations.append("有花费的投放对象不足以切分弹性曲线，跳过投放弹性与饱和点。")
        return None, []

    sat = saturation_point(curve)
    sat_bin = sat["saturation_bin"]
    break_even_spend = sat["break_even_spend"]

    response_rows = [
        {
            "spend_band": _SPEND_BAND_LABELS[r["bin"]],
            "objects": r["n"],
            "avg_spend": round(r["avg_spend"], 2),
            "avg_roas": round(r["avg_roas"], 4) if r["avg_roas"] is not None else None,
            "marginal_roas": (
                round(r["marginal_roas"], 4) if r["marginal_roas"] is not None else None
            ),
            "is_saturation": r["bin"] == sat_bin,
        }
        for r in curve
    ]

    if sat_bin is not None:
        conclusion = (
            f"投放回报随消耗上升递减，边际 ROAS 在「{_SPEND_BAND_LABELS[sat_bin]}」档"
            f"跌破盈亏线（该档日均消耗约 {money(break_even_spend)}）——"
            "越过此档继续加投，每元消耗回报不足 1 元。"
        )
        action = (
            "把预算上限压在饱和点档位附近，超出部分的消耗转投到饱和点以下、"
            "边际回报仍高的对象；放量前先按对象小步测试。"
        )
    elif sat["diminishing"]:
        conclusion = (
            "投放回报随消耗上升递减，但边际 ROAS 仍在盈亏线以上，"
            "规模区间内尚有加投空间，需监控是否临近饱和。"
        )
        action = "可小幅放量高消耗对象，同时监控边际 ROAS 是否继续下滑至盈亏线。"
    else:
        conclusion = (
            "未见明显的边际回报递减，规模区间内投产相对稳定，"
            "可按对象 ROAS 结构而非统一阈值调整预算。"
        )
        action = "按对象边际回报结构分配预算，暂无统一放量/缩量的规模拐点。"

    n_objects = sum(r["n"] for r in curve)
    return (
        Finding(
            title="投放弹性与饱和点",
            conclusion=conclusion,
            evidence_strength=score_evidence(n_objects, has_controls=False, confounder_count=2),
            descriptive_reliability=score_reliability(n_objects),
            key_numbers={
                "band_count": len(response_rows),
                "saturation_band": _SPEND_BAND_LABELS[sat_bin] if sat_bin is not None else None,
                "break_even_spend": round(break_even_spend, 2) if break_even_spend else None,
                "diminishing": sat["diminishing"],
            },
            caveats=[
                "横截面观察，非因果——对象本身质量不同，边际 ROAS 递减是关联而非同一对象的加投响应。",
                "花费按四分位分档，饱和点为描述性拐点；平台归因口径与延迟成交会影响 ROAS。",
            ],
            recommended_action=action,
            evidence_reason=(
                "按对象花费四分位分档，边际 ROAS=Δ人均成交/Δ人均花费；"
                "饱和点取边际 ROAS 首次跌破盈亏线的档位，替代硬编码 ROAS 阈值。"
            ),
            confounders=["对象质量差异", "平台归因口径", "活动与季节节奏"],
        ),
        response_rows,
    )


def _spend_gmv_observations(con, source: str) -> list[tuple[float, float]]:
    """Per-object ``(spend, gmv)`` for the spend→GMV response curve.

    Aggregates over the same object dimensions as :func:`_efficiency_rows` but with
    no ROAS ordering or ``LIMIT`` — the saturation curve needs the full spend
    cross-section, not just the top-20 by ROAS. Returns ``[]`` on any error or when
    GMV is absent (curve is only meaningful with return data)."""
    columns = _table_columns(con, source)
    if numeric_expr(columns, "gmv_optional") == "NULL":
        return []
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
    if not dimensions and "platform_source" in columns:
        dimensions = ["platform_source"]

    # Group by the dimension column names directly — the SELECT only projects the
    # aggregates, so positional GROUP BY would (wrongly) reference an aggregate.
    group_clause = "GROUP BY " + ", ".join(dimensions) if dimensions else ""
    spend_expr = numeric_expr(columns, "spend")
    gmv_expr = numeric_expr(columns, "gmv_optional")
    try:
        result = con.sql(
            f"""
            SELECT SUM({spend_expr}) AS spend, SUM({gmv_expr}) AS gmv
            FROM {source}
            {group_clause}
            """
        )
    except Exception:
        return []
    observations: list[tuple[float, float]] = []
    for spend, gmv in result.fetchall():
        if spend is None or gmv is None:
            continue
        observations.append((float(spend), float(gmv)))
    return observations


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

    # The numeric_expr CASTs raise a DuckDB Conversion Error on a dirty VARCHAR
    # cell ("1,234", "—"); guard exactly like the sibling _spend_gmv_observations
    # so a messy export degrades to an empty efficiency table, never a raise.
    try:
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
        rows = result.fetchall()
        columns = result.columns
    except Exception:
        return []
    return [_clean_row(dict(zip(columns, row, strict=True))) for row in rows]


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
