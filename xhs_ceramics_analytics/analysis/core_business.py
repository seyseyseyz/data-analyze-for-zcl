"""核心经营结构诊断 (§2).

Sibling of ``refund_structure_diagnosis``. Same module contract, shared stat
helpers, and never-raise degradation discipline. Observational only — report
direction and effect size, never causal claims.

Design: docs/superpowers/specs/2026-07-03-core-business-diagnosis-design.md
"""
from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis.funnel_scope import normalize_funnel_rows
from xhs_ceramics_analytics.analysis.prose import cn_date, money, pp, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    bounded_rate,
    min_detectable_effect,
    min_n_guard,
    rate_band,
    relative_lift,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.analytics.benchmark import percentile_label, self_percentile
from xhs_ceramics_analytics.analytics.decomposition import gmv_bridge
from xhs_ceramics_analytics.analytics.timeseries import (
    anomaly_days,
    changepoints,
    dow_seasonality,
    iso_date,
    iso_week,
    week_over_week_calendar,
)
from xhs_ceramics_analytics.analytics.trends import (
    direction_from_summary,
    mom_change,
    trend_extrapolation,
    trend_summary,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence, score_reliability

TASK_ID = "core_business_diagnosis"
TITLE = "核心经营结构诊断"

# D1 前瞻: how many days ahead the significant trend is projected (one week).
_PROJECTION_HORIZON = 7

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

        benchmark_finding, benchmark_rows = _benchmark_finding(con, limitations)
        if benchmark_finding is not None:
            findings.append(benchmark_finding)
            tables["business_self_benchmark"] = benchmark_rows

        bridge_finding, bridge_tables = _growth_attribution_finding(con, limitations)
        if bridge_finding is not None:
            findings.append(bridge_finding)
            tables.update(bridge_tables)

        struct_finding, struct_tables = _structure_finding(con, limitations)
        if struct_finding is not None:
            findings.append(struct_finding)
            tables.update(struct_tables)

        funnel_finding, funnel_tables = _funnel_finding(con, limitations)
        if funnel_finding is not None:
            findings.append(funnel_finding)
            tables.update(funnel_tables)

        event_finding, event_rows = _event_lift_finding(con, limitations)
        if event_finding is not None:
            findings.append(event_finding)
            tables["event_activity_lift"] = event_rows
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

    trend_rows, direction, summary, decomp = _gmv_trend(cols, rows, limitations)

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
        dow_note = "已去趋势" if decomp.get("detrended_dow") else "未去趋势（序列过短）"
        caveats.append(
            f"周对比按 ISO 日历周（非行数）；周内节律{dow_note}后取残差均值；"
            "结构性变化点为递归多变点分解，均为观察性，仅提示何时移动，非因果。"
        )
    if summary and summary.get("n"):
        caveats.append(
            "趋势方向按逐日 GMV 的最小二乘斜率判定（非首末两点），日度数据波动较大，"
            "逐期环比见趋势表。"
        )
    if decomp.get("anomaly_count"):
        sample = "、".join(cn_date(d) for d in decomp.get("anomaly_dates", [])[:3])
        caveats.append(
            f"已标记 {decomp['anomaly_count']} 个异常日（去趋势后 GMV 偏离 ±2σ，如 {sample}），"
            "多为大促/断货/数据缺口所致，是观察性提示而非因果。"
        )
    if decomp.get("projected_gmv") is not None:
        caveats.append(
            f"末尾的 {decomp.get('projection_horizon')} 日 GMV 外推为显著趋势线的线性延伸，"
            "是观察性提示、非预测承诺，活动或季节变化会使其失真。"
        )

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
        descriptive_reliability=score_reliability(sample_size),
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
            "anomaly_day_count": decomp.get("anomaly_count"),
            "projected_gmv_next": decomp.get("projected_gmv"),
        },
        caveats=caveats,
        evidence_reason="经营规模为聚合快照，趋势为逐期 GMV 走势，均为观察性描述。",
        confounders=_SNAPSHOT_CONFOUNDERS,
        appendix=(
            "趋势方向用最小二乘斜率判定；逐期环比（delta/pct）见 business_trend 表；"
            "变点用最小段长守卫排除端点噪声。"
            if summary and summary.get("n")
            else None
        ),
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
) -> tuple[list[dict], str | None, dict, dict]:
    if "date" not in cols or "gmv" not in cols:
        limitations.append("business_overview_daily 缺少 date/gmv，跳过 GMV 趋势。")
        return [], None, [], {}
    dated = [(r.get("date"), _num(r.get("gmv"))) for r in rows if r.get("date") is not None]
    dated.sort(key=lambda t: str(t[0]))
    # Normalize raw table dates (int YYYYMMDD or ISO) to canonical ISO once, at the
    # boundary where daily rows become the trend series. Every downstream consumer —
    # trend_rows, mom_change periods, changepoint matching, prose — inherits ISO from
    # this single point; _parse_date still accepts both forms for the math helpers.
    series = [(cn_date(d), g) for d, g in dated]
    trend_rows = [{"date": p, "gmv": g} for p, g in series]
    if len(series) < 2:
        limitations.append("business_overview_daily 日期行不足两期，跳过 GMV 趋势。")
        return trend_rows, None, {}, {}
    # Per-period deltas live in the table columns (not a stringified appendix dump).
    steps = mom_change(series)
    trend_rows = [
        {"date": s["period"], "gmv": s["value"], "gmv_delta": s["delta"],
         "pct": s["pct"], "direction": s["direction"]}
        for s in steps
    ]
    # Significance-gated direction: a near-zero slope buried in daily noise reads as
    # 趋势不明, not a spurious 上升/下降 (A1 — the OLS slope alone over-claims).
    summary = trend_summary(series)
    decomp = _decompose_gmv(series, trend_rows)
    return trend_rows, direction_from_summary(summary), summary, decomp


