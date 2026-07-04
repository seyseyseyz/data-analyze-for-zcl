"""人群结构诊断 (§6) — audience_structure_diagnosis.

Sibling of ``refund_diagnosis``: same module contract, shared stat helpers,
never-raise degradation discipline. Observational only — no causal attribution.

Real counts available: ``shop_page_funnel`` carries genuine ``shop_visitors``
and ``shop_payers``, so audience/cycle conversion uses ``k = Σ shop_payers`` and
``n = Σ shop_visitors`` directly — no reverse derivation.
"""
from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analysis.funnel_scope import (
    ROLLUP as _ROLLUP,
    normalize_funnel_rows,
)
from xhs_ceramics_analytics.analysis.prose import pp
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.concentration import gini, hhi, top_share
from xhs_ceramics_analytics.analytics.confidence import (
    bounded_rate,
    min_n_guard,
    rate_band,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import (
    DescriptiveReliability,
    EvidenceStrength,
    score_evidence,
    score_reliability,
)

TASK_ID = "audience_structure_diagnosis"
TITLE = "人群结构诊断"

# A difference below this (absolute proportion) is treated as trivial even when
# the z-test flags it — "显著" is gated on a reported non-trivial effect size.
_MIN_MEANINGFUL_DIFF = 0.02

# ``shop_page_funnel`` scope (rollup drop + cumulative-window collapse) is defined
# once in ``funnel_scope``; ``_ROLLUP`` above is imported from there.
_DEDUP_CAVEAT = (
    "漏斗按天记录，跨天汇总的访客/支付人数可能重复计入回访用户，份额为近似。"
)

_LEVER_AUDIENCE = "低转化人群：针对该人群做承接内容与利益点定制（人群包 + 定向笔记）。"
_LEVER_CYCLE = "薄弱首购周期：首购人群补券/信任状；复购人群做召回与复购提醒。"
_LEVER_SOURCE = "高流量低转化来源：优化该来源承接页的相关性与首屏转化。"
_LEVER_COMPOSITION = (
    "人群构成倾斜：向高 GMV 贡献人群加投，低效人群缩量或换承接——"
    "份额为手工录入，先核对录入口径，再小步对照测试确认增量后固化。"
)
_LEVER_VALUE = (
    "高贡献人群与高集中来源倾斜加投；复购贡献偏低时加强会员召回与复购提醒，"
    "降低对单一来源的 GMV 依赖。"
)

_CONV_CONFOUNDERS = ["人群定义口径", "流量来源差异", "客单与品类"]
_CYCLE_CONFOUNDERS = ["券与活动节奏", "复购提醒机制", "客群成熟度"]
_SOURCE_CONFOUNDERS = ["来源意图差异", "承接页匹配", "活动引流结构"]
_VALUE_CONFOUNDERS = ["客群成熟度", "活动与券结构", "GMV 与退款口径", "累计窗口重叠"]

# Substrings that mark a repeat/returning audience segment (老客/复购/回购). New
# customers (新客) are everything else. Kept as tokens rather than exact labels so
# drifted export wording ("复购客") still classifies correctly.
_REPEAT_TOKENS = ("老", "复购", "回购", "复访")


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "shop_page_funnel"):
            return _missing_result("缺少 shop_page_funnel 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        conv_finding, conv_rows = _conversion_finding(con, limitations)
        findings.append(conv_finding)
        tables["audience_conversion_comparison"] = conv_rows

        cycle_finding, cycle_rows = _cycle_finding(con, limitations)
        if cycle_finding is not None:
            findings.append(cycle_finding)
            tables["first_purchase_cycle_funnel"] = cycle_rows

        source_finding, source_rows = _source_finding(con, limitations)
        if source_finding is not None:
            findings.append(source_finding)
            tables["shop_source_structure"] = source_rows

        value_finding, value_rows = _customer_value_finding(con, limitations)
        if value_finding is not None:
            findings.append(value_finding)
            tables["audience_gmv_contribution"] = value_rows

        # Finding 5 is always emitted (documented gap-notice when data absent).
        comp_finding, comp_rows = _composition_finding(con, limitations)
        findings.append(comp_finding)
        tables["audience_composition"] = comp_rows
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
# Finding 1 — 人群转化对比 (always emitted)
# --------------------------------------------------------------------------- #
def _conversion_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "shop_page_funnel")
    if "shop_visitors" not in cols or "shop_payers" not in cols:
        limitations.append(
            "shop_page_funnel 缺少 shop_visitors/shop_payers 列，无法计算人群转化。"
        )
        finding = Finding(
            title="人群转化对比",
            conclusion="shop_page_funnel 缺少访客/支付人数列，无法计算人群转化，需补充真实计数列。",
            evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            key_numbers={"group_count": 0, "overall_conversion": None},
            caveats=[M.causal_disclaimer("人群之间的流量结构和客群成熟度不同"), "缺少真实计数列。"],
            confounders=list(_CONV_CONFOUNDERS),
            evidence_reason="缺少 shop_visitors/shop_payers，无法基于真实计数计算转化。",
        )
        return finding, []

    rows = _fetch_all(con, "shop_page_funnel")
    has_audience = "audience_type" in cols
    has_cycle = "first_purchase_cycle" in cols

    # Split the platform ``全部`` rollup from the real audience segments, and fix a
    # single canonical first-purchase window so 180天/365天 do not double-count.
    segment_rows, rollup_rows, canonical_cycle = normalize_funnel_rows(
        rows, has_audience, has_cycle
    )
    if canonical_cycle is not None:
        limitations.append(
            f"首购周期为累计窗口，人群对比固定取 {canonical_cycle} 避免 180/365 天窗口重复计数。"
        )

    # Overall conversion prefers the platform 全部 rollup (true store-wide total);
    # falls back to the canonical-window segment sum when no rollup row exists.
    overall_source = rollup_rows if rollup_rows else segment_rows
    total_n = sum(_num(r.get("shop_visitors")) for r in overall_source)
    total_k = sum(_num(r.get("shop_payers")) for r in overall_source)
    overall = total_k / total_n if total_n else None

    comparison_rows: list[dict] = []
    if has_audience:
        groups: dict = {}
        for r in segment_rows:
            key = r.get("audience_type")
            g = groups.setdefault(key, {"n": 0.0, "k": 0.0})
            g["n"] += _num(r.get("shop_visitors"))
            g["k"] += _num(r.get("shop_payers"))
        for key, g in groups.items():
            conv = g["k"] / g["n"] if g["n"] else None
            comparison_rows.append(
                {
                    "audience_type": key,
                    "visitors": g["n"],
                    "payers": g["k"],
                    "conversion": conv,
                }
            )

    valid = sorted(
        [c for c in comparison_rows if c["visitors"] > 0],
        key=lambda c: c["visitors"],
        reverse=True,
    )

    # Retention lens: how dependent revenue is on new customers, and how much
    # better repeat customers convert than first-timers.
    by_type = {c["audience_type"]: c for c in comparison_rows}
    new_g, old_g = by_type.get("新客"), by_type.get("老客")
    new_customer_dependence: float | None = None
    repeat_conversion_premium: float | None = None
    if new_g and old_g:
        payers_total = new_g["payers"] + old_g["payers"]
        if payers_total > 0:
            new_customer_dependence = new_g["payers"] / payers_total
        new_conv, old_conv = new_g["conversion"], old_g["conversion"]
        if new_conv and new_conv > 0 and old_conv is not None:
            repeat_conversion_premium = old_conv / new_conv - 1
    retention_note = ""
    if new_customer_dependence is not None:
        retention_note += f" 新客贡献付费 {round(new_customer_dependence * 100)}%"
        if repeat_conversion_premium is not None:
            retention_note += f"、老客转化为新客的 {round(repeat_conversion_premium + 1, 1)} 倍"
        retention_note += "。"

    caveats = [M.causal_disclaimer("人群之间的流量结构和客群成熟度不同"), _DEDUP_CAVEAT]
    conv_methodology = False

    if has_audience and len(valid) >= 2:
        a, b = valid[0], valid[1]
        test = two_proportion(a["payers"], a["visitors"], b["payers"], b["visitors"])
        diff = test["diff"]
        significant = bool(
            test["significant"] and diff is not None and abs(diff) >= _MIN_MEANINGFUL_DIFF
        )
        sig_zh = "显著" if significant else "不显著"
        conclusion = (
            f"{a['audience_type']} 转化 {round((a['conversion'] or 0) * 100)}% vs "
            f"{b['audience_type']} {round((b['conversion'] or 0) * 100)}%，"
            f"差异 {pp(diff)}（{sig_zh}）。"
            f"整体进店转化 {round((overall or 0) * 100)}%。"
            + retention_note
        )
        key_numbers = {
            "group_count": len(valid),
            "top_audience": a["audience_type"],
            "top_conversion": a["conversion"],
            "second_audience": b["audience_type"],
            "second_conversion": b["conversion"],
            "diff": diff,
            "significant": significant,
            "ci_overlap": test["ci_overlap"],
            "overall_conversion": overall,
            "new_customer_dependence": new_customer_dependence,
            "repeat_conversion_premium": repeat_conversion_premium,
        }
        conv_methodology = True
    else:
        if has_audience:
            limitations.append("shop_page_funnel 人群维度不足两组，回退到整体转化，跳过人群对比。")
        else:
            limitations.append("shop_page_funnel 缺少 audience_type 列，回退到整体进店转化。")
        lo, hi = wilson_interval(total_k, total_n) if min_n_guard(total_n) else (None, None)
        band = f"（{rate_band(lo, hi)}）" if lo is not None else ""
        conclusion = (
            f"整体进店转化 {round((overall or 0) * 100)}%{band}。人群维度不足，未做人群对比。"
        )
        key_numbers = {
            "group_count": len(valid),
            "overall_conversion": overall,
            "ci_low": lo,
            "ci_high": hi,
            "diff": None,
            "fallback": True,
            "new_customer_dependence": new_customer_dependence,
            "repeat_conversion_premium": repeat_conversion_premium,
        }
        comparison_rows = [
            {
                "audience_type": "整体",
                "visitors": total_n,
                "payers": total_k,
                "conversion": overall,
            }
        ]

    evidence_reason = "转化率用真实 shop_payers/shop_visitors 计数，人群差异为观察性两样本比例检验。"
    if conv_methodology:
        evidence_reason = M.methodology_note(
            evidence_reason, M.METHOD_PROPORTION_TEST, M.METHOD_WILSON
        )

    finding = Finding(
        title="人群转化对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_n), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_n)),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=_LEVER_AUDIENCE,
        evidence_reason=evidence_reason,
        confounders=list(_CONV_CONFOUNDERS),
    )
    return finding, comparison_rows


