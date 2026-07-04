"""搜索效率诊断 (§5) — carrier search efficiency, conversion trend, term opps.

Sibling of ``refund_diagnosis``: same module contract, shared stat helpers, and
never-raise degradation discipline. Search derives the payer numerator *forward*
(impressions × click_rate × pay_conversion) and never reverse-derives
``n = k / rate``. Prefers real ``paid_buyers`` when the column is present.
Observational only — every finding carries confounders and an observational
caveat, and every denominator is guarded.
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
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

_LEVER_CARRIER_GAP = "向高转化载体倾斜搜索承接内容与预算。"
_LEVER_TREND_DECLINE = "排查搜索承接页与词-货匹配，止跌优先。"
_LEVER_OPPORTUNITY = "高机会词加投 / 做定向笔记与商详承接。"
_LEVER_LEAK = "高流失词降权 / 修词-货匹配 / 修承接页相关性。"
_LEVER_CLICK_LEAK = "高曝光低点击词：优化封面/标题与词-货匹配（点击漏损）。"
_LEVER_CONV_LEAK = "高点击低转化词：优化商详/价格/信任状承接（转化漏损）。"

_OBS_CAVEAT = "观察性诊断，非因果——载体/词间效率差异仅供假设生成。"


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


def _derive_payers(impr: float, click_rate, pay_conv) -> float:
    """Forward-derive payer count: impressions × click_rate × pay_conversion.

    Rates are normalised via ``bounded_rate``; a dirty/uninterpretable rate
    contributes 0 payers rather than raising. Never divides by a rate.
    """
    cr = bounded_rate(click_rate)
    pc = bounded_rate(pay_conv)
    if cr is None or pc is None:
        return 0.0
    return impr * cr * pc


def _carrier_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "search_overview")
    rows = _fetch_all(con, "search_overview")
    has_carrier = "carrier" in cols
    has_impr = "card_impression_users" in cols
    has_buyers = "paid_buyers" in cols
    has_click = "product_click_rate" in cols
    has_pay = "pay_conversion" in cols
    if not has_carrier:
        limitations.append("search_overview 缺少 carrier 列，按单一载体聚合。")
    if not has_impr:
        limitations.append("search_overview 缺少 card_impression_users 列，效率无法计算。")

    payers_source = "real" if has_buyers else "forward_derived"
    agg: dict[str, dict] = {}
    for r in rows:
        key = r.get("carrier") if has_carrier else "全部"
        impr = _num(r.get("card_impression_users")) if has_impr else 0.0
        if has_buyers:
            payers = _num(r.get("paid_buyers"))
        else:
            payers = _derive_payers(
                impr,
                r.get("product_click_rate") if has_click else None,
                r.get("pay_conversion") if has_pay else None,
            )
        bucket = agg.setdefault(key, {"impressions": 0.0, "payers": 0.0})
        bucket["impressions"] += impr
        bucket["payers"] += payers

    carrier_rows = [
        {
            "carrier": key,
            "impressions": round(v["impressions"]),
            "payers": round(v["payers"]),
            "effectiveness": (
                v["payers"] / v["impressions"] if v["impressions"] > 0 else None
            ),
        }
        for key, v in agg.items()
    ]
    carrier_rows.sort(key=lambda c: c["impressions"], reverse=True)

    eligible = [c for c in carrier_rows if c["impressions"] > 0]
    total_impr = sum(c["impressions"] for c in carrier_rows)
    caveats = [_OBS_CAVEAT]
    if not has_buyers:
        caveats.append("无 paid_buyers，成交人数由 曝光×点击率×成交转化率 正推估计。")

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
    }
    recommended_action = None

    if len(eligible) >= 2:
        top2 = eligible[:2]
        a, b = top2[0], top2[1]
        hi, lo = (a, b) if a["effectiveness"] >= b["effectiveness"] else (b, a)
        test = two_proportion(
            a["payers"], a["impressions"], b["payers"], b["impressions"]
        )
        # Report the gap in hi/lo order so its sign matches effectiveness_high/low
        # (two_proportion's diff is ordered by impression rank, which can differ).
        diff = hi["effectiveness"] - lo["effectiveness"]
        significant = bool(
            test["significant"] and diff >= _MIN_EFFECT_DIFF
        )
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
        caveats.append("显著性用两样本比例 z 检验，并要求非平凡效应量后再判显著。")
        if significant:
            recommended_action = _LEVER_CARRIER_GAP
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
            "无可比较对象。"
        )
    else:
        limitations.append("search_overview 无有效曝光的载体行，无法比较载体效率。")
        conclusion = "搜索概览无有效数据行，无法比较载体搜索效率。"

    finding = Finding(
        title="载体搜索效率对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_impr), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(int(total_impr)),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=recommended_action,
        evidence_reason="载体搜索成交效率=成交人数/曝光人数；成交人数优先取真实值，否则由率正推。",
        confounders=_CARRIER_CONFOUNDERS,
    )
    return finding, carrier_rows


def _trend_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "search_overview")
    if "date" not in cols or "pay_conversion" not in cols:
        limitations.append("search_overview 缺少 date/pay_conversion，跳过搜索转化趋势。")
        return None, []
    rows = _fetch_all(con, "search_overview")
    by_date: dict[str, list[float]] = {}
    for r in rows:
        pc = bounded_rate(r.get("pay_conversion"))
        if pc is None or r.get("date") is None:
            continue
        by_date.setdefault(str(r.get("date")), []).append(pc)
    period_avgs = [
        (d, sum(vals) / len(vals)) for d, vals in sorted(by_date.items()) if vals
    ]
    if len(period_avgs) < 2:
        limitations.append("搜索转化序列不足两期，跳过趋势。")
        return None, []

    series = period_avgs
    # Per-period deltas belong in the table columns, not a stringified appendix.
    steps = mom_change(series)
    trend_rows = [
        {"period": s["period"], "avg_pay_conversion": s["value"],
         "avg_pay_conversion_delta": s["delta"],
         "pct": s["pct"], "direction": s["direction"]}
        for s in steps
    ]
    # Direction from OLS slope over all periods — a noisy endpoint can't flip it.
    summary = trend_summary(series)
    direction = summary["direction"]
    recommended_action = _LEVER_TREND_DECLINE if direction == "下降" else None
    finding = Finding(
        title="搜索转化时间趋势",
        conclusion=(
            f"搜索成交转化率整体呈{direction}趋势（{qty(len(series))} 期，"
            f"起 {_pct(series[0][1])} 止 {_pct(series[-1][1])}）。"
        ),
        evidence_strength=score_evidence(
            len(series), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(len(series)),
        key_numbers={
            "trend_direction": direction,
            "first_rate": series[0][1],
            "last_rate": series[-1][1],
            "periods": len(series),
        },
        caveats=[
            _OBS_CAVEAT,
            "方向按最小二乘斜率判定（非首末两点），未对趋势做显著性检验。",
            "日度成交转化波动较大，逐期环比见搜索转化趋势表。",
        ],
        recommended_action=recommended_action,
        evidence_reason="逐期平均成交转化率走势，方向用最小二乘斜率，观察性描述。",
        confounders=_TREND_CONFOUNDERS,
        appendix="趋势方向用最小二乘斜率；逐期环比（delta/pct）见搜索转化趋势表。",
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
    has_buyers = "paid_buyers" in cols
    has_click = "product_click_rate" in cols
    has_pay = "pay_conversion" in cols
    has_gmv = "gmv" in cols
    rows = _fetch_all(con, "search_terms")

    records: list[dict] = []
    for r in rows:
        n = _num(r.get("card_impression_users"))
        click_rate = bounded_rate(r.get("product_click_rate")) if has_click else None
        pay_conv = bounded_rate(r.get("pay_conversion")) if has_pay else None
        if has_buyers:
            k = _num(r.get("paid_buyers"))
        else:
            k = _derive_payers(
                n,
                r.get("product_click_rate") if has_click else None,
                r.get("pay_conversion") if has_pay else None,
            )
        records.append(
            {
                "search_term": r.get("search_term"),
                "n": round(n),
                "k": round(k),
                "gmv": _num(r.get("gmv")) if has_gmv else None,
                "rate": (k / n) if n > 0 else None,
                "click_rate": click_rate,
                "pay_conv": pay_conv,
            }
        )

    total_k = sum(r["k"] for r in records)
    total_n = sum(r["n"] for r in records)
    baseline = total_k / total_n if total_n else 0.0

    # Traffic-weighted click + conversion baselines let us split a "leak" into a
    # click-side loss (low click-through) vs a conversion-side loss (clicks that
    # don't convert). Only computable when the click-rate column is present.
    click_den = sum(r["n"] for r in records if r["click_rate"] is not None)
    click_base = (
        sum(r["n"] * r["click_rate"] for r in records if r["click_rate"] is not None)
        / click_den
        if click_den
        else None
    )
    conv_den = sum(
        r["n"] * r["click_rate"] for r in records if r["click_rate"] is not None
    )
    conv_base = (
        sum(r["k"] for r in records if r["click_rate"] is not None) / conv_den
        if conv_den
        else None
    )

    term_rows: list[dict] = []
    opportunities: list[dict] = []
    leaks: list[dict] = []
    click_leaks: list[dict] = []
    conversion_leaks: list[dict] = []
    for r in records:
        n = r["n"]
        lo, hi = wilson_interval(r["k"], n)
        if not min_n_guard(n):
            term_class = "small_sample"
        elif lo > baseline:
            term_class = "opportunity"
        elif hi < baseline:
            term_class = "leak"
        else:
            term_class = "average"
        leak_type = (
            _leak_type(r["click_rate"], r["pay_conv"], click_base, conv_base)
            if term_class == "leak"
            else None
        )
        row = {
            "search_term": r["search_term"],
            "n": n,
            "k": r["k"],
            "rate": r["rate"],
            "wilson_low": lo,
            "wilson_high": hi,
            "gmv": r["gmv"],
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
        traffic = row["gmv"] if (has_gmv and row["gmv"] is not None) else row["n"]
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

    caveats = [_OBS_CAVEAT, "分类以 Wilson 区间对比加权基线，避免小样本误报。"]
    if click_base is not None:
        caveats.append("高流失词按点击率/转化率基线拆分为点击漏损 vs 转化漏损，定位对应杠杆。")
    small = sum(1 for r in term_rows if r["term_class"] == "small_sample")
    if small:
        caveats.append(
            f"{small} 个搜索词样本不足 {MIN_ORDERS_FOR_RATE} 曝光，仅列出未分类。"
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
        evidence_strength=score_evidence(
            int(total_n), has_controls=False, confounder_count=1
        ),
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
        },
        caveats=caveats,
        recommended_action=recommended_action,
        evidence_reason=(
            "以 Wilson 下界高于基线判高机会、上界低于基线判高流失；高流失再按"
            "点击率<点击基线（点击漏损）或转化率<转化基线（转化漏损）拆分；成交人数优先取真实值。"
        ),
        confounders=_TERM_CONFOUNDERS,
        next_test="对高机会词做定向内容/加投后复测转化；对漏损词按漏损类型分别处置后复测。",
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
    return float(value) if value is not None else 0.0


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
                caveats=["搜索概览缺失应视为导入缺口。"],
                recommended_action="导出搜索概览（含载体、卡片曝光人数、点击率、成交转化率）后重新构建。",
            )
        ],
        tables={"carrier_search_efficiency": []},
        limitations=[reason],
    )