# --------------------------------------------------------------------------- #
# Finding — 自身历史基准分位 (C1): no external benchmark exists, so anchor the
# latest week against the account's own weekly distribution.
# --------------------------------------------------------------------------- #
_BENCHMARK_MIN_WEEKS = 4
_BENCHMARK_CONFOUNDERS = ["促销与活动节奏", "季节性", "流量结构变化"]


def _benchmark_finding(con, limitations: list[str]):
    """Anchor the latest ISO week's GMV / 支付转化 to the shop's own history.

    A raw "2% 转化" is meaningless without a yardstick; this shop has no external
    industry baseline, so the yardstick is its *own* recent weeks. Each metric's
    latest week is placed as a self-percentile of all observed weeks. Degrades to
    ``(None, {})`` when there is no date column or fewer than
    ``_BENCHMARK_MIN_WEEKS`` weeks — a percentile over 2–3 points is noise.
    """
    cols = _table_columns(con, "business_overview_daily")
    rows = _fetch_all(con, "business_overview_daily")
    if "date" not in cols:
        return None, {}

    metrics = _weekly_metric_series(cols, rows)
    bench_rows = []
    for metric_key, series in metrics.items():
        if len(series) < _BENCHMARK_MIN_WEEKS:
            continue
        latest_week, latest_value = series[-1]
        history = [v for _, v in series]
        pct = self_percentile(latest_value, history)
        if pct is None:
            continue
        bench_rows.append(
            {
                "metric": _BENCHMARK_LABELS.get(metric_key, metric_key),
                "latest_period": latest_week,
                "value": round(latest_value, 4),
                "self_percentile": round(pct, 4),
                "percentile_label": percentile_label(pct),
                "periods": len(series),
            }
        )

    if not bench_rows:
        limitations.append("周期不足 4 个 ISO 周或缺 GMV/转化列，跳过自身历史基准分位。")
        return None, []

    headline = max(bench_rows, key=lambda r: r["self_percentile"])
    worst = min(bench_rows, key=lambda r: r["self_percentile"])
    n_weeks = max(r["periods"] for r in bench_rows)
    conclusion = (
        f"以近 {n_weeks} 个 ISO 周为自身基准，最新一周"
        f"「{headline['metric']}」处于 {headline['percentile_label']} 分位"
    )
    if worst["metric"] != headline["metric"]:
        conclusion += (
            f"，而「{worst['metric']}」仅 {worst['percentile_label']} 分位、相对偏弱。"
        )
    else:
        conclusion += "。"

    n = n_weeks
    return (
        Finding(
            title="自身历史基准分位",
            conclusion=conclusion,
            evidence_strength=score_evidence(n, has_controls=False, confounder_count=2),
            descriptive_reliability=score_reliability(n),
            key_numbers={
                "periods": n_weeks,
                "top_metric": headline["metric"],
                "top_percentile": headline["percentile_label"],
                "weak_metric": worst["metric"],
                "weak_percentile": worst["percentile_label"],
            },
            caveats=[
                "分位是相对自身历史的排名，非绝对好坏；周期越少越易受单周波动影响。",
                "GMV 按周求和、转化率按周内日均聚合；促销周天然偏高，读数需结合活动节奏。",
            ],
            recommended_action=(
                "把最新周处于低分位的指标列为本周重点，对照高分位周的动作复盘差异。"
            ),
            evidence_reason=(
                "用 analytics.benchmark.self_percentile 把最新周放进自身周度分布的中位秩分位，"
                "为观察性相对定位，无外部对照。"
            ),
            confounders=_BENCHMARK_CONFOUNDERS,
        ),
        bench_rows,
    )