# --------------------------------------------------------------------------- #
# Finding 2 — 首购周期漏斗 (degrade-gated)
# --------------------------------------------------------------------------- #
def _cycle_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "shop_page_funnel")
    if not {"first_purchase_cycle", "shop_visitors", "shop_payers"} <= cols:
        limitations.append(
            "shop_page_funnel 缺少 first_purchase_cycle/计数列，跳过首购周期漏斗。"
        )
        return None, []
    rows = _fetch_all(con, "shop_page_funnel")
    groups: dict = {}
    for r in rows:
        key = r.get("first_purchase_cycle")
        if key in (None, _ROLLUP):
            continue  # drop the 全部 rollup — it is not a real cycle bucket
        g = groups.setdefault(key, {"n": 0.0, "k": 0.0})
        g["n"] += _num(r.get("shop_visitors"))
        g["k"] += _num(r.get("shop_payers"))
    if not groups:
        limitations.append("shop_page_funnel 无首购周期数据，跳过首购周期漏斗。")
        return None, []

    cycle_rows: list[dict] = []
    for key, g in groups.items():
        conv = g["k"] / g["n"] if g["n"] else None
        lo, hi = wilson_interval(g["k"], g["n"]) if min_n_guard(g["n"]) else (None, None)
        cycle_rows.append(
            {
                "first_purchase_cycle": key,
                "visitors": g["n"],
                "payers": g["k"],
                "conversion": conv,
                "ci_low": lo,
                "ci_high": hi,
            }
        )
    cycle_rows.sort(key=lambda r: r["visitors"], reverse=True)

    convs = [r["conversion"] for r in cycle_rows if r["conversion"] is not None]
    gap = (max(convs) - min(convs)) if len(convs) >= 2 else None

    # Nested cumulative windows (180天 ⊂ 365天) can be numerically identical; a
    # "weakest" among windows that do not differ meaningfully is noise. Only
    # declare a weakest when the between-window gap clears a minimal threshold.
    windows_differ = gap is not None and gap >= _MIN_MEANINGFUL_DIFF
    guarded = [r for r in cycle_rows if r["ci_low"] is not None]
    weakest = min(guarded, key=lambda r: r["ci_low"], default=None) if windows_differ else None
    weakest_cycle = weakest["first_purchase_cycle"] if weakest else None

    caveats = [
        M.causal_disclaimer("各周期之间的活动节奏和客群成熟度不同"),
        "首购周期为累计窗口（180天 ⊂ 365天），各窗口访客/支付存在重叠，仅作漏斗对比不可相加。",
        _DEDUP_CAVEAT,
    ]
    evidence_reason_parts = [
        "各周期转化用真实计数聚合，最弱周期以 Wilson 下界排序，观察性。",
        M.METHOD_WILSON,
    ]
    if weakest_cycle:
        cycle_note = f"最弱周期为 {weakest_cycle}（转化明显偏低）。"
    elif gap is not None and not windows_differ:
        cycle_note = "各累计窗口转化无有效差异（差异低于阈值，视为同一窗口）。"
    else:
        cycle_note = "各周期样本量不足，暂无稳健最弱周期。"
        caveats.append("各周期样本量均不足 30，转化率结果仅供参考。")
        evidence_reason_parts.append("样本量不足 30 的周期未做置信区间判定。")
    conclusion = (
        f"共 {len(cycle_rows)} 个首购周期。"
        + cycle_note
        + (f" 周期间转化差 {pp(gap)}。" if gap is not None else "")
    )
    total_n = sum(r["visitors"] for r in cycle_rows)
    finding = Finding(
        title="首购周期漏斗",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_n), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_n)),
        key_numbers={
            "cycle_count": len(cycle_rows),
            "weakest_cycle": weakest_cycle,
            "conversion_gap": gap,
        },
        caveats=caveats,
        recommended_action=_LEVER_CYCLE,
        evidence_reason=M.methodology_note(*evidence_reason_parts),
        confounders=list(_CYCLE_CONFOUNDERS),
    )
    return finding, cycle_rows


