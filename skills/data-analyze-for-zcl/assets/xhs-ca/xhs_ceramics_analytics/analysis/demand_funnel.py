"""需求漏斗与心愿单诊断 — demand_funnel_diagnosis.

Complements ``core_business_diagnosis``: that module reads the store-page
visit→click→pay funnel (shop_page_funnel) and GMV trend; this one reads the
*account-level demand accumulation* off business_overview_daily —— 加购→成交
的转化漏斗与其时间趋势，以及心愿单蓄水的规模与走向。两者口径不同、不重叠。

Same module contract: never-raise degradation, ``_table_exists`` /
``_table_columns`` / ``_fetch_all`` / ``_num`` helpers, per-Finding
confounders + observational caveats. Observational only — 报方向与规模，非因果。
"""
from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis.prose import cn_date, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analytics.confidence import min_n_guard, rate_band, wilson_interval
from xhs_ceramics_analytics.analytics.trends import trend_summary
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import (
    EvidenceStrength,
    score_evidence,
    score_reliability,
)

TASK_ID = "demand_funnel_diagnosis"
TITLE = "需求漏斗与心愿单诊断"

_WISHLIST_COL = "新增加入心愿单人数"

_CONFOUNDERS = ["流量质量", "促销与活动节奏", "客群构成", "季节性"]

_LEVER_FUNNEL = (
    "加购蓄水与成交转化分开看：加购在涨但转化走平/下降，说明承接（详情页/价格/信任状）"
    "跟不上蓄水，应优先补转化钩子；两者同向上行则以扩流量为主。"
)
_LEVER_WISHLIST = (
    "心愿单是延迟需求的蓄水池：规模走高时用上新预告/到货提醒/限时权益促其转化，"
    "避免蓄水沉淀不动。"
)


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "business_overview_daily"):
            return _missing_result("缺少 business_overview_daily 表。")

        cols = _table_columns(con, "business_overview_daily")
        rows = _fetch_all(con, "business_overview_daily")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        # Finding 1 is always emitted (documented not-judgable when cart cols absent).
        funnel_finding, funnel_rows = _funnel_finding(rows, cols, limitations)
        findings.append(funnel_finding)
        if funnel_rows:
            tables["demand_funnel_trend"] = funnel_rows

        wishlist_finding, wishlist_rows = _wishlist_finding(rows, cols, limitations)
        if wishlist_finding is not None:
            findings.append(wishlist_finding)
            tables["wishlist_demand_trend"] = wishlist_rows
    finally:
        con.close()
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