_BENCHMARK_LABELS = {
    "weekly_gmv": "周 GMV",
    "weekly_pay_conversion": "周支付转化率",
}


def _weekly_metric_series(cols, rows) -> dict[str, list[tuple[str, float]]]:
    """ISO-week series per benchmarkable metric.

    GMV is summed within a week; 支付转化 is the week's mean of daily
    ``pay_conversion_uv`` (the only per-day rate column). Weeks are keyed by ISO
    ``YYYY-Www`` and returned in chronological order. A metric with no usable
    column is simply absent from the result.
    """
    gmv_by_week: dict[str, float] = {}
    conv_by_week: dict[str, list[float]] = {}
    has_gmv = "gmv" in cols
    has_conv = "pay_conversion_uv" in cols
    for r in rows:
        week = iso_week(r.get("date"))
        if week is None:
            continue
        if has_gmv:
            gmv_by_week[week] = gmv_by_week.get(week, 0.0) + _num(r.get("gmv"))
        if has_conv:
            rate = bounded_rate(r.get("pay_conversion_uv"))
            if rate is not None:
                conv_by_week.setdefault(week, []).append(rate)

    series: dict[str, list[tuple[str, float]]] = {}
    if gmv_by_week:
        series["weekly_gmv"] = [(w, gmv_by_week[w]) for w in sorted(gmv_by_week)]
    if conv_by_week:
        series["weekly_pay_conversion"] = [
            (w, sum(v) / len(v)) for w, v in sorted(conv_by_week.items())
        ]
    return series


# A lift comparison needs at least this many days on each side; a single event day
# vs a single baseline day is anecdote, not a rate.
_EVENT_MIN_DAYS = 2
_EVENT_CONFOUNDERS = ["活动期降价/满减", "活动期投放加码", "季节性与节假日", "事件选择性排布"]