# --------------------------------------------------------------------------- #
# Finding 3 — 进店来源结构 (degrade-gated)
# --------------------------------------------------------------------------- #
def _source_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "shop_page_source"):
        limitations.append("缺少 shop_page_source 表，跳过进店来源结构。")
        return None, []
    cols = _table_columns(con, "shop_page_source")
    if not {"source_page", "shop_visitors", "enter_pay_rate"} <= cols:
        limitations.append(
            "shop_page_source 缺少 source_page/shop_visitors/enter_pay_rate，跳过进店来源结构。"
        )
        return None, []
    has_gmv = "shop_gmv" in cols
    rows = _fetch_all(con, "shop_page_source")

    groups: dict = {}
    for r in rows:
        key = r.get("source_page")
        visitors = _num(r.get("shop_visitors"))
        rate = bounded_rate(r.get("enter_pay_rate")) or 0.0
        g = groups.setdefault(key, {"n": 0.0, "k": 0.0, "gmv": 0.0})
        g["n"] += visitors
        g["k"] += round(visitors * rate)
        if has_gmv:
            g["gmv"] += _num(r.get("shop_gmv"))
    if not groups:
        limitations.append("shop_page_source 无来源数据，跳过进店来源结构。")
        return None, []

    total_n = sum(g["n"] for g in groups.values())
    total_gmv = sum(g["gmv"] for g in groups.values())
    total_k = sum(g["k"] for g in groups.values())
    overall_rate = total_k / total_n if total_n else None

    source_rows: list[dict] = []
    for key, g in groups.items():
        pay_rate = g["k"] / g["n"] if g["n"] else None
        lo, hi = wilson_interval(g["k"], g["n"]) if min_n_guard(g["n"]) else (None, None)
        source_rows.append(
            {
                "source_page": key,
                "visitors": g["n"],
                "estimated_payers": g["k"],
                "visitor_share": (g["n"] / total_n) if total_n else None,
                "pay_rate": pay_rate,
                "gmv_share": (g["gmv"] / total_gmv) if (has_gmv and total_gmv) else None,
                "ci_low": lo,
                "ci_high": hi,
            }
        )
    source_rows.sort(key=lambda r: r["visitors"], reverse=True)

    top_source = source_rows[0]["source_page"] if source_rows else None
    # 承接优化点: highest-traffic source whose conversion is below the overall rate.
    optimize_source = None
    if overall_rate is not None:
        for r in source_rows:
            if r["visitors"] > 0 and r["pay_rate"] is not None and r["pay_rate"] < overall_rate:
                optimize_source = r["source_page"]
                break

    caveats = [M.causal_disclaimer("各来源之间的访客意图和承接页不同"), _DEDUP_CAVEAT]
    conclusion = (
        f"共 {len(source_rows)} 个进店来源，最大流量来源为 {top_source}"
        f"（访客占比 {round((source_rows[0]['visitor_share'] or 0) * 100)}%）。"
        + (f" 承接优化点：{optimize_source}（高流量但转化低于整体）。" if optimize_source else "")
    )
    finding = Finding(
        title="进店来源结构",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_n), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_n)),
        key_numbers={
            "source_count": len(source_rows),
            "top_source": top_source,
            "optimize_source": optimize_source,
            "overall_pay_rate": overall_rate,
        },
        caveats=caveats,
        recommended_action=_LEVER_SOURCE,
        evidence_reason=M.methodology_note(
            "来源支付数=bounded_rate(enter_pay_rate)×访客估计；份额与转化为观察性描述。",
            "支付人数由 rate×访客估计，非真实计数。",
        ),
        confounders=list(_SOURCE_CONFOUNDERS),
    )
    return finding, source_rows