# --------------------------------------------------------------------------- #
# Finding 1 — 加购→成交需求漏斗（账号级） (always emitted)
# --------------------------------------------------------------------------- #
def _funnel_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding, list[dict]]:
    if not {"add_to_cart_users", "paid_buyers"} <= cols:
        limitations.append(
            "business_overview_daily 缺少 add_to_cart_users/paid_buyers 列，无法计算加购→成交漏斗。"
        )
        finding = Finding(
            title="加购→成交需求漏斗",
            conclusion=(
                "business_overview_daily 缺少 add_to_cart_users/paid_buyers 列，"
                "无法计算账号级加购→成交漏斗，需补充真实加购与支付买家列。"
            ),
            evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            key_numbers={"total_add_to_cart_users": None, "total_paid_buyers": None},
            caveats=["加购人数/支付买家列缺失应视为导入缺口。"],
            confounders=list(_CONFOUNDERS),
            evidence_reason="缺少 add_to_cart_users/paid_buyers 列，无法计算加购→成交转化。",
        )
        return finding, []

    total_cart = sum(_num(r.get("add_to_cart_users")) for r in rows)
    total_buyers = sum(_num(r.get("paid_buyers")) for r in rows)
    # Ratio caliber, not a strict funnel — some buyers never add to cart, so the
    # ratio can approach or exceed 1. Kept raw (never through bounded_rate, which
    # would misread a legit 1.2 as 1.2%).
    cart_to_pay = (total_buyers / total_cart) if total_cart else None

    # Per-day cart→pay series for the trend (only days with positive carts).
    has_date = "date" in cols
    series: list[tuple[str, float]] = []
    funnel_rows: list[dict] = []
    if has_date:
        dated = [r for r in rows if r.get("date") is not None]
        dated.sort(key=lambda r: str(r.get("date")))
        for r in dated:
            # Normalize raw table dates (int YYYYMMDD or ISO) to canonical ISO once,
            # so table rows and chart series share one date form (same source as
            # core_business._gmv_trend).
            iso_date = cn_date(r.get("date"))
            cart = _num(r.get("add_to_cart_users"))
            buyers = _num(r.get("paid_buyers"))
            rate = (buyers / cart) if cart else None
            funnel_rows.append(
                {
                    "date": iso_date,
                    "add_to_cart_users": cart,
                    "paid_buyers": buyers,
                    "cart_to_pay": rate,
                }
            )
            if rate is not None:
                series.append((iso_date, rate))

    trend_direction = None
    if len(series) >= 2:
        trend_direction = trend_summary(series)["direction"]
    elif has_date:
        limitations.append("business_overview_daily 有效日期不足两期，跳过加购→成交趋势。")
    else:
        limitations.append("business_overview_daily 缺少 date 列，跳过加购→成交趋势。")

    # Wilson band only when the ratio is a genuine sub-funnel (buyers ≤ carts).
    ci_low = ci_high = ci_band = None
    if total_cart and total_buyers <= total_cart and min_n_guard(int(total_cart)):
        ci_low, ci_high = wilson_interval(total_buyers, int(total_cart))
        ci_band = rate_band(ci_low, ci_high)

    conclusion = (
        f"累计加购 {qty(total_cart)} 人、支付买家 {qty(total_buyers)} 人，"
        f"加购→成交比约 {round((cart_to_pay or 0) * 100, 1)}%"
        + (f"，趋势{trend_direction}。" if trend_direction else "，趋势数据不足。")
    )

    caveats = [
        M.causal_disclaimer("流量质量、活动折扣和客群不同"),
        "比值口径而非严格漏斗：部分成交未先加购，比值可能接近或超过 100%，趋势比绝对值更可读。",
    ]

    key_numbers: dict[str, object] = {
        "total_add_to_cart_users": total_cart,
        "total_paid_buyers": total_buyers,
        "cart_to_pay": cart_to_pay,
        "cart_to_pay_trend": trend_direction,
    }
    if ci_band is not None:
        key_numbers["ci_low"] = ci_low
        key_numbers["ci_high"] = ci_high

    sample_size = int(total_cart) if total_cart else len(rows)
    finding = Finding(
        title="加购→成交需求漏斗",
        conclusion=conclusion,
        evidence_strength=score_evidence(sample_size, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sample_size, ci_low, ci_high),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=_LEVER_FUNNEL,
        evidence_reason=M.methodology_note(
            "加购与支付买家为 business_overview_daily 真实列聚合，"
            "趋势按逐日加购→成交比的最小二乘斜率判定；观察性描述，非因果。",
            "加购→成交比的 95% 置信区间见 ci_low/ci_high。" if ci_band is not None else None,
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, funnel_rows


# --------------------------------------------------------------------------- #
# Finding 2 — 心愿单需求蓄水 (degrade-gated)
# --------------------------------------------------------------------------- #
def _wishlist_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if _WISHLIST_COL not in cols:
        limitations.append(f"business_overview_daily 缺少「{_WISHLIST_COL}」列，跳过心愿单需求蓄水。")
        return None, []

    total_wishlist = sum(_num(r.get(_WISHLIST_COL)) for r in rows)

    has_date = "date" in cols
    series: list[tuple[str, float]] = []
    wishlist_rows: list[dict] = []
    if has_date:
        dated = [r for r in rows if r.get("date") is not None]
        dated.sort(key=lambda r: str(r.get("date")))
        for r in dated:
            iso_date = cn_date(r.get("date"))
            users = _num(r.get(_WISHLIST_COL))
            wishlist_rows.append(
                {"date": iso_date, "new_wishlist_users": users}
            )
            series.append((iso_date, users))

    trend_direction = None
    if len(series) >= 2:
        trend_direction = trend_summary(series)["direction"]
    else:
        limitations.append("business_overview_daily 心愿单序列不足两期，跳过心愿单趋势。")

    # Depth indicator: 心愿单 relative to 加购（both蓄水，但心愿单是更弱意向）。
    wishlist_to_cart = None
    if "add_to_cart_users" in cols:
        total_cart = sum(_num(r.get("add_to_cart_users")) for r in rows)
        wishlist_to_cart = (total_wishlist / total_cart) if total_cart else None

    conclusion = (
        f"心愿单累计新增 {qty(total_wishlist)} 人"
        + (f"，趋势{trend_direction}。" if trend_direction else "，趋势数据不足。")
    )
    if wishlist_to_cart is not None:
        conclusion += f" 心愿单/加购约 {round(wishlist_to_cart * 100)}%，反映延迟需求蓄水深度。"

    key_numbers: dict[str, object] = {
        "total_new_wishlist": total_wishlist,
        "wishlist_trend": trend_direction,
    }
    if wishlist_to_cart is not None:
        key_numbers["wishlist_to_cart_ratio"] = wishlist_to_cart

    finding = Finding(
        title="心愿单需求蓄水",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(series) or 1, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(series) or 1),
        key_numbers=key_numbers,
        caveats=[
            "心愿单是延迟需求信号。" + M.causal_disclaimer("上新、提醒和权益节奏不同"),
            "心愿单与加购为两种意向强度，不可相加；心愿单/加购仅作蓄水深度参考。",
        ],
        recommended_action=_LEVER_WISHLIST,
        evidence_reason="心愿单新增为真实列逐日聚合，趋势按最小二乘斜率判定；观察性描述，非因果。",
        confounders=list(_CONFOUNDERS),
    )
    return finding, wishlist_rows


# --------------------------------------------------------------------------- #
# Shared helpers (ported from core_business/sku_structure)
# --------------------------------------------------------------------------- #
def _num(value) -> float:
    return to_finite_float(value, 0.0)


def _fetch_all(con, table: str) -> list[dict]:
    rel = con.sql(f"SELECT * FROM {table}")
    columns = rel.columns
    return [dict(zip(columns, row)) for row in rel.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=[
            Finding(
                title="需求漏斗不可诊断",
                conclusion="需要导出 business_overview_daily（每日经营概览）数据后才能诊断需求漏斗与心愿单。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["每日经营概览缺失应视为导入缺口。"],
                recommended_action="导出每日经营概览（含加购人数、支付买家、心愿单新增）后重新构建。",
            )
        ],
        tables={"demand_funnel_trend": []},
        limitations=[reason],
    )
