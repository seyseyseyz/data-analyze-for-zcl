"""搜索效率诊断 (§5) — carrier search efficiency, conversion trend, term opps.

Sibling of ``refund_diagnosis``: same module contract, shared stat helpers, and
never-raise degradation discipline. Search derives the payer numerator *forward*
(impressions × click_rate × pay_conversion) and never reverse-derives
``n = k / rate``. Prefers real ``paid_buyers`` when the column is present.
Observational only — every finding carries confounders and an observational
caveat, and every denominator is guarded.
"""

from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analytics.confidence import (
    MIN_ORDERS_FOR_RATE,
    bounded_rate,
    min_n_guard,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.analytics.trends import mom_change, trend_summary
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import (
    EvidenceStrength,
    score_evidence,
    score_reliability,
)

TASK_ID = "search_efficiency_diagnosis"
TITLE = "搜索效率诊断"

# effectiveness = click_rate × pay_conversion → small fractions; require a
# non-trivial absolute gap before calling a significant z-test "显著".
_MIN_EFFECT_DIFF = 0.005

_CARRIER_CONFOUNDERS = ["载体流量结构", "搜索意图差异", "品类混合"]
_TREND_CONFOUNDERS = ["搜索大盘季节性", "活动节奏"]
_TERM_CONFOUNDERS = ["词意图混合", "季节性", "竞争度"]

_LEVER_CARRIER_GAP = "这周先把搜索承接内容和预算向转化更高的那个载体倾斜，别再平摊给低效载体。"
_LEVER_TREND_DECLINE = (
    "先止跌：这周逐个排查搜索承接页和词-货匹配，看问题是出在承接页还是词没对上货。"
)
_LEVER_OPPORTUNITY = "这周先给高机会词加投，并为它们补上定向笔记和商详承接。"
_LEVER_LEAK = "这周先给高流失词降权减投，再逐一修词-货匹配和承接页相关性。"
_LEVER_CLICK_LEAK = (
    "这些词高曝光却少人点（卡在点击漏损）：这周先换封面/标题、对齐词-货匹配，把点击拉起来。"
)
_LEVER_CONV_LEAK = (
    "这些词有人点却少下单（卡在转化漏损）：这周先优化商详、价格和信任状承接，把转化补上。"
)

_OBS_CAVEAT = M.causal_disclaimer("不同载体/搜索词的流量结构和承接页不同")


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "search_overview"):
            return _missing_result("缺少 search_overview 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        carrier_finding, carrier_rows = _carrier_finding(con, limitations)
        findings.append(carrier_finding)
        tables["carrier_search_efficiency"] = carrier_rows

        trend_finding, trend_rows = _trend_finding(con, limitations)
        if trend_finding is not None:
            findings.append(trend_finding)
            tables["search_conversion_trend"] = trend_rows

        term_finding, term_rows = _term_finding(con, limitations)
        if term_finding is not None:
            findings.append(term_finding)
            tables["search_term_opportunities"] = term_rows
    finally:
        con.close()
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _observed_count(value) -> float | None:
    """Return a usable observed count without turning NULL into zero."""
    number = to_finite_float(value)
    return number if number is not None and number >= 0 else None


def _derive_click_users(impressions, click_rate) -> float | None:
    impressions = _observed_count(impressions)
    rate = bounded_rate(click_rate)
    return impressions * rate if impressions is not None and rate is not None else None


def _derive_payers(click_users, pay_conv) -> float | None:
    """Forward-derive payers from an available click count and conversion rate."""
    rate = bounded_rate(pay_conv)
    return click_users * rate if click_users is not None and rate is not None else None


def _search_funnel_record(row: dict, cols: set[str]) -> dict:
    """Build one explicit exposure→click→pay→GMV fact row.

    A canonical count is used only when that *row* has a value.  A NULL count
    may fall back to the rate-derived value for that row, but missing rates stay
    missing rather than becoming zero.
    """
    impressions = _observed_count(row.get("card_impression_users"))
    raw_clicks = _observed_count(row.get("product_click_users"))
    if raw_clicks is not None:
        clicks, click_source = raw_clicks, "real"
    else:
        clicks = _derive_click_users(
            row.get("card_impression_users"), row.get("product_click_rate")
        )
        click_source = "forward_derived" if clicks is not None else "missing"

    raw_buyers = _observed_count(row.get("paid_buyers"))
    if raw_buyers is not None:
        buyers, buyer_source = raw_buyers, "real"
    else:
        buyers = _derive_payers(clicks, row.get("pay_conversion"))
        buyer_source = "forward_derived" if buyers is not None else "missing"

    paid_orders = _observed_count(row.get("paid_orders"))
    gmv = _observed_count(row.get("gmv"))
    return {
        "impressions": impressions,
        "product_click_users": clicks,
        "paid_buyers": buyers,
        "paid_orders": paid_orders,
        "gmv": gmv,
        "click_users_source": click_source,
        "paid_buyers_source": buyer_source,
        "paid_orders_source": "real" if paid_orders is not None else "missing",
        "gmv_source": "real" if gmv is not None else "missing",
        "click_rate": (clicks / impressions) if impressions and clicks is not None else None,
        "click_to_pay_rate": (buyers / clicks) if clicks and buyers is not None else None,
        "pay_rate": (buyers / impressions) if impressions and buyers is not None else None,
        "gmv_per_thousand_impressions": (
            gmv / impressions * 1000 if impressions and gmv is not None else None
        ),
        "has_real_click_and_buyer": raw_clicks is not None and raw_buyers is not None,
        "rate_fallback": bounded_rate(row.get("pay_conversion")),
    }


def _source_summary(sources: list[str]) -> str:
    unique = set(sources)
    if not unique or unique == {"missing"}:
        return "missing"
    if unique == {"real"}:
        return "real"
    if unique == {"forward_derived"}:
        return "forward_derived"
    return "mixed"


def _source_coverage(records: list[dict], source_key: str) -> dict[str, int]:
    sources = [record[source_key] for record in records]
    return {
        "real_rows": sources.count("real"),
        "forward_derived_rows": sources.count("forward_derived"),
        "missing_rows": sources.count("missing"),
    }


def _sum_complete(values: list[float | None]) -> float | None:
    """Sum only a complete set so NULL never silently becomes a zero."""
    return sum(values) if values and all(value is not None for value in values) else None


def _carrier_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "search_overview")
    rows = _fetch_all(con, "search_overview")
    has_carrier = "carrier" in cols
    has_impr = "card_impression_users" in cols
    if not has_carrier:
        limitations.append("search_overview 缺少 carrier 列，按单一载体聚合。")
    if not has_impr:
        limitations.append("search_overview 缺少 card_impression_users 列，效率无法计算。")

    agg: dict[str, dict] = {}
    for r in rows:
        key = r.get("carrier") if has_carrier else "全部"
        record = _search_funnel_record(r, cols)
        agg.setdefault(key, {"records": []})["records"].append(record)

    carrier_rows = []
    all_records: list[dict] = []
    for key, bucket in agg.items():
        records = bucket["records"]
        all_records.extend(records)
        impressions = _sum_complete([record["impressions"] for record in records])
        clicks = _sum_complete([record["product_click_users"] for record in records])
        buyers = _sum_complete([record["paid_buyers"] for record in records])
        paid_orders = _sum_complete([record["paid_orders"] for record in records])
        gmv = _sum_complete([record["gmv"] for record in records])
        carrier_rows.append(
            {
                "carrier": key,
                "impressions": round(impressions) if impressions is not None else None,
                "product_click_users": round(clicks) if clicks is not None else None,
                "paid_buyers": round(buyers) if buyers is not None else None,
                "payers": round(buyers) if buyers is not None else None,
                "paid_orders": round(paid_orders) if paid_orders is not None else None,
                "gmv": gmv,
                "click_rate": (clicks / impressions)
                if impressions and clicks is not None
                else None,
                "click_to_pay_rate": (buyers / clicks) if clicks and buyers is not None else None,
                "pay_rate": (buyers / impressions) if impressions and buyers is not None else None,
                "effectiveness": (buyers / impressions)
                if impressions and buyers is not None
                else None,
                "gmv_per_thousand_impressions": (
                    gmv / impressions * 1000 if impressions and gmv is not None else None
                ),
                "click_users_source": _source_summary(
                    [record["click_users_source"] for record in records]
                ),
                "paid_buyers_source": _source_summary(
                    [record["paid_buyers_source"] for record in records]
                ),
                "paid_orders_source": _source_summary(
                    [record["paid_orders_source"] for record in records]
                ),
                "gmv_source": _source_summary([record["gmv_source"] for record in records]),
            }
        )
    carrier_rows.sort(
        key=lambda c: c["impressions"] if c["impressions"] is not None else -1, reverse=True
    )

    eligible = [
        c
        for c in carrier_rows
        if c["impressions"] is not None and c["impressions"] > 0 and c["payers"] is not None
    ]
    total_impr = _sum_complete([record["impressions"] for record in all_records])
    payers_source = _source_summary([record["paid_buyers_source"] for record in all_records])
    caveats = [_OBS_CAVEAT]
    buyer_coverage = _source_coverage(all_records, "paid_buyers_source")
    click_coverage = _source_coverage(all_records, "click_users_source")
    if buyer_coverage["forward_derived_rows"]:
        caveats.append("部分成交人数缺少真实值，逐行由点击人数×成交转化率正推；来源覆盖见关键数。")

    key_numbers: dict[str, object] = {
        "payers_source": payers_source,
        "carrier_count": len(eligible),
        "carrier_high": None,
        "effectiveness_high": None,
        "effectiveness_low": None,
        "diff": None,
        "significant": None,
        "ci_overlap": None,
        "total_impressions": total_impr,
        "click_users_source": _source_summary(
            [record["click_users_source"] for record in all_records]
        ),
        "click_users_coverage": click_coverage,
        "paid_buyers_coverage": buyer_coverage,
        "paid_orders_coverage": _source_coverage(all_records, "paid_orders_source"),
        "gmv_coverage": _source_coverage(all_records, "gmv_source"),
    }
    recommended_action = None
    method_note = None

    if len(eligible) >= 2:
        top2 = eligible[:2]
        a, b = top2[0], top2[1]
        hi, lo = (a, b) if a["effectiveness"] >= b["effectiveness"] else (b, a)
        test = two_proportion(a["payers"], a["impressions"], b["payers"], b["impressions"])
        # Report the gap in hi/lo order so its sign matches effectiveness_high/low
        # (two_proportion's diff is ordered by impression rank, which can differ).
        diff = hi["effectiveness"] - lo["effectiveness"]
        significant = bool(test["significant"] and diff >= _MIN_EFFECT_DIFF)
        key_numbers.update(
            {
                "carrier_high": hi["carrier"],
                "effectiveness_high": hi["effectiveness"],
                "effectiveness_low": lo["effectiveness"],
                "diff": diff,
                "significant": significant,
                "ci_overlap": test["ci_overlap"],
            }
        )
        sig_zh = "显著" if significant else "不显著"
        conclusion = (
            f"{hi['carrier']} 搜索成交效率（{_pct(hi['effectiveness'])}）高于 "
            f"{lo['carrier']}（{_pct(lo['effectiveness'])}），差异{sig_zh}。"
        )
        if significant:
            recommended_action = _LEVER_CARRIER_GAP
        method_note = M.METHOD_PROPORTION_TEST
    elif len(eligible) == 1:
        only = eligible[0]
        limitations.append("search_overview 只有单一载体，跳过载体对比。")
        key_numbers.update(
            {
                "carrier_high": only["carrier"],
                "effectiveness_high": only["effectiveness"],
            }
        )
        conclusion = (
            f"仅有载体 {only['carrier']}，搜索成交效率 {_pct(only['effectiveness'])}，"
            "没有其他载体可以对比。"
        )
    else:
        limitations.append("search_overview 无有效曝光的载体行，无法比较载体效率。")
        conclusion = "搜索概览里没有有效数据，没法比较各载体的搜索效率。"

    finding = Finding(
        title="载体搜索效率对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_impr or 0), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(int(total_impr or 0)),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=recommended_action,
        evidence_reason=M.methodology_note(
            "载体表按曝光→点击→支付→GMV逐行聚合；点击/成交人数优先取真实值，行值缺失才由率正推，NULL 不当作零。",
            method_note,
        ),
        confounders=_CARRIER_CONFOUNDERS,
    )
    return finding, carrier_rows