# --------------------------------------------------------------------------- #
# Finding 4 — 客户价值贡献与集中度 (degrade-gated)
# --------------------------------------------------------------------------- #
def _customer_value_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    """新客/老客 GMV 贡献占比 + 复购人群 GMV 集中度.

    ``shop_page_source`` 是唯一同时带 ``audience_type`` 与 ``shop_gmv`` 的表。GMV 贡献
    按人群聚合得到份额；复购人群的 GMV 再按进店来源 (``source_page``) 计算 Gini/HHI，
    衡量收入是否押注在少数来源上。集中度是「来源层面」而非「顾客个体层面」——聚合导出
    无顾客粒度，caveat 明示不可读作少数大客户贡献。观察性，never-raise。
    """
    if not _table_exists(con, "shop_page_source"):
        limitations.append("缺少 shop_page_source 表，跳过客户价值贡献与集中度。")
        return None, []
    cols = _table_columns(con, "shop_page_source")
    if not {"audience_type", "shop_gmv"} <= cols:
        limitations.append(
            "shop_page_source 缺少 audience_type/shop_gmv，跳过客户价值贡献与集中度。"
        )
        return None, []
    has_cycle = "first_purchase_cycle" in cols
    rows = _fetch_all(con, "shop_page_source")

    # Collapse the platform 全部 rollup and nested cumulative windows so GMV is not
    # double-counted across 180天/365天 within a single audience segment.
    segment_rows, _rollup_rows, canonical_cycle = normalize_funnel_rows(rows, True, has_cycle)
    if canonical_cycle is not None:
        limitations.append(
            f"客户价值贡献固定取首购窗口 {canonical_cycle}，避免 180/365 天累计窗口重复计入 GMV。"
        )

    gmv_by_aud: dict = {}
    for r in segment_rows:
        key = r.get("audience_type")
        if key is None:
            continue
        gmv_by_aud[key] = gmv_by_aud.get(key, 0.0) + _num(r.get("shop_gmv"))
    total_gmv = sum(gmv_by_aud.values())
    if total_gmv <= 0:
        limitations.append("shop_page_source 无有效 GMV，跳过客户价值贡献与集中度。")
        return None, []

    contribution_rows = sorted(
        (
            {"audience_type": key, "gmv": gmv, "gmv_share": gmv / total_gmv}
            for key, gmv in gmv_by_aud.items()
        ),
        key=lambda r: r["gmv"],
        reverse=True,
    )
    top = contribution_rows[0]

    # Repeat-audience GMV share (老客/复购/回购), and its concentration across
    # source_page — a source-level Gini, explicitly not a customer-level one.
    repeat_types = [k for k in gmv_by_aud if any(t in str(k) for t in _REPEAT_TOKENS)]
    repeat_gmv = sum(gmv_by_aud[k] for k in repeat_types)
    repeat_gmv_share = repeat_gmv / total_gmv if total_gmv else None

    gini_v = hhi_v = top_v = None
    n_sources = 0
    if "source_page" in cols and repeat_types:
        by_source: dict = {}
        repeat_set = set(repeat_types)
        for r in segment_rows:
            if r.get("audience_type") in repeat_set:
                key = r.get("source_page")
                by_source[key] = by_source.get(key, 0.0) + _num(r.get("shop_gmv"))
        values = [v for v in by_source.values() if v > 0]
        n_sources = len(values)
        if n_sources >= 2:
            gini_v = gini(values)
            hhi_v = hhi(values)
            top_v = top_share(values)

    # Sample size for the reliability axis: real visitor counts when present,
    # else the number of contributing segment rows (a weaker proxy).
    if "shop_visitors" in cols:
        sample_n = int(sum(_num(r.get("shop_visitors")) for r in segment_rows))
    else:
        sample_n = len(segment_rows)

    conclusion = (
        f"GMV 贡献最高的人群为「{top['audience_type']}」"
        f"（占 {round(top['gmv_share'] * 100)}%）。"
    )
    if repeat_gmv_share is not None and repeat_types:
        conclusion += f" 复购人群贡献 GMV {round(repeat_gmv_share * 100)}%。"
    if gini_v is not None:
        conclusion += (
            f" 复购 GMV 在 {n_sources} 个进店来源上的集中度 Gini={round(gini_v, 2)}"
            f"（Top20% 来源占 {round((top_v or 0) * 100)}%）。"
        )

    caveats = [
        M.causal_disclaimer("活动、券与流量结构不同"),
        "集中度按进店来源 (source_page) 计算，是来源层面而非顾客个体层面——聚合导出无顾客粒度，"
        "不可读作少数大客户贡献。",
        _DEDUP_CAVEAT,
    ]

    finding = Finding(
        title="客户价值贡献与集中度",
        conclusion=conclusion,
        evidence_strength=score_evidence(sample_n, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sample_n),
        key_numbers={
            "audience_count": len(contribution_rows),
            "top_audience_by_gmv": top["audience_type"],
            "top_gmv_share": top["gmv_share"],
            "repeat_gmv_share": repeat_gmv_share,
            "repeat_gmv_gini": gini_v,
            "repeat_gmv_hhi": hhi_v,
            "repeat_source_count": n_sources,
        },
        caveats=caveats,
        recommended_action=_LEVER_VALUE,
        evidence_reason=(
            "GMV 贡献份额用真实 shop_gmv 聚合；集中度用来源层面 Gini/HHI，观察性描述。"
        ),
        confounders=list(_VALUE_CONFOUNDERS),
    )
    return finding, contribution_rows


