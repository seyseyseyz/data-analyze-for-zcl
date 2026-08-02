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
from xhs_ceramics_analytics.analytics.trends import trend_summary
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import (
    EvidenceStrength,
    score_evidence,
    score_reliability,
)

TASK_ID = "demand_funnel_diagnosis"
TITLE = "需求漏斗与心愿单诊断"

_WISHLIST_COL = "new_wishlist_users"

_CONFOUNDERS = ["流量质量", "促销与活动节奏", "客群构成", "季节性"]

_LEVER_FUNNEL = (
    "加购蓄水和成交转化分开看：加购人数在涨、但真正下单的没跟上（走平或掉了），说明详情页/价格/信任这些接住客人的环节"
    "跟不上蓄水，就先把这些环节补好、让客人更愿意下单；两者一起往上走时，就主要去多拉流量。"
)
_LEVER_WISHLIST = (
    "心愿单是延迟需求的蓄水池：规模走高时用上新预告/到货提醒/限时权益促其转化，"
    "别让这池需求沉着不动，趁热推一把。"
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
            key_numbers={
                "avg_daily_add_to_cart_users": None,
                "avg_daily_paid_buyers": None,
            },
            caveats=["加购人数/支付买家列缺失应视为导入缺口。"],
            confounders=list(_CONFOUNDERS),
            evidence_reason="缺少 add_to_cart_users/paid_buyers 列，无法计算加购→成交转化。",
        )
        return finding, []

    cart_values = [
        _num(r.get("add_to_cart_users")) for r in rows if r.get("add_to_cart_users") is not None
    ]
    buyer_values = [_num(r.get("paid_buyers")) for r in rows if r.get("paid_buyers") is not None]
    has_product_visitors = "product_visitors" in cols
    product_visitor_values = (
        [_num(r.get("product_visitors")) for r in rows if r.get("product_visitors") is not None]
        if has_product_visitors
        else []
    )
    add_to_cart_user_days = sum(cart_values) if cart_values else None
    paid_buyer_days = sum(buyer_values) if buyer_values else None
    avg_daily_cart = _mean(cart_values)
    avg_daily_buyers = _mean(buyer_values)
    avg_daily_product_visitors = _mean(product_visitor_values)
    daily_ratios: list[float] = []
    product_to_cart_ratios: list[float] = []
    for row in rows:
        raw_cart = row.get("add_to_cart_users")
        raw_buyers = row.get("paid_buyers")
        if raw_cart is not None and raw_buyers is not None:
            cart = _num(raw_cart)
            if cart > 0:
                daily_ratios.append(_num(raw_buyers) / cart)
        if (
            has_product_visitors
            and raw_cart is not None
            and row.get("product_visitors") is not None
        ):
            cart = _num(raw_cart)
            visitors = _num(row.get("product_visitors"))
            if visitors > 0:
                product_to_cart_ratios.append(cart / visitors)

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
            raw_cart = r.get("add_to_cart_users")
            raw_buyers = r.get("paid_buyers")
            cart = _num(raw_cart) if raw_cart is not None else None
            buyers = _num(raw_buyers) if raw_buyers is not None else None
            rate = (buyers / cart) if cart and buyers is not None else None
            row = {
                "date": iso_date,
                "add_to_cart_users": cart,
                "paid_buyers": buyers,
                "cart_to_pay": rate,
            }
            if has_product_visitors:
                raw_visitors = r.get("product_visitors")
                visitors = _num(raw_visitors) if raw_visitors is not None else None
                row = {
                    "date": iso_date,
                    "product_visitors": visitors,
                    "add_to_cart_users": cart,
                    "paid_buyers": buyers,
                    "product_to_cart": (cart / visitors) if visitors and cart is not None else None,
                    "cart_to_pay": rate,
                }
            funnel_rows.append(row)
            if rate is not None:
                series.append((iso_date, rate))

    avg_daily_cart_to_pay = _mean(daily_ratios)
    avg_daily_product_to_cart = _mean(product_to_cart_ratios)

    trend_direction = None
    if len(series) >= 2:
        trend_direction = trend_summary(series)["direction"]
    elif has_date:
        limitations.append("business_overview_daily 有效日期不足两期，跳过加购→成交趋势。")
    else:
        limitations.append("business_overview_daily 缺少 date 列，跳过加购→成交趋势。")

    ratio_summary = (
        f"日均加购→支付比约 {round(avg_daily_cart_to_pay * 100, 1)}%"
        if avg_daily_cart_to_pay is not None
        else "日均加购→支付比数据不足"
    )
    cart_summary = (
        f"日均加购 {qty(avg_daily_cart)} 人" if avg_daily_cart is not None else "日均加购数据不足"
    )
    buyer_summary = (
        f"日均支付买家 {qty(avg_daily_buyers)} 人"
        if avg_daily_buyers is not None
        else "日均支付买家数据不足"
    )
    conclusion = f"{cart_summary}、{buyer_summary}，{ratio_summary}" + (
        f"，趋势{trend_direction}。" if trend_direction else "，趋势数据不足。"
    )

    caveats = [
        M.causal_disclaimer("流量质量、活动折扣和客群不同"),
        "不是严格的漏斗、只是个比值：有些人没先加购就直接下单了，所以这个比值可能接近甚至超过 100%，看走势比看具体数字更靠谱。",
        "加购人数和支付买家数均为逐日去重；跨日可能重复计入，因此只报告日均值和逐日比率，不解释为观察期唯一人数。",
        "商品访客→加购→支付是逐日阶段事实，不是严格的用户漏斗：同一用户跨日可能重复，且支付未必先加购。",
    ]

    key_numbers: dict[str, object] = {
        "add_to_cart_user_days": add_to_cart_user_days,
        "paid_buyer_days": paid_buyer_days,
        "avg_daily_add_to_cart_users": avg_daily_cart,
        "avg_daily_paid_buyers": avg_daily_buyers,
        "avg_daily_cart_to_pay": avg_daily_cart_to_pay,
        "add_to_cart_observed_days": len(cart_values),
        "paid_buyer_observed_days": len(buyer_values),
        "paired_ratio_observed_days": len(daily_ratios),
        "cart_to_pay_trend": trend_direction,
    }
    if has_product_visitors:
        key_numbers.update(
            {
                "product_visitor_days": sum(product_visitor_values)
                if product_visitor_values
                else None,
                "avg_daily_product_visitors": avg_daily_product_visitors,
                "avg_daily_product_to_cart": avg_daily_product_to_cart,
                "product_visitor_observed_days": len(product_visitor_values),
                "product_to_cart_paired_observed_days": len(product_to_cart_ratios),
            }
        )

    sample_size = len(daily_ratios)
    if sample_size == 0:
        limitations.append(
            "加购人数与支付买家数的有效配对日为 0，无法判断加购→支付比或给出经营动作；"
            "需补齐同日有效的加购与支付买家数据。"
        )
    finding = Finding(
        title="加购→成交需求漏斗",
        conclusion=conclusion,
        evidence_strength=score_evidence(sample_size, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sample_size),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=_LEVER_FUNNEL if sample_size > 0 else None,
        evidence_reason=M.methodology_note(
            "商品访客（如已导出）、加购与支付买家为 business_overview_daily 逐日去重真实列，跨日不求唯一人数；"
            "趋势按逐日加购→成交比的最小二乘斜率判定；观察性描述，非因果。",
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
        limitations.append(
            f"business_overview_daily 缺少「{_WISHLIST_COL}」列，跳过心愿单需求蓄水。"
        )
        return None, []

    wishlist_values = [_num(r.get(_WISHLIST_COL)) for r in rows if r.get(_WISHLIST_COL) is not None]
    new_wishlist_user_days = sum(wishlist_values) if wishlist_values else None
    avg_daily_wishlist = _mean(wishlist_values)

    has_date = "date" in cols
    series: list[tuple[str, float]] = []
    wishlist_rows: list[dict] = []
    if has_date:
        dated = [r for r in rows if r.get("date") is not None]
        dated.sort(key=lambda r: str(r.get("date")))
        for r in dated:
            iso_date = cn_date(r.get("date"))
            raw_users = r.get(_WISHLIST_COL)
            users = _num(raw_users) if raw_users is not None else None
            wishlist_rows.append({"date": iso_date, "new_wishlist_users": users})
            if users is not None:
                series.append((iso_date, users))

    trend_direction = None
    if len(series) >= 2:
        trend_direction = trend_summary(series)["direction"]
    else:
        limitations.append("business_overview_daily 心愿单序列不足两期，跳过心愿单趋势。")

    # Depth indicator: 心愿单 relative to 加购（both蓄水，但心愿单是更弱意向）。
    daily_wishlist_to_cart: list[float] = []
    if "add_to_cart_users" in cols:
        for row in rows:
            cart = _num(row.get("add_to_cart_users"))
            if cart > 0 and row.get(_WISHLIST_COL) is not None:
                daily_wishlist_to_cart.append(_num(row.get(_WISHLIST_COL)) / cart)
    avg_daily_wishlist_to_cart = _mean(daily_wishlist_to_cart)

    wishlist_summary = (
        f"心愿单日均新增 {qty(avg_daily_wishlist)} 人"
        if avg_daily_wishlist is not None
        else "心愿单日均新增数据不足"
    )
    conclusion = wishlist_summary + (
        f"，趋势{trend_direction}。" if trend_direction else "，趋势数据不足。"
    )
    if avg_daily_wishlist_to_cart is not None:
        conclusion += (
            f" 日均心愿单/加购比约 {round(avg_daily_wishlist_to_cart * 100)}%，"
            "反映延迟需求蓄水深度。"
        )

    key_numbers: dict[str, object] = {
        "new_wishlist_user_days": new_wishlist_user_days,
        "avg_daily_new_wishlist_users": avg_daily_wishlist,
        "wishlist_trend": trend_direction,
    }
    if avg_daily_wishlist_to_cart is not None:
        key_numbers["avg_daily_wishlist_to_cart"] = avg_daily_wishlist_to_cart

    sample_size = len(wishlist_values)
    if sample_size == 0:
        limitations.append(
            "心愿单有效观察日为 0，无法判断需求蓄水或给出经营动作；需补齐有效的心愿单新增数据。"
        )
    finding = Finding(
        title="心愿单需求蓄水",
        conclusion=conclusion,
        evidence_strength=score_evidence(sample_size, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sample_size),
        key_numbers=key_numbers,
        caveats=[
            "心愿单是延迟需求信号。" + M.causal_disclaimer("上新、提醒和权益节奏不同"),
            "心愿单和加购是两种不同热度的想买信号，不能加在一起算；心愿单/加购只当作蓄水深浅的参考。",
            "心愿单新增和加购人数均为逐日去重；跨日可能重复计入，因此不解释为观察期唯一人数。",
        ],
        recommended_action=_LEVER_WISHLIST if sample_size > 0 else None,
        evidence_reason="心愿单新增为逐日去重真实列，报告日均值并按逐日序列判趋势；观察性描述，非因果。",
        confounders=list(_CONFOUNDERS),
    )
    return finding, wishlist_rows


# --------------------------------------------------------------------------- #
# Shared helpers (ported from core_business/sku_structure)
# --------------------------------------------------------------------------- #
def _num(value) -> float:
    return to_finite_float(value, 0.0)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


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
                conclusion="暂时无法诊断需求漏斗与心愿单，需要导出 business_overview_daily（每日经营概览）数据。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["每日经营概览缺失应视为导入缺口。"],
                recommended_action="导出每日经营概览（含加购人数、支付买家、心愿单新增）后重新构建。",
            )
        ],
        tables={"demand_funnel_trend": []},
        limitations=[reason],
    )