def _trend_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "search_overview")
    if "date" not in cols:
        limitations.append("search_overview 缺少 date，跳过搜索转化趋势。")
        return None, []
    rows = _fetch_all(con, "search_overview")
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("date") is None:
            continue
        by_date.setdefault(str(r.get("date")), []).append(_search_funnel_record(r, cols))
    period_rows: list[dict] = []
    for date, records in sorted(by_date.items()):
        usable_records = [
            record
            for record in records
            if record["product_click_users"] is not None and record["paid_buyers"] is not None
        ]
        clicks = sum(record["product_click_users"] for record in usable_records)
        buyers = sum(record["paid_buyers"] for record in usable_records)
        if usable_records and clicks > 0:
            value = buyers / clicks
            source_pairs = {
                (record["click_users_source"], record["paid_buyers_source"])
                for record in usable_records
            }
            if source_pairs == {("real", "real")}:
                source = "real_weighted"
            elif source_pairs == {("forward_derived", "forward_derived")}:
                source = "forward_derived"
            else:
                source = "mixed"
        else:
            rates = [
                record["rate_fallback"] for record in records if record["rate_fallback"] is not None
            ]
            if not rates:
                continue
            value, source = sum(rates) / len(rates), "rate_average"
        period_rows.append(
            {
                "period": date,
                "value": value,
                "conversion_source": source,
                "real_count_rows": sum(record["has_real_click_and_buyer"] for record in records),
                "usable_rows": len(usable_records),
                "excluded_rows": len(records) - len(usable_records),
                "rate_rows": sum(record["rate_fallback"] is not None for record in records),
            }
        )
    period_avgs = [(row["period"], row["value"]) for row in period_rows]
    if len(period_avgs) < 2:
        limitations.append("搜索转化序列不足两期，跳过趋势。")
        return None, []

    series = period_avgs
    # Per-period deltas belong in the table columns, not a stringified appendix.
    steps = mom_change(series)
    trend_rows = [
        {
            "period": step["period"],
            "avg_pay_conversion": step["value"],
            "avg_pay_conversion_delta": step["delta"],
            "pct": step["pct"],
            "direction": step["direction"],
            "conversion_source": next(
                row["conversion_source"] for row in period_rows if row["period"] == step["period"]
            ),
            "real_count_rows": next(
                row["real_count_rows"] for row in period_rows if row["period"] == step["period"]
            ),
            "usable_rows": next(
                row["usable_rows"] for row in period_rows if row["period"] == step["period"]
            ),
            "excluded_rows": next(
                row["excluded_rows"] for row in period_rows if row["period"] == step["period"]
            ),
            "rate_rows": next(
                row["rate_rows"] for row in period_rows if row["period"] == step["period"]
            ),
        }
        for step in steps
    ]
    # Direction from OLS slope over all periods — a noisy endpoint can't flip it.
    summary = trend_summary(series)
    direction = summary["direction"]
    recommended_action = _LEVER_TREND_DECLINE if direction == "下降" else None
    finding = Finding(
        title="搜索转化时间趋势",
        conclusion=(
            f"搜索成交转化率整体呈{direction}趋势（{qty(len(series))} 期，"
            f"从 {_pct(series[0][1])} 到 {_pct(series[-1][1])}）。"
        ),
        evidence_strength=score_evidence(len(series), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(series)),
        key_numbers={
            "trend_direction": direction,
            "first_rate": series[0][1],
            "last_rate": series[-1][1],
            "periods": len(series),
            "conversion_source": _source_summary(
                [
                    "real" if row["conversion_source"] == "real_weighted" else "forward_derived"
                    for row in period_rows
                ]
            ),
            "real_weighted_periods": sum(
                row["conversion_source"] == "real_weighted" for row in period_rows
            ),
            "rate_fallback_periods": sum(
                row["conversion_source"] == "rate_average" for row in period_rows
            ),
        },
        caveats=[
            _OBS_CAVEAT,
            "每天的成交转化本来就上下波动大，逐期对比可以看搜索转化趋势表。",
        ],
        recommended_action=recommended_action,
        evidence_reason=M.methodology_note(
            "逐日优先按 Σ真实支付买家/Σ真实点击人数加权；没有成对真实计数时才降级为率列平均。",
            M.METHOD_TREND_SLOPE,
        ),
        confounders=_TREND_CONFOUNDERS,
        appendix="逐期环比（delta/pct）见搜索转化趋势表。",
    )
    return finding, trend_rows