# --------------------------------------------------------------------------- #
# Finding 5 — 人群构成 (permanently degraded in production; never dropped)
# --------------------------------------------------------------------------- #
def _composition_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    gap_conclusion = (
        "人群构成需手工录入 audience_profile（9.人群分析 为图片，无法自动导入）。"
        "请将截图中的人群分层份额与 GMV 手工整理为 audience_profile（列：audience_segment, share, gmv）后补录。"
    )
    if not _table_exists(con, "audience_profile"):
        limitations.append(
            "缺少 audience_profile 表（9.人群分析为图片，无导入器），人群构成需手工录入。"
        )
        return _composition_gap_finding(gap_conclusion), []

    cols = _table_columns(con, "audience_profile")
    if not {"audience_segment", "share", "gmv"} <= cols:
        limitations.append(
            "audience_profile 缺少 audience_segment/share/gmv 列，人群构成需手工补齐。"
        )
        return _composition_gap_finding(gap_conclusion), []

    rows = _fetch_all(con, "audience_profile")
    if not rows:
        limitations.append("audience_profile 无数据，人群构成需手工补录。")
        return _composition_gap_finding(gap_conclusion), []

    total_gmv = sum(_num(r.get("gmv")) for r in rows)
    comp_rows: list[dict] = []
    for r in rows:
        gmv = _num(r.get("gmv"))
        comp_rows.append(
            {
                "audience_segment": r.get("audience_segment"),
                "share": bounded_rate(r.get("share")),
                "gmv": gmv,
                "gmv_share": (gmv / total_gmv) if total_gmv else None,
            }
        )
    comp_rows.sort(key=lambda r: r["gmv"], reverse=True)
    top = comp_rows[0] if comp_rows else None
    top_segment = top["audience_segment"] if top else None

    conclusion = (
        f"共 {len(comp_rows)} 个人群分层，GMV 贡献最高的是 {top_segment}"
        f"（GMV 占比 {round((top['gmv_share'] or 0) * 100)}%）。"
        if top
        else "audience_profile 无有效人群分层。"
    )
    finding = Finding(
        title="人群构成",
        conclusion=conclusion,
        evidence_strength=EvidenceStrength.WEAK,
        key_numbers={
            "segment_count": len(comp_rows),
            "top_segment": top_segment,
            "top_gmv_share": top["gmv_share"] if top else None,
        },
        caveats=[M.causal_disclaimer("人群定义口径不同"), "份额为手工录入，口径需自校。"],
        # 手工录入快照 → 描述可靠性固定为 LOW，与其他计算型 finding 一样显式给出该正交轴。
        descriptive_reliability=DescriptiveReliability.LOW,
        recommended_action=_LEVER_COMPOSITION,
        evidence_reason="人群构成为手工录入的份额/GMV 快照，仅作结构描述，无统计推断。",
        confounders=[],
    )
    return finding, comp_rows


def _composition_gap_finding(conclusion: str) -> Finding:
    return Finding(
        title="人群构成",
        conclusion=conclusion,
        evidence_strength=EvidenceStrength.NOT_JUDGABLE,
        key_numbers={"segment_count": 0, "top_segment": None},
        caveats=["人群构成为快照，非因果；当前无可用数据源，属已知导入缺口。"],
        recommended_action=(
            "将『9.人群分析』截图中的人群分层份额与 GMV 手工录入 audience_profile"
            "（列：audience_segment, share, gmv）后重新构建。"
        ),
        evidence_reason="audience_profile 无自动导入器（PNG 来源），生产环境默认缺失，需手工补录。",
        confounders=[],
    )


# --------------------------------------------------------------------------- #
# Shared helpers (ported from refund_diagnosis)
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
                title="人群结构不可诊断",
                conclusion="需要导出 shop_page_funnel（店铺页人群漏斗）数据后才能诊断人群结构。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["店铺页人群漏斗缺失应视为导入缺口。"],
                recommended_action="导出店铺页人群漏斗（含 audience_type、first_purchase_cycle、访客/支付人数）后重新构建。",
            )
        ],
        tables={"audience_conversion_comparison": []},
        limitations=[reason],
    )