def _event_lift_finding(con, limitations: list[str]):
    """活动期 vs 平销期 的日均 GMV 与支付转化抬升（两比例检验 + 相对效应量）。

    Splits every business day into event / baseline by matching ``calendar_events``
    dates against ``business_overview_daily`` on a shared day key (so mixed date
    calibers still align). GMV lift is a descriptive daily-mean ratio (continuous,
    no p-value); conversion lift carries a two-proportion significance flag. Degrades
    to ``(None, [])`` without a calendar table, without a GMV column, or when either
    side has fewer than ``_EVENT_MIN_DAYS`` days. Observational — a promotion-day GMV
    bump largely reflects the promotion itself, never a clean causal lift.
    """
    if not _table_exists(con, "calendar_events"):
        return None, []
    cols = _table_columns(con, "business_overview_daily")
    if "date" not in cols or "gmv" not in cols:
        return None, []
    if "date" not in _table_columns(con, "calendar_events"):
        return None, []

    event_dates = {iso_date(r.get("date")) for r in _fetch_all(con, "calendar_events")}
    event_dates.discard(None)
    if not event_dates:
        return None, []

    has_conv = "product_visitors" in cols and "paid_buyers" in cols
    ev = {"days": 0, "gmv": 0.0, "visitors": 0.0, "payers": 0.0}
    base = {"days": 0, "gmv": 0.0, "visitors": 0.0, "payers": 0.0}
    for r in _fetch_all(con, "business_overview_daily"):
        key = iso_date(r.get("date"))
        if key is None:
            continue
        bucket = ev if key in event_dates else base
        bucket["days"] += 1
        bucket["gmv"] += _num(r.get("gmv"))
        if has_conv:
            bucket["visitors"] += _num(r.get("product_visitors"))
            bucket["payers"] += _num(r.get("paid_buyers"))

    if ev["days"] < _EVENT_MIN_DAYS or base["days"] < _EVENT_MIN_DAYS:
        limitations.append("活动日或平销日不足 2 天，跳过活动抬升对比。")
        return None, []

    rows = []
    ev_gmv = ev["gmv"] / ev["days"]
    base_gmv = base["gmv"] / base["days"]
    gmv_lift = (ev_gmv - base_gmv) / base_gmv if base_gmv else None
    rows.append(
        {
            "metric": "日均 GMV",
            "event_value": round(ev_gmv, 2),
            "baseline_value": round(base_gmv, 2),
            "lift_pct": round(gmv_lift * 100, 1) if gmv_lift is not None else None,
            "significance": "描述性",
        }
    )

    conv_significant = None
    if has_conv and ev["visitors"] > 0 and base["visitors"] > 0:
        tp = two_proportion(ev["payers"], ev["visitors"], base["payers"], base["visitors"])
        rl = relative_lift(ev["payers"], ev["visitors"], base["payers"], base["visitors"])
        conv_significant = tp["significant"]
        rows.append(
            {
                "metric": "支付转化率",
                "event_value": round(ev["payers"] / ev["visitors"], 4),
                "baseline_value": round(base["payers"] / base["visitors"], 4),
                "lift_pct": round(rl["lift"] * 100, 1) if rl["lift"] is not None else None,
                "significance": "显著" if tp["significant"] else "不显著",
            }
        )

    gmv_dir = "高" if (gmv_lift or 0) >= 0 else "低"
    conclusion = (
        f"活动期日均 GMV {money(ev_gmv)}，较平销期（{money(base_gmv)}）"
        f"{gmv_dir} {abs(round((gmv_lift or 0) * 100, 1))}%"
    )
    if conv_significant is not None:
        conclusion += f"；支付转化差异{'显著' if conv_significant else '不显著'}。"
    else:
        conclusion += "。"

    n = ev["days"] + base["days"]
    return (
        Finding(
            title="活动期抬升对比",
            conclusion=conclusion,
            evidence_strength=score_evidence(n, has_controls=False, confounder_count=3),
            descriptive_reliability=score_reliability(n),
            key_numbers={
                "event_days": ev["days"],
                "baseline_days": base["days"],
                "gmv_lift_pct": round(gmv_lift * 100, 1) if gmv_lift is not None else None,
                "conversion_significant": conv_significant,
            },
            caveats=[
                "活动期 GMV 抬升主要来自降价/满减与投放加码本身，是活动的组成，不能读作「活动很成功」的独立因果。",
                "活动日与平销日非随机分配（大促常压在周末/节假日），季节性与流量结构是主要混淆项。",
            ],
            recommended_action=(
                "对照抬升幅度与活动让利成本核算净收益，再决定活动强度与频率；"
                "转化差异不显著时优先复盘承接页而非加大让利。"
            ),
            evidence_reason=(
                "按 calendar_events 日期切分活动/平销两组，GMV 取日均相对差、"
                "转化用 analytics.confidence.two_proportion 做两比例检验；观察性对比、无随机对照。"
            ),
            confounders=_EVENT_CONFOUNDERS,
        ),
        rows,
    )


