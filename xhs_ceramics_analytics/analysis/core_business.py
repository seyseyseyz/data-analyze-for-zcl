"""核心经营结构诊断 (§2).

Sibling of ``refund_structure_diagnosis``. Same module contract, shared stat
helpers, and never-raise degradation discipline. Observational only — report
direction and effect size, never causal claims.

Design: docs/superpowers/specs/2026-07-03-core-business-diagnosis-design.md
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.funnel_scope import normalize_funnel_rows
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    bounded_rate,
    min_n_guard,
    rate_band,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.analytics.timeseries import (
    changepoint,
    dow_seasonality,
    week_over_week,
)
from xhs_ceramics_analytics.analytics.trends import direction_label, mom_change
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

TASK_ID = "core_business_diagnosis"
TITLE = "核心经营结构诊断"

_SNAPSHOT_CONFOUNDERS = ["促销节奏", "季节性", "流量结构变化"]
_STRUCTURE_CONFOUNDERS = ["渠道流量结构", "客群差异", "投放节奏"]
_FUNNEL_CONFOUNDERS = ["客群构成", "流量质量", "详情页与价格"]

_STAGE_ZH = {
    "visit_click": "访问→点击",
    "click_pay": "点击→支付",
    "visit_pay": "访问→支付",
}
_STAGE_LEVERS = {
    "visit_click": "优化店铺页首屏与商品卡点击诱因（主图、卖点、价格锚点）。",
    "click_pay": "优化商详转化（尺寸/规格说明、评价、优惠与信任状）。",
    "visit_pay": "全链路诊断，先补最弱阶段再看承接。",
}
_CARRIER_LEVER = "检视 note vs card 的投入产出，向高转化载体倾斜内容与预算。"


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "business_overview_daily"):
            return _missing_result("缺少 business_overview_daily 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        snapshot_finding, snap_rows, trend_rows = _snapshot_finding(con, limitations)
        findings.append(snapshot_finding)
        tables["business_snapshot"] = snap_rows
        if trend_rows:
            tables["business_trend"] = trend_rows

        struct_finding, struct_tables = _structure_finding(con, limitations)
        if struct_finding is not None:
            findings.append(struct_finding)
            tables.update(struct_tables)

        funnel_finding, funnel_tables = _funnel_finding(con, limitations)
        if funnel_finding is not None:
            findings.append(funnel_finding)
            tables.update(funnel_tables)
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
# Finding 1 — 整体经营快照 + 时间趋势 (always emitted)
# --------------------------------------------------------------------------- #
def _snapshot_finding(
    con, limitations: list[str]
) -> tuple[Finding, list[dict], list[dict]]:
    cols = _table_columns(con, "business_overview_daily")
    rows = _fetch_all(con, "business_overview_daily")

    def col_sum(name: str) -> float | None:
        return sum(_num(r.get(name)) for r in rows) if name in cols else None

    total_gmv = col_sum("gmv")
    total_orders = col_sum("paid_orders")
    total_buyers = col_sum("paid_buyers")
    total_units = col_sum("paid_units")

    aov, aov_source = _aov(cols, rows, total_gmv, total_buyers)
    pay_conv, conv_source = _pay_conversion(cols, rows, total_buyers)

    trend_rows, direction, steps, decomp = _gmv_trend(cols, rows, limitations)

    for missing in ("gmv", "paid_buyers"):
        if missing not in cols:
            limitations.append(f"business_overview_daily 缺少 {missing}，快照用现有列估计。")

    sample_size = int(total_orders or total_buyers or len(rows))
    conclusion = _snapshot_conclusion(
        total_gmv, total_buyers, aov, pay_conv, direction, decomp
    )
    caveats = ["观察性快照，非因果；聚合口径仅反映方向与规模。"]
    if aov_source == "column":
        caveats.append("客单价用 aov 列均值（paid_buyers 缺失或为零，无法反推）。")
    if conv_source == "column":
        caveats.append("支付转化率用 pay_conversion_uv 列均值（缺 product_visitors）。")
    elif conv_source is None:
        caveats.append("缺 product_visitors 与 pay_conversion_uv，无法给出支付转化率。")
    if decomp.get("changepoint_date") or decomp.get("peak_dow"):
        caveats.append("周对比/周内节律/结构性变化点为观察性分解，仅提示何时移动，非因果。")

    snapshot_row = {
        "gmv": total_gmv,
        "paid_orders": total_orders,
        "paid_buyers": total_buyers,
        "paid_units": total_units,
        "aov": aov,
        "aov_source": aov_source,
        "pay_conversion": pay_conv,
        "pay_conversion_source": conv_source,
    }
    finding = Finding(
        title="整体经营快照与趋势",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            sample_size, has_controls=False, confounder_count=1
        ),
        key_numbers={
            "total_gmv": total_gmv,
            "total_paid_orders": total_orders,
            "total_paid_buyers": total_buyers,
            "total_paid_units": total_units,
            "aov": aov,
            "pay_conversion": pay_conv,
            "trend_direction": direction,
            "wow_last_pct": decomp.get("wow_last_pct"),
            "peak_dow": decomp.get("peak_dow"),
            "changepoint_date": decomp.get("changepoint_date"),
        },
        caveats=caveats,
        evidence_reason="经营规模为聚合快照，趋势为逐期 GMV 走势，均为观察性描述。",
        confounders=_SNAPSHOT_CONFOUNDERS,
        appendix=str(steps) if steps else None,
    )
    return finding, [snapshot_row], trend_rows


def _aov(cols, rows, total_gmv, total_buyers) -> tuple[float | None, str | None]:
    if total_buyers and total_buyers > 0 and total_gmv is not None:
        return total_gmv / total_buyers, "derived"
    if "aov" in cols:
        vals = [_num(r.get("aov")) for r in rows if r.get("aov") is not None]
        return (sum(vals) / len(vals) if vals else None), "column"
    return None, None


def _pay_conversion(cols, rows, total_buyers) -> tuple[float | None, str | None]:
    if "product_visitors" in cols and total_buyers is not None:
        visitors = sum(_num(r.get("product_visitors")) for r in rows)
        if visitors > 0:
            return total_buyers / visitors, "real"
    if "pay_conversion_uv" in cols:
        vals = [bounded_rate(r.get("pay_conversion_uv")) for r in rows]
        vals = [v for v in vals if v is not None]
        return (sum(vals) / len(vals) if vals else None), "column"
    return None, None


def _gmv_trend(
    cols, rows, limitations: list[str]
) -> tuple[list[dict], str | None, list[dict], dict]:
    if "date" not in cols or "gmv" not in cols:
        limitations.append("business_overview_daily 缺少 date/gmv，跳过 GMV 趋势。")
        return [], None, [], {}
    dated = [(r.get("date"), _num(r.get("gmv"))) for r in rows if r.get("date") is not None]
    dated.sort(key=lambda t: str(t[0]))
    series = [(str(d), g) for d, g in dated]
    trend_rows = [{"date": p, "gmv": g} for p, g in series]
    if len(series) < 2:
        limitations.append("business_overview_daily 日期行不足两期，跳过 GMV 趋势。")
        return trend_rows, None, [], {}
    steps = mom_change(series)
    direction = direction_label(series[-1][1] - series[0][1])
    decomp = _decompose_gmv(series, trend_rows)
    return trend_rows, direction, steps, decomp


def _decompose_gmv(series: list[tuple[str, float]], trend_rows: list[dict]) -> dict:
    """Layer week-over-week, day-of-week, and changepoint structure over the slope.

    Every sub-metric degrades independently: too-short series → no WoW bucket,
    unparseable dates → no peak weekday, <4 points → no changepoint. The
    changepoint date is looked up from the series and mirrored onto trend_rows so
    the exported table flags the shift row.
    """
    weeks = week_over_week(series)
    wow_last_pct = next(
        (b["pct"] for b in reversed(weeks) if b["pct"] is not None), None
    )
    dow = dow_seasonality(series)
    peak_dow = dow.get("peak_dow")
    cp = changepoint([g for _, g in series])
    cp_idx = cp.get("index")
    changepoint_date = (
        series[cp_idx][0] if cp_idx is not None and 0 <= cp_idx < len(series) else None
    )
    if changepoint_date is not None:
        for row in trend_rows:
            row["is_changepoint"] = row["date"] == changepoint_date
    return {
        "wow_last_pct": wow_last_pct,
        "peak_dow": peak_dow,
        "changepoint_date": changepoint_date,
        "changepoint_shift": cp.get("shift"),
    }


def _snapshot_conclusion(total_gmv, total_buyers, aov, pay_conv, direction, decomp) -> str:
    parts = [f"累计 GMV {round(total_gmv or 0)} 元"]
    if total_buyers:
        parts.append(f"支付买家 {round(total_buyers)} 人")
    if aov is not None:
        parts.append(f"客单价 {round(aov)} 元")
    if pay_conv is not None:
        parts.append(f"支付转化率 {round(pay_conv * 100, 1)}%")
    tail = f"，GMV 趋势{direction}。" if direction else "，趋势数据不足。"
    extras: list[str] = []
    if decomp.get("changepoint_date"):
        extras.append(f"GMV 在 {decomp['changepoint_date']} 附近出现结构性变化")
    if decomp.get("peak_dow"):
        extras.append(f"周内 {decomp['peak_dow']} GMV 最高")
    extra = ("（" + "；".join(extras) + "）") if extras else ""
    return "、".join(parts) + tail + extra


# --------------------------------------------------------------------------- #
# Finding 2 — 载体 + 渠道结构拆解 (degrade-gated)
# --------------------------------------------------------------------------- #
def _structure_finding(
    con, limitations: list[str]
) -> tuple[Finding | None, dict[str, list[dict]]]:
    carrier_rows, carrier_dom = _carrier_structure(con, limitations)
    channel_rows, channel_test, channel_top = _channel_structure(con, limitations)

    if carrier_rows is None and channel_rows is None:
        limitations.append("缺少载体列与 traffic_source，跳过载体/渠道结构诊断。")
        return None, {}

    tables: dict[str, list[dict]] = {}
    key_numbers: dict[str, object] = {}
    parts: list[str] = []
    caveats = ["观察性拆解，非因果；份额为聚合快照。"]
    sample_size = 1

    if carrier_rows is not None:
        tables["carrier_structure"] = carrier_rows
        key_numbers["carrier_dominant"] = carrier_dom
        share = next(
            (r["gmv_share"] for r in carrier_rows if r["carrier"] == carrier_dom), None
        )
        parts.append(
            f"载体以 {_carrier_zh(carrier_dom)} 为主（GMV 占比 {round((share or 0) * 100)}%）"
        )

    if channel_rows is not None:
        tables["traffic_channel_structure"] = channel_rows
        top = max(channel_rows, key=lambda r: _num(r["click_users"]), default=None)
        if top is not None:
            parts.append(
                f"点击客数最高渠道为 {top['channel']}"
                f"（点击占比 {round((top['click_share'] or 0) * 100)}%）"
            )
        if channel_test is not None and channel_top is not None:
            a, b = channel_top
            diff = channel_test["diff"]
            key_numbers["channel_diff"] = diff
            key_numbers["channel_significant"] = _sig_gated(channel_test, diff)
            key_numbers["channel_top2"] = [a["channel"], b["channel"]]
            n = int(_num(a["click_users"]) + _num(b["click_users"]))
            sample_size = max(sample_size, n)
            verdict = _verdict(channel_test, diff)
            parts.append(
                f"{a['channel']} 与 {b['channel']} 支付转化差异{verdict}"
                f"（diff={round((diff or 0) * 100, 1)}pct）"
            )
            caveats.append("渠道显著性用两样本比例检验，并结合效应量（diff）判断。")
        else:
            key_numbers["channel_diff"] = None
            caveats.append("traffic_source 缺 paid_buyers 或渠道不足两组，仅报点击份额。")

    finding = Finding(
        title="载体与渠道结构",
        conclusion="；".join(parts) + "。" if parts else "结构数据不足。",
        evidence_strength=score_evidence(
            sample_size, has_controls=False, confounder_count=1
        ),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=_CARRIER_LEVER if carrier_rows is not None else None,
        evidence_reason="载体为 note/card 列的 GMV 份额拆解；渠道转化差异用两样本比例检验，观察性。",
        confounders=_STRUCTURE_CONFOUNDERS,
    )
    return finding, tables


def _carrier_structure(
    con, limitations: list[str]
) -> tuple[list[dict] | None, str | None]:
    cols = _table_columns(con, "business_overview_daily")
    if "note_gmv" not in cols or "card_gmv" not in cols:
        limitations.append("business_overview_daily 缺 note_gmv/card_gmv，跳过载体拆解。")
        return None, None
    rows = _fetch_all(con, "business_overview_daily")
    note_gmv = sum(_num(r.get("note_gmv")) for r in rows)
    card_gmv = sum(_num(r.get("card_gmv")) for r in rows)
    total_gmv = note_gmv + card_gmv
    has_orders = "note_paid_orders" in cols and "card_paid_orders" in cols
    note_o = sum(_num(r.get("note_paid_orders")) for r in rows) if has_orders else None
    card_o = sum(_num(r.get("card_paid_orders")) for r in rows) if has_orders else None
    total_o = (note_o or 0) + (card_o or 0) if has_orders else 0
    carrier_rows = []
    for name, gmv, orders in (("note", note_gmv, note_o), ("card", card_gmv, card_o)):
        carrier_rows.append(
            {
                "carrier": name,
                "gmv": gmv,
                "gmv_share": gmv / total_gmv if total_gmv else None,
                "paid_orders": orders,
                "order_share": (
                    (orders / total_o) if (has_orders and total_o) else None
                ),
            }
        )
    dominant = max(carrier_rows, key=lambda r: r["gmv"])["carrier"]
    return carrier_rows, dominant


def _channel_structure(
    con, limitations: list[str]
) -> tuple[list[dict] | None, dict | None, tuple[dict, dict] | None]:
    if not _table_exists(con, "traffic_source"):
        limitations.append("缺少 traffic_source 表，跳过渠道结构。")
        return None, None, None
    cols = _table_columns(con, "traffic_source")
    if "channel" not in cols or "product_click_users" not in cols:
        limitations.append("traffic_source 缺 channel/product_click_users，跳过渠道结构。")
        return None, None, None
    rows = _fetch_all(con, "traffic_source")
    has_buyers = "paid_buyers" in cols
    agg: dict[str, dict] = {}
    for r in rows:
        ch = r.get("channel")
        d = agg.setdefault(ch, {"channel": ch, "click_users": 0.0, "paid_buyers": 0.0})
        d["click_users"] += _num(r.get("product_click_users"))
        d["paid_buyers"] += _num(r.get("paid_buyers")) if has_buyers else 0.0
    total_clicks = sum(d["click_users"] for d in agg.values())
    channel_rows = [
        {
            "channel": d["channel"],
            "click_users": d["click_users"],
            "click_share": d["click_users"] / total_clicks if total_clicks else None,
            "paid_buyers": d["paid_buyers"] if has_buyers else None,
        }
        for d in agg.values()
    ]
    test = None
    top: tuple[dict, dict] | None = None
    if has_buyers:
        valid = [d for d in channel_rows if _num(d["click_users"]) > 0]
        if len(valid) >= 2:
            a, b = sorted(valid, key=lambda d: d["click_users"], reverse=True)[:2]
            test = two_proportion(
                _num(a["paid_buyers"]), _num(a["click_users"]),
                _num(b["paid_buyers"]), _num(b["click_users"]),
            )
            top = (a, b)
        else:
            limitations.append("traffic_source 有效渠道不足两组，跳过渠道显著性检验。")
    return channel_rows, test, top


# --------------------------------------------------------------------------- #
# Finding 3 — 店铺页转化漏斗诊断 (degrade-gated)
# --------------------------------------------------------------------------- #
def _funnel_finding(
    con, limitations: list[str]
) -> tuple[Finding | None, dict[str, list[dict]]]:
    if not _table_exists(con, "shop_page_funnel"):
        limitations.append("缺少 shop_page_funnel 表，跳过店铺页漏斗诊断。")
        return None, {}
    cols = _table_columns(con, "shop_page_funnel")
    if "shop_visitors" not in cols or "shop_payers" not in cols:
        limitations.append("shop_page_funnel 缺 shop_visitors/shop_payers，跳过漏斗诊断。")
        return None, {}
    raw_rows = _fetch_all(con, "shop_page_funnel")
    # Normalize scope before summing: drop the platform ``全部`` rollup and collapse
    # cumulative first-purchase windows, so visitors are not double-counted and the
    # audience test compares real segments (新客 vs 老客), never subset-vs-superset.
    rows, _rollup, canonical_cycle = normalize_funnel_rows(
        raw_rows, "audience_type" in cols, "first_purchase_cycle" in cols
    )
    visitors = sum(_num(r.get("shop_visitors")) for r in rows)
    payers = sum(_num(r.get("shop_payers")) for r in rows)
    has_clicks = "product_click_users" in cols
    clicks = sum(_num(r.get("product_click_users")) for r in rows) if has_clicks else None

    fallback = not (has_clicks and clicks and clicks > 0)
    if fallback:
        visit_click = _avg_rate(rows, "visit_click_rate") if "visit_click_rate" in cols else None
        click_pay = _avg_rate(rows, "click_pay_rate") if "click_pay_rate" in cols else None
    else:
        visit_click = clicks / visitors if visitors else None
        click_pay = payers / clicks if clicks else None
    visit_pay = payers / visitors if visitors else None
    if visit_pay is None and "visit_pay_rate" in cols:
        visit_pay = _avg_rate(rows, "visit_pay_rate")

    stage_denoms = {
        "visit_click": (clicks, visitors) if not fallback else (None, None),
        "click_pay": (payers, clicks) if not fallback else (None, None),
        "visit_pay": (payers, visitors),
    }
    stage_rates = {
        "visit_click": visit_click,
        "click_pay": click_pay,
        "visit_pay": visit_pay,
    }
    stage_rows = _stage_rows(stage_rates, stage_denoms)

    weakest = _weakest_stage(stage_rates)
    tables: dict[str, list[dict]] = {"shop_funnel_stages": stage_rows}
    aud_rows, aud_test, aud_top = _audience_conversion(cols, rows, limitations)
    if aud_rows is not None:
        tables["audience_conversion"] = aud_rows

    caveats = ["观察性漏斗，非因果；各阶段率为聚合快照。"]
    if fallback:
        caveats.append("缺 product_click_users，访问→点击/点击→支付用比率列均值。")
    if canonical_cycle is not None:
        caveats.append(
            f"首购周期为累计窗口，固定取 {canonical_cycle} 避免 180/365 天窗口重复计数。"
        )
    key_numbers: dict[str, object] = {
        "weakest_stage": weakest,
        "visit_click_rate": visit_click,
        "click_pay_rate": click_pay,
        "visit_pay_rate": visit_pay,
    }
    if aud_test is not None and aud_top is not None:
        a, b = aud_top
        key_numbers["audience_diff"] = aud_test["diff"]
        key_numbers["audience_significant"] = _sig_gated(aud_test, aud_test["diff"])
        key_numbers["audience_top2"] = [a["audience_type"], b["audience_type"]]
        caveats.append("客群转化差异用两样本比例检验，并结合效应量判断。")

    sample_size = int(visitors) if visitors else len(rows)
    finding = Finding(
        title="店铺页转化漏斗诊断",
        conclusion=_funnel_conclusion(weakest, stage_rates),
        evidence_strength=score_evidence(
            sample_size, has_controls=False, confounder_count=1
        ),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=_STAGE_LEVERS.get(weakest) if weakest else None,
        evidence_reason="各阶段转化优先用真实计数，弱阶段用 Wilson 区间守卫小样本；差异用两样本比例检验。",
        confounders=_FUNNEL_CONFOUNDERS,
    )
    return finding, tables


def _stage_rows(stage_rates: dict, stage_denoms: dict) -> list[dict]:
    rows: list[dict] = []
    for stage, rate in stage_rates.items():
        k, n = stage_denoms[stage]
        if n and min_n_guard(n):
            lo, hi = wilson_interval(_num(k), n)
            band = rate_band(lo, hi)
        else:
            lo = hi = None
            band = None
        rows.append(
            {
                "stage": stage,
                "stage_zh": _STAGE_ZH[stage],
                "rate": rate,
                "denominator": n,
                "ci_low": lo,
                "ci_high": hi,
                "ci_band": band,
            }
        )
    return rows


def _weakest_stage(stage_rates: dict) -> str | None:
    seq = {
        k: v
        for k, v in stage_rates.items()
        if k in ("visit_click", "click_pay") and v is not None
    }
    if seq:
        return min(seq, key=seq.get)
    return "visit_pay" if stage_rates.get("visit_pay") is not None else None


def _audience_conversion(
    cols, rows, limitations: list[str]
) -> tuple[list[dict] | None, dict | None, tuple[dict, dict] | None]:
    if "audience_type" not in cols:
        limitations.append("shop_page_funnel 缺 audience_type，跳过客群转化对比。")
        return None, None, None
    agg: dict[str, dict] = {}
    for r in rows:
        at = r.get("audience_type")
        d = agg.setdefault(at, {"audience_type": at, "visitors": 0.0, "payers": 0.0})
        d["visitors"] += _num(r.get("shop_visitors"))
        d["payers"] += _num(r.get("shop_payers"))
    aud_rows = [
        {
            "audience_type": d["audience_type"],
            "shop_visitors": d["visitors"],
            "shop_payers": d["payers"],
            "conversion": d["payers"] / d["visitors"] if d["visitors"] else None,
        }
        for d in agg.values()
    ]
    valid = [d for d in agg.values() if d["visitors"] > 0]
    if len(valid) < 2:
        limitations.append("shop_page_funnel 有效客群不足两组，跳过客群显著性检验。")
        return aud_rows, None, None
    a, b = sorted(valid, key=lambda d: d["visitors"], reverse=True)[:2]
    test = two_proportion(a["payers"], a["visitors"], b["payers"], b["visitors"])
    return aud_rows, test, (a, b)


def _funnel_conclusion(weakest: str | None, stage_rates: dict) -> str:
    if weakest is None:
        return "店铺页各阶段转化数据不足，无法定位漏点。"
    rate = stage_rates.get(weakest)
    pct = f"{round((rate or 0) * 100, 1)}%"
    return f"最弱阶段为 {_STAGE_ZH[weakest]}（转化 {pct}），优先补该阶段。"


# --------------------------------------------------------------------------- #
# Shared helpers (ported from refund_diagnosis)
# --------------------------------------------------------------------------- #
def _carrier_zh(carrier: str | None) -> str:
    return {"note": "笔记", "card": "商品卡"}.get(carrier, "未知载体")


_MIN_EFFECT_DIFF = 0.01


def _sig_gated(test: dict, diff: float | None) -> bool:
    """Effect-size-gated significance: z-test significant AND non-trivial diff."""
    return bool(test["significant"] and diff is not None and abs(diff) >= _MIN_EFFECT_DIFF)


def _verdict(test: dict, diff: float | None) -> str:
    return "显著" if _sig_gated(test, diff) else "不显著"


def _avg_rate(rows: list[dict], col: str) -> float | None:
    vals = [bounded_rate(r.get(col)) for r in rows]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


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
                title="核心经营结构不可诊断",
                conclusion="需要导出 business_overview_daily（每日经营概览）数据后才能诊断核心经营结构。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["每日经营概览缺失应视为导入缺口。"],
                recommended_action="导出每日经营概览（含 GMV、支付订单、支付买家、客单价）后重新构建。",
            )
        ],
        tables={"business_snapshot": []},
        limitations=[reason],
    )