def _term_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "search_terms"):
        limitations.append("缺少 search_terms 表，跳过高机会/高流失搜索词。")
        return None, []
    cols = _table_columns(con, "search_terms")
    if "search_term" not in cols or "card_impression_users" not in cols:
        limitations.append("search_terms 缺少 search_term/card_impression_users，跳过。")
        return None, []
    rows = _fetch_all(con, "search_terms")

    records: list[dict] = []
    for r in rows:
        funnel = _search_funnel_record(r, cols)
        records.append({"search_term": r.get("search_term"), **funnel})

    complete_records = [
        record
        for record in records
        if record["impressions"] is not None and record["paid_buyers"] is not None
    ]
    total_k = sum(record["paid_buyers"] for record in complete_records)
    total_n = sum(record["impressions"] for record in complete_records)
    baseline = total_k / total_n if total_n else 0.0

    # Traffic-weighted click + conversion baselines let us split a "leak" into a
    # click-side loss (low click-through) vs a conversion-side loss (clicks that
    # don't convert). Only computable when the click-rate column is present.
    click_den = sum(
        record["impressions"]
        for record in records
        if record["impressions"] is not None and record["click_rate"] is not None
    )
    click_base = (
        sum(
            record["impressions"] * record["click_rate"]
            for record in records
            if record["impressions"] is not None and record["click_rate"] is not None
        )
        / click_den
        if click_den
        else None
    )
    conv_den = sum(
        record["product_click_users"]
        for record in records
        if record["product_click_users"] is not None and record["paid_buyers"] is not None
    )
    conv_base = (
        sum(
            record["paid_buyers"]
            for record in records
            if record["product_click_users"] is not None and record["paid_buyers"] is not None
        )
        / conv_den
        if conv_den
        else None
    )

    term_rows: list[dict] = []
    opportunities: list[dict] = []
    leaks: list[dict] = []
    click_leaks: list[dict] = []
    conversion_leaks: list[dict] = []
    for r in records:
        n = r["impressions"]
        k = r["paid_buyers"]
        lo, hi = wilson_interval(k, n) if n is not None and k is not None else (None, None)
        if n is None or k is None:
            term_class = "not_judgable"
        elif not min_n_guard(n):
            term_class = "small_sample"
        elif lo > baseline:
            term_class = "opportunity"
        elif hi < baseline:
            term_class = "leak"
        else:
            term_class = "average"
        leak_type = (
            _leak_type(r["click_rate"], r["click_to_pay_rate"], click_base, conv_base)
            if term_class == "leak"
            else None
        )
        row = {
            "search_term": r["search_term"],
            "n": round(n) if n is not None else None,
            "k": round(k) if k is not None else None,
            "rate": r["pay_rate"],
            "wilson_low": lo,
            "wilson_high": hi,
            "gmv": r["gmv"],
            "impressions": round(n) if n is not None else None,
            "product_click_users": (
                round(r["product_click_users"]) if r["product_click_users"] is not None else None
            ),
            "paid_buyers": round(k) if k is not None else None,
            "paid_orders": round(r["paid_orders"]) if r["paid_orders"] is not None else None,
            "click_rate": r["click_rate"],
            "click_to_pay_rate": r["click_to_pay_rate"],
            "pay_rate": r["pay_rate"],
            "gmv_per_thousand_impressions": r["gmv_per_thousand_impressions"],
            "click_users_source": r["click_users_source"],
            "paid_buyers_source": r["paid_buyers_source"],
            "paid_orders_source": r["paid_orders_source"],
            "gmv_source": r["gmv_source"],
            "term_class": term_class,
            "leak_type": leak_type,
        }
        term_rows.append(row)
        if term_class == "opportunity":
            opportunities.append(row)
        elif term_class == "leak":
            leaks.append(row)
            if leak_type == "click_leak":
                click_leaks.append(row)
            elif leak_type == "conversion_leak":
                conversion_leaks.append(row)

    # Pareto: rank classifiable (n>=MIN) terms by gmv (when present) else traffic;
    # small-sample terms are listed but pushed to the end (unranked).
    def _rank_key(row: dict):
        classifiable = row["term_class"] != "small_sample"
        traffic = row["gmv"] if row["gmv"] is not None else (row["n"] or 0)
        return (classifiable, traffic)

    term_rows.sort(key=_rank_key, reverse=True)
    top_term = term_rows[0]["search_term"] if term_rows else None

    # Prefer the dominant leak lever so the recommendation is actionable at the
    # right funnel step; fall back to the generic leak lever when undecomposable.
    if opportunities:
        recommended_action = _LEVER_OPPORTUNITY
    elif click_leaks and len(click_leaks) >= len(conversion_leaks):
        recommended_action = _LEVER_CLICK_LEAK
    elif conversion_leaks:
        recommended_action = _LEVER_CONV_LEAK
    elif leaks:
        recommended_action = _LEVER_LEAK
    else:
        recommended_action = None

    caveats = [_OBS_CAVEAT]
    if click_base is not None:
        caveats.append("高流失词按点击率/转化率基线拆分为点击漏损 vs 转化漏损，定位对应杠杆。")
    click_coverage = _source_coverage(records, "click_users_source")
    buyer_coverage = _source_coverage(records, "paid_buyers_source")
    if click_coverage["forward_derived_rows"] or buyer_coverage["forward_derived_rows"]:
        caveats.append("点击/支付计数缺失时仅逐词由率正推；NULL 未按零处理，来源覆盖见关键数。")
    small = sum(1 for r in term_rows if r["term_class"] == "small_sample")
    if small:
        caveats.append(
            f"{small} 个搜索词曝光还不到 {MIN_ORDERS_FOR_RATE}，量太少，只列出来不下判断。"
        )
    leak_split = (
        f"（点击漏损 {qty(len(click_leaks))}、转化漏损 {qty(len(conversion_leaks))}）"
        if click_base is not None
        else ""
    )
    finding = Finding(
        title="高机会/高流失搜索词",
        conclusion=(
            f"{qty(len(opportunities))} 个高机会词、{qty(len(leaks))} 个高流失词{leak_split}"
            f"（基线成交效率 {_pct(baseline)}）。"
        ),
        evidence_strength=score_evidence(int(total_n), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_n)),
        key_numbers={
            "opportunity_count": len(opportunities),
            "leak_count": len(leaks),
            "click_leak_count": len(click_leaks),
            "conversion_leak_count": len(conversion_leaks),
            "baseline_effectiveness": baseline,
            "click_baseline": click_base,
            "conversion_baseline": conv_base,
            "top_term": top_term,
            "click_users_source": _source_summary(
                [record["click_users_source"] for record in records]
            ),
            "payers_source": _source_summary([record["paid_buyers_source"] for record in records]),
            "click_users_coverage": click_coverage,
            "paid_buyers_coverage": buyer_coverage,
            "paid_orders_coverage": _source_coverage(records, "paid_orders_source"),
            "gmv_coverage": _source_coverage(records, "gmv_source"),
        },
        caveats=caveats,
        recommended_action=recommended_action,
        evidence_reason=M.methodology_note(
            "下界高于基线判高机会、上界低于基线判高流失；高流失再按"
            "点击率<点击基线（点击漏损）或转化率<转化基线（转化漏损）拆分；"
            "点击/成交人数优先取真实值，行值缺失才由率正推。",
            M.METHOD_WILSON,
        ),
        confounders=_TERM_CONFOUNDERS,
        next_test="给高机会词做专门内容或加投，过阵子再看转化有没有起来；漏损词按漏损类型分别处理后，同样再复测一遍。",
    )
    return finding, term_rows


def _leak_type(click_rate, pay_conv, click_base, conv_base) -> str:
    """Attribute a leak to the click step or the conversion step.

    A term whose click-through is below the click baseline is a click leak
    (fix cover/title/term-goods match); one whose click-through is fine but
    whose conversion trails the conversion baseline is a conversion leak (fix
    detail page/price/trust). Undecomposable (no click data) → generic ``leak``.
    """
    if click_rate is not None and click_base is not None and click_rate < click_base:
        return "click_leak"
    if pay_conv is not None and conv_base is not None and pay_conv < conv_base:
        return "conversion_leak"
    return "leak"


def _pct(value: float | None) -> str:
    return f"{round(value * 100, 1)}%" if value is not None else "—"


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
                title="搜索效率不可诊断",
                conclusion="需要导出 search_overview（搜索概览）数据后才能诊断搜索效率。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["搜索概览没导出，得当成数据缺口补上。"],
                recommended_action="导出搜索概览（含载体、卡片曝光人数、点击率、成交转化率）后重新构建。",
            )
        ],
        tables={"carrier_search_efficiency": []},
        limitations=[reason],
    )