def _decompose_gmv(series: list[tuple[str, float]], trend_rows: list[dict]) -> dict:
    """Layer week-over-week, day-of-week, and changepoint structure over the slope.

    Each sub-metric degrades independently. Weeks are bucketed by real ISO calendar
    (A3) so a missing day never drifts the Mon–Sun boundary; weekday seasonality is
    detrended (A2) so a rising series' late weekdays are not mislabelled "peak"; and
    the level shifts come from recursive multi-changepoint detection (A5), of which
    the strongest is surfaced as the headline date and mirrored onto trend_rows.
    """
    weeks = week_over_week_calendar(series)
    wow_last_pct = next(
        (b["pct"] for b in reversed(weeks) if b["pct"] is not None), None
    )
    dow = dow_seasonality(series)
    peak_dow = dow.get("peak_dow")
    detrended_dow = dow.get("detrended", False)
    cps = changepoints([g for _, g in series], max_k=2)
    # The strongest break (largest relative shift) is the headline; all detected
    # breaks flag their row so the trend table shows every structural move.
    strongest = max(cps, key=lambda c: abs(c["rel_shift"]), default=None)
    cp_dates = {
        series[c["index"]][0]
        for c in cps
        if 0 <= c["index"] < len(series)
    }
    changepoint_date = (
        series[strongest["index"]][0]
        if strongest is not None and 0 <= strongest["index"] < len(series)
        else None
    )
    if cp_dates:
        for row in trend_rows:
            row["is_changepoint"] = row["date"] in cp_dates
    # D1 前瞻: flag ±2σ anomaly days (detrended residual outliers) and, when the
    # trend is significant, project it one horizon ahead. Both are observational
    # hints — the projection is the trend line extended, never a prediction promise.
    anomalies = anomaly_days(series)
    anomaly_by_date = {a["date"]: a for a in anomalies}
    if anomaly_by_date:
        for row in trend_rows:
            row["is_anomaly"] = row["date"] in anomaly_by_date
    projection = trend_extrapolation(series, horizon=_PROJECTION_HORIZON, non_negative=True)
    return {
        "wow_last_pct": wow_last_pct,
        "peak_dow": peak_dow,
        "detrended_dow": detrended_dow,
        "changepoint_date": changepoint_date,
        "changepoint_shift": strongest["shift"] if strongest is not None else None,
        "changepoint_count": len(cps),
        "anomaly_count": len(anomalies),
        "anomaly_dates": [a["date"] for a in anomalies],
        "projected_gmv": projection["projected_value"] if projection else None,
        "projection_horizon": _PROJECTION_HORIZON if projection else None,
        "projection_direction": projection["direction"] if projection else None,
    }


def _snapshot_conclusion(total_gmv, total_buyers, aov, pay_conv, direction, decomp) -> str:
    parts = [f"累计 GMV {money(total_gmv)} 元"]
    if total_buyers:
        parts.append(f"支付买家 {qty(total_buyers)} 人")
    if aov is not None:
        parts.append(f"客单价 {money(aov)} 元")
    if pay_conv is not None:
        parts.append(f"支付转化率 {round(pay_conv * 100, 1)}%")
    if direction is None:
        tail = "，趋势数据不足。"
    elif direction == "趋势不明":
        tail = "，GMV 趋势不明（日度斜率未过显著性门槛）。"
    else:
        tail = f"，GMV 趋势{direction}。"
    extras: list[str] = []
    if decomp.get("changepoint_date"):
        extras.append(f"GMV 在 {cn_date(decomp['changepoint_date'])} 附近出现结构性变化")
    if decomp.get("peak_dow"):
        extras.append(f"周内 {decomp['peak_dow']} GMV 最高")
    extra = ("（" + "；".join(extras) + "）") if extras else ""
    return "、".join(parts) + tail + extra


# --------------------------------------------------------------------------- #
# Finding 1.5 — 增长归因 GMV 桥 (degrade-gated, ★highest value)
# --------------------------------------------------------------------------- #
_BRIDGE_CONFOUNDERS = ["促销与活动", "流量结构变化", "品类结构变化"]
_FACTOR_LEVER = {
    "traffic": "GMV 变化主要由流量驱动：稳固当前流量来源，并检视转化/客单是否被稀释。",
    "conversion": "GMV 变化主要由转化驱动：延续起效的详情页/信任状/优惠，扩大到更多商品。",
    "aov": "GMV 变化主要由客单价驱动：核对是价格结构还是连带/客群变化，评估可持续性。",
}


def _growth_attribution_finding(
    con, limitations: list[str]
) -> tuple[Finding | None, dict[str, list[dict]]]:
    """Decompose the window's ΔGMV into traffic × conversion × AOV (LMDI bridge).

    Splits the dated series into an early and a late half, aggregates each into
    (gmv, visitors, buyers), and runs :func:`gmv_bridge`. Needs product_visitors +
    paid_buyers to reverse-derive conversion and AOV; missing either → degrade with
    a limitation. Deterministic attribution, not causal.
    """
    cols = _table_columns(con, "business_overview_daily")
    if not {"date", "gmv", "paid_buyers", "product_visitors"} <= cols:
        limitations.append(
            "business_overview_daily 缺 product_visitors 或 paid_buyers，跳过增长归因（GMV 桥）。"
        )
        return None, {}
    rows = _fetch_all(con, "business_overview_daily")
    dated = [(str(r.get("date")), r) for r in rows if r.get("date") is not None]
    if len(dated) < 4:
        limitations.append("business_overview_daily 日期行不足四期，跳过增长归因（GMV 桥）。")
        return None, {}
    dated.sort(key=lambda t: t[0])
    mid = len(dated) // 2
    early = [r for _, r in dated[:mid]]
    late = [r for _, r in dated[mid:]]

    def _aggregate(part: list[dict]) -> dict:
        return {
            "gmv": sum(_num(r.get("gmv")) for r in part),
            "visitors": sum(_num(r.get("product_visitors")) for r in part),
            "buyers": sum(_num(r.get("paid_buyers")) for r in part),
        }

    p0, p1 = _aggregate(early), _aggregate(late)
    bridge = gmv_bridge(p0, p1)
    bridge_rows = _bridge_rows(bridge)
    factor_zh = bridge.get("dominant_factor_zh")

    caveats = [
        "GMV = 访客数 × 支付转化率 × 客单价 的 LMDI 确定性分解，三项贡献之和≈ΔGMV，非因果。",
        f"前后各取半程聚合：前段 {dated[0][0]}–{dated[mid - 1][0]}，后段 {dated[mid][0]}–{dated[-1][0]}。",
    ]
    if bridge.get("partial"):
        caveats.append("部分因子缺失或非正（如某段访客/买家为零），分解降级，未拆部分计入残差。")

    sample_size = int(p0["buyers"] + p1["buyers"])
    finding = Finding(
        title="增长归因（GMV 桥）",
        conclusion=_bridge_conclusion(bridge, p0, p1),
        evidence_strength=score_evidence(sample_size, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sample_size),
        key_numbers={
            "delta_gmv": bridge.get("delta_gmv"),
            "dominant_factor": bridge.get("dominant_factor"),
            "dominant_factor_zh": factor_zh,
            "contrib_traffic": bridge.get("contrib_traffic"),
            "contrib_conversion": bridge.get("contrib_conversion"),
            "contrib_aov": bridge.get("contrib_aov"),
            "residual": bridge.get("residual"),
            "partial": bridge.get("partial"),
        },
        caveats=caveats,
        recommended_action=_FACTOR_LEVER.get(bridge.get("dominant_factor")),
        evidence_reason="用 LMDI 把 ΔGMV 完全可加地拆到流量/转化/客单三因子，确定性分解、观察性。",
        confounders=_BRIDGE_CONFOUNDERS,
    )
    return finding, {"gmv_bridge": bridge_rows}


def _bridge_rows(bridge: dict) -> list[dict]:
    delta = bridge.get("delta_gmv")
    out: list[dict] = []
    for factor, zh in (("traffic", "流量"), ("conversion", "转化"), ("aov", "客单价")):
        contrib = bridge.get(f"contrib_{factor}")
        out.append(
            {
                "factor": factor,
                "factor_zh": zh,
                "contribution": contrib,
                "share": (contrib / delta) if (contrib is not None and delta) else None,
                "is_dominant": factor == bridge.get("dominant_factor"),
            }
        )
    return out


def _bridge_conclusion(bridge: dict, p0: dict, p1: dict) -> str:
    delta = bridge.get("delta_gmv")
    if delta is None:
        return "增长归因数据不足，无法分解 ΔGMV。"
    move = "增长" if delta > 0 else ("下滑" if delta < 0 else "持平")
    head = (
        f"GMV 从 {money(p0['gmv'])} 元{move}至 {money(p1['gmv'])} 元"
        f"（Δ {money(delta)} 元）"
    )
    zh = bridge.get("dominant_factor_zh")
    if zh is None:
        return head + "，各因子贡献相近或数据不足以定位主因。"
    contrib = bridge.get(f"contrib_{bridge['dominant_factor']}")
    # When the biggest-magnitude factor moves *against* the net change, it was
    # offset by the others — calling it the "driver" would misread the sign.
    if contrib is not None and delta != 0 and (contrib > 0) != (delta > 0):
        return head + (
            f"，其中{zh}变动最大（贡献 {money(contrib)} 元，方向与净变化相反，"
            "被其他因子抵消）。"
        )
    return head + f"，主要由{zh}拉动（贡献 {money(contrib)} 元）。"


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
            lift, mde, mde_caveat = _comparison_extras(
                _num(a["paid_buyers"]), _num(a["click_users"]),
                _num(b["paid_buyers"]), _num(b["click_users"]), channel_test,
            )
            key_numbers["channel_rel_lift"] = lift
            key_numbers["channel_mde"] = mde
            parts.append(
                f"{a['channel']} 与 {b['channel']} 支付转化率相差 {pp(diff)}（{verdict}）"
            )
            caveats.append("渠道显著性用两样本比例检验，并结合效应量（差值）判断。")
            if mde_caveat:
                caveats.append(mde_caveat)
        else:
            key_numbers["channel_diff"] = None
            caveats.append("traffic_source 缺 paid_buyers 或渠道不足两组，仅报点击份额。")

    finding = Finding(
        title="载体与渠道结构",
        conclusion="；".join(parts) + "。" if parts else "结构数据不足。",
        evidence_strength=score_evidence(
            sample_size, has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(sample_size),
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
        lift, mde, mde_caveat = _comparison_extras(
            _num(a["payers"]), _num(a["visitors"]),
            _num(b["payers"]), _num(b["visitors"]), aud_test,
        )
        key_numbers["audience_rel_lift"] = lift
        key_numbers["audience_mde"] = mde
        caveats.append("客群转化差异用两样本比例检验，并结合效应量判断。")
        if mde_caveat:
            caveats.append(mde_caveat)

    sample_size = int(visitors) if visitors else len(rows)
    finding = Finding(
        title="店铺页转化漏斗诊断",
        conclusion=_funnel_conclusion(weakest, stage_rates),
        evidence_strength=score_evidence(
            sample_size, has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(sample_size),
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


def _comparison_extras(
    k1: float, n1: float, k2: float, n2: float, test: dict
) -> tuple[float | None, float | None, str | None]:
    """Relative lift + minimum detectable effect for a two-proportion comparison.

    The raw diff alone hides scale and cannot tell "truly no gap" from "sample too
    small". Returns (relative_lift, mde, caveat) where the caveat fires only when
    the test is non-significant and the MDE is known — so a null result is read as
    under-powered, not as proven equality.
    """
    lift = relative_lift(k1, n1, k2, n2).get("lift")
    p_base = (k2 / n2) if n2 else None
    mde = min_detectable_effect(n1, n2, p_base) if p_base is not None else None
    caveat = None
    if not _sig_gated(test, test.get("diff")) and mde is not None:
        caveat = (
            f"当前样本量下最小可测差约 {round(mde * 100, 1)}pp，"
            "未达显著更可能是样本不足而非确无差异。"
        )
    return lift, mde, caveat


def _avg_rate(rows: list[dict], col: str) -> float | None:
    vals = [bounded_rate(r.get(col)) for r in rows]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None


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
