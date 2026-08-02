from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    min_n_guard,
    rate_band,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.analytics.trends import mom_change, trend_summary
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence, score_reliability

TASK_ID = "refund_structure_diagnosis"
TITLE = "退款结构诊断"

_LAYER_COLUMNS = {
    "pre_ship": "pre_ship_refund_amount",
    "post_ship": "post_ship_refund_amount",
    "return": "return_refund_amount",
}
_LAYER_ORDER_COLUMNS = {
    "pre_ship": "pre_ship_refund_orders",
    "post_ship": "post_ship_refund_orders",
    "shipped_refundonly": "shipped_refundonly_orders",
    "return": "return_refund_orders",
}
_LAYER_RATE_COLUMNS = {
    "pre_ship": "pre_ship_refund_rate_pay",
    "post_ship": "post_ship_refund_rate_pay",
    "return": "return_refund_rate_pay",
}
_SHIP_STAGE_LAYERS = ("pre_ship", "post_ship")
_LAYER_LEVERS = {
    "pre_ship": "发货前退款最高：退款主要卡在发货前。这周先翻发货前退款的订单备注，分清是催不发货、缺货还是价格波动；对上号的先补下单后拦截话术，再理顺库存与发货时效，价格波动就提前把预期说清。",
    "post_ship": "发货后退款最高：退款主要出在发货之后。这周先抽发货后退款的订单问客户是破损还是嫌慢，优先排查物流破损与时效；同时把客服响应提上来，发货后主动推签收提醒。",
    "return": "退货退款最高：钱主要退在退货上。这周先拿退货最多的商品，对着实物逐条核查商品质量、尺寸色差、详情页描述相符度，陶瓷重点盯开裂、色差、规格一致性，哪条对不上先改哪条。",
}


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "refund_overview"):
            return _missing_result("缺少 refund_overview 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}
        cols = _table_columns(con, "refund_overview")
        all_rows = _fetch_all(con, "refund_overview")
        tables["refund_overview_by_period_account_carrier"] = [dict(row) for row in all_rows]
        rows = _single_period_rows(all_rows, cols, limitations)

        layer_finding, layer_rows = _layer_finding(con, limitations, rows)
        findings.append(layer_finding)
        tables["refund_layer_breakdown"] = layer_rows

        if rows is not None:
            carrier_finding, carrier_rows = _carrier_finding(con, limitations, rows)
            if carrier_finding is not None:
                findings.append(carrier_finding)
                tables["carrier_refund_comparison"] = carrier_rows

        trend_finding, trend_rows = _trend_finding(con, limitations)
        if trend_finding is not None:
            findings.append(trend_finding)
            tables["refund_trend"] = trend_rows

        note_finding, note_rows = _note_finding(con, limitations)
        if note_finding is not None:
            findings.append(note_finding)
            tables["high_refund_notes"] = note_rows

        product_finding, product_rows = _product_finding(con, limitations)
        if product_finding is not None:
            findings.append(product_finding)
            tables["product_refund_concentration"] = product_rows

        reason_finding, reason_rows = _reason_finding(con, limitations)
        if reason_finding is not None:
            findings.append(reason_finding)
            tables["refund_reason_breakdown"] = reason_rows
    finally:
        con.close()
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _reason_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "refund_reasons"):
        limitations.append("缺少 refund_reasons 手工录入表，跳过退款原因结构。")
        return None, []
    cols = _table_columns(con, "refund_reasons")
    if "refund_reason" not in cols:
        limitations.append("refund_reasons 缺少 refund_reason，跳过退款原因结构。")
        return None, []
    groups: dict[str, dict[str, float | None]] = {}
    for row in _fetch_all(con, "refund_reasons"):
        reason = str(row.get("refund_reason") or "未分类")
        group = groups.setdefault(reason, {"refund_amount": None, "refund_orders": None})
        for metric in ("refund_amount", "refund_orders"):
            if metric not in cols or row.get(metric) is None:
                continue
            value = _num(row.get(metric))
            group[metric] = (group[metric] or 0.0) + value
    if not groups:
        limitations.append("refund_reasons 没有可用原因记录，跳过退款原因结构。")
        return None, []
    total_amount = sum(group["refund_amount"] or 0.0 for group in groups.values())
    total_orders = sum(group["refund_orders"] or 0.0 for group in groups.values())
    rows = [
        {
            "refund_reason": reason,
            "refund_amount": group["refund_amount"],
            "refund_orders": group["refund_orders"],
            "amount_share": (
                group["refund_amount"] / total_amount
                if total_amount and group["refund_amount"] is not None
                else None
            ),
            "order_share": (
                group["refund_orders"] / total_orders
                if total_orders and group["refund_orders"] is not None
                else None
            ),
        }
        for reason, group in groups.items()
    ]
    rows.sort(
        key=lambda row: (
            row["refund_amount"] is not None,
            row["refund_amount"] or 0,
            row["refund_orders"] or 0,
        ),
        reverse=True,
    )
    top = rows[0]
    sample_size = int(total_orders) if total_orders else len(rows)
    return (
        Finding(
            title="退款原因结构",
            conclusion=(
                f"已整理 {qty(len(rows))} 类退款原因；首要原因为「{top['refund_reason']}」，"
                f"涉及退款 {money(top['refund_amount'])}、{qty(top['refund_orders'])} 单。"
            ),
            evidence_strength=score_evidence(sample_size, has_controls=False, confounder_count=2),
            descriptive_reliability=score_reliability(sample_size),
            key_numbers={
                "reason_count": len(rows),
                "top_reason": top["refund_reason"],
                "total_refund_amount": total_amount if "refund_amount" in cols else None,
                "total_refund_orders": total_orders if "refund_orders" in cols else None,
            },
            caveats=[
                "退款原因来自手工录入或 OCR，可能存在漏记、归类误差和多原因合并。",
                "原因金额/订单只在本表内部计算占比，不与其他统计周期的退款快照相加。",
                M.causal_disclaimer("商品销量结构和售后记录完整度不同"),
            ],
            evidence_reason="按退款原因汇总手工录入的金额和订单，两种占比分别计算。",
            confounders=["原因记录完整度", "商品销量结构"],
            recommended_action="先抽检首要原因对应订单与商品，再决定修改详情、包装、物流或客服流程。",
        ),
        rows,
    )


def _layer_finding(
    con, limitations: list[str], rows: list[dict] | None = None
) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "refund_overview")
    if rows is None:
        return _multi_period_gap_finding(), []
    present = {name: col for name, col in _LAYER_COLUMNS.items() if col in cols}
    if "shipped_refundonly_amount" in cols:
        present["shipped_refundonly"] = "shipped_refundonly_amount"
    total = sum(_num(r.get("refund_amount_pay")) for r in rows)
    amounts = {layer: sum(_num(r.get(col)) for r in rows) for layer, col in present.items()}
    # pre_ship + post_ship partition the ship-stage axis (they sum to 100% of
    # refunds); 退货退款 is a *return-type* subset of post-ship, on a different
    # axis. Sharing one denominator would make the column sum ~127% and imply
    # additivity, so each axis gets its own denominator.
    ship_stage_total = sum(amt for layer, amt in amounts.items() if layer in _SHIP_STAGE_LAYERS)
    layer_rows: list[dict] = []
    for layer in present:
        amount = amounts[layer]
        if layer in _SHIP_STAGE_LAYERS:
            axis, denom = "ship_stage", ship_stage_total
        else:
            axis, denom = "return_type", total
        layer_rows.append(
            row := {
                "layer": layer,
                "axis": axis,
                "refund_amount": amount,
                "share": amount / denom if denom else None,
            }
        )
        order_col = _LAYER_ORDER_COLUMNS.get(layer)
        rate_col = _LAYER_RATE_COLUMNS.get(layer)
        if order_col in cols:
            row["refund_orders"] = sum(_num(r.get(order_col)) for r in rows)
        if rate_col in cols:
            row["refund_rate"] = _aggregate_rate(rows, order_col, rate_col)
    for missing in _LAYER_COLUMNS.keys() - present.keys():
        limitations.append(f"refund_overview 缺少 {_LAYER_COLUMNS[missing]}，跳过 {missing} 层。")

    # Dominant layer is judged within the ship-stage partition only — 退货退款 lives
    # on a different axis and cannot be compared share-for-share against it.
    ship_rows = [r for r in layer_rows if r["axis"] == "ship_stage"]
    dominant = max(ship_rows, key=lambda r: r["refund_amount"], default=None)
    # overall refund rate + Wilson CI via reverse-derived paid-order base
    k = sum(_num(r.get("refund_orders_pay")) for r in rows)
    n = sum(
        _num(r.get("refund_orders_pay")) / _num(r.get("refund_rate_pay"))
        for r in rows
        if _num(r.get("refund_rate_pay")) > 0
    )
    overall_rate = k / n if n else None
    lo, hi = wilson_interval(k, n) if min_n_guard(n) else (None, None)

    dominant_layer = dominant["layer"] if dominant else None
    conclusion = (
        f"总退款 {money(total)} 元。按发货阶段划分（发货前+发货后=100%），占比最高的是 "
        f"{_layer_zh(dominant_layer)}（{round((dominant['share'] or 0) * 100)}%）。"
        if dominant
        else "发货阶段退款金额列缺失，无法拆解。"
    )
    caveats = [
        M.causal_disclaimer("促销节奏、季节性和品类结构不同"),
        "本节为退款金额份额口径。退款率口径见退款根因诊断，分渠道退款率见渠道结构与健康诊断，三者非重复。",
    ]
    return_row = next((r for r in layer_rows if r["axis"] == "return_type"), None)
    if return_row is not None:
        caveats.append(
            f"退货退款本身就算在发货后退款里（占总退款额 "
            f"{round((return_row['share'] or 0) * 100)}%），它和发货前、发货后不是同一套分法，占比不能直接相加。"
        )
    if lo is not None:
        caveats.append(f"整体退款率 {rate_band(lo, hi)}（大致统计了 {qty(n)} 单）。")
    finding = Finding(
        title="退款主漏点层级",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(n), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(n), lo, hi),
        key_numbers={
            "dominant_layer": dominant_layer,
            "dominant_share": dominant["share"] if dominant else None,
            "overall_refund_rate": overall_rate,
            "ci_low": lo,
            "ci_high": hi,
            "total_refund_amount": total,
            "total_refund_users": (
                sum(_num(r.get("refund_users")) for r in rows) if "refund_users" in cols else None
            ),
        },
        caveats=caveats,
        recommended_action=_LAYER_LEVERS.get(dominant_layer) if dominant_layer else None,
        evidence_reason=M.methodology_note(
            "退款率样本量以退款订单/退款率反推支付订单基数估计；层级份额基于聚合快照口径。",
            M.METHOD_OBSERVATIONAL,
        ),
        confounders=["促销节奏", "季节性", "品类结构"],
    )
    return finding, layer_rows


def _carrier_finding(
    con, limitations: list[str], rows: list[dict] | None = None
) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "refund_overview")
    if "carrier" not in cols:
        limitations.append("refund_overview 缺少 carrier 列，跳过载体对比。")
        return None, []
    if rows is None:
        return None, []
    grouped: dict[object, dict] = {}
    for r in rows:
        rate = _num(r.get("refund_rate_pay"))
        orders = _num(r.get("refund_orders_pay"))
        group = grouped.setdefault(
            r.get("carrier"),
            {
                "refund_orders": 0.0,
                "refund_orders_all": 0.0,
                "n": 0.0,
                "refund_amount": 0.0,
                "refund_users": 0.0,
                "rate_coverage_rows": 0,
                "missing_rate_rows": 0,
            },
        )
        group["refund_orders_all"] += orders
        if (
            r.get("refund_orders_pay") is not None
            and r.get("refund_rate_pay") is not None
            and rate > 0
        ):
            group["refund_orders"] += orders
            group["n"] += orders / rate
            group["rate_coverage_rows"] += 1
        else:
            group["missing_rate_rows"] += 1
        if "refund_amount_pay" in cols:
            group["refund_amount"] += _num(r.get("refund_amount_pay"))
        if "refund_users" in cols:
            group["refund_users"] += _num(r.get("refund_users"))
    by_carrier = []
    for carrier, group in grouped.items():
        by_carrier.append(
            {
                "carrier": carrier,
                "refund_rate": (group["refund_orders"] / group["n"] if group["n"] else None),
                "refund_orders": group["refund_orders"],
                "refund_orders_all": group["refund_orders_all"],
                "n": group["n"],
                "refund_amount": group["refund_amount"] if "refund_amount_pay" in cols else None,
                "refund_users": group["refund_users"] if "refund_users" in cols else None,
                "rate_coverage_rows": group["rate_coverage_rows"],
                "missing_rate_rows": group["missing_rate_rows"],
            }
        )
    if len({c["carrier"] for c in by_carrier}) < 2:
        limitations.append("refund_overview 只有单一载体，跳过载体对比。")
        return None, []
    valid = [row for row in by_carrier if row["refund_rate"] is not None]
    if len(valid) < 2:
        limitations.append("refund_overview 载体退款率有效组不足两组，跳过载体对比。")
        return None, []
    top2 = sorted(valid, key=lambda c: c["refund_rate"], reverse=True)[:2]
    a, b = top2[0], top2[1]
    test = two_proportion(a["refund_orders"], a["n"], b["refund_orders"], b["n"])
    sig = "显著" if test["significant"] else "不显著"
    conclusion = (
        f"{a['carrier']} 退款率（{round(a['refund_rate'] * 100)}%）高于 "
        f"{b['carrier']}（{round(b['refund_rate'] * 100)}%），差异{sig}。"
    )
    finding = Finding(
        title="载体退款率对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(a["n"] + b["n"]), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(int(a["n"] + b["n"])),
        key_numbers={
            "carrier_high": a["carrier"],
            "diff": test["diff"],
            "significant": test["significant"],
            "ci_overlap": test["ci_overlap"],
        },
        caveats=[
            M.causal_disclaimer("载体之间流量结构和客群不同"),
        ],
        evidence_reason=M.methodology_note(
            "载体间退款率差异样本量以退款订单/退款率反推。",
            M.METHOD_PROPORTION_TEST,
            M.METHOD_WILSON,
        ),
        confounders=["载体流量结构", "客群差异"],
    )
    return finding, by_carrier


def _single_period_rows(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> list[dict] | None:
    if "stat_period" not in cols:
        return rows
    periods = {row.get("stat_period") for row in rows if row.get("stat_period") is not None}
    if len(periods) <= 1:
        return rows
    limitations.append("refund_overview 含多个统计周期，可能重叠，禁止跨周期叠加。")
    return None


def _aggregate_rate(rows: list[dict], order_col: str | None, rate_col: str) -> float | None:
    if order_col is not None:
        paired = [
            row
            for row in rows
            if row.get(order_col) is not None
            and row.get(rate_col) is not None
            and _num(row.get(rate_col)) > 0
        ]
        orders = sum(_num(row.get(order_col)) for row in paired)
        base = sum(_num(row.get(order_col)) / _num(row.get(rate_col)) for row in paired)
        if base > 0:
            return orders / base
    rates = [_num(row.get(rate_col)) for row in rows if row.get(rate_col) is not None]
    return sum(rates) / len(rates) if rates else None


def _multi_period_gap_finding() -> Finding:
    return Finding(
        title="退款主漏点层级",
        conclusion="退款概览包含多个统计周期，可能相互重叠，未跨周期汇总退款结构。",
        evidence_strength=EvidenceStrength.NOT_JUDGABLE,
        key_numbers={
            "dominant_layer": None,
            "dominant_share": None,
            "overall_refund_rate": None,
            "total_refund_amount": None,
        },
        caveats=["不同统计周期的聚合快照不可直接相加。"],
        evidence_reason="保留原周期/账号/载体粒度，未对可能重叠的周期求和。",
        confounders=["统计周期重叠"],
    )


def _trend_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "business_overview_daily"):
        limitations.append("缺少 business_overview_daily 表，跳过退款率时间趋势。")
        return None, []
    cols = _table_columns(con, "business_overview_daily")
    if "refund_rate_pay" not in cols or "date" not in cols:
        limitations.append("business_overview_daily 缺少 date/refund_rate_pay，跳过趋势。")
        return None, []
    result = con.sql(
        """
        SELECT CAST(date AS VARCHAR) AS period, AVG(CAST(refund_rate_pay AS DOUBLE)) AS rate
        FROM business_overview_daily
        WHERE refund_rate_pay IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """
    )
    base_rows = [{"period": p, "refund_rate": rate} for p, rate in result.fetchall()]
    if len(base_rows) < 2:
        limitations.append("退款率序列不足两期，跳过趋势。")
        return None, []
    series = [(r["period"], r["refund_rate"]) for r in base_rows]
    # Per-period deltas belong in the table columns, not a stringified appendix.
    steps = mom_change(series)
    trend_rows = [
        {
            "period": s["period"],
            "refund_rate": s["value"],
            "refund_rate_delta": s["delta"],
            "pct": s["pct"],
            "direction": s["direction"],
        }
        for s in steps
    ]
    # Direction from OLS slope over all periods — a noisy endpoint can't flip it.
    summary = trend_summary(series)
    direction = summary["direction"]
    finding = Finding(
        title="退款率时间趋势",
        conclusion=(
            f"退款率整体呈{direction}趋势（{qty(len(series))} 期，"
            f"从 {round(series[0][1] * 100)}% 到 {round(series[-1][1] * 100)}%）。"
        ),
        evidence_strength=score_evidence(len(series), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(series)),
        key_numbers={
            "trend_direction": direction,
            "first_rate": series[0][1],
            "last_rate": series[-1][1],
        },
        caveats=[
            M.causal_disclaimer("促销周期和季节性不同"),
            "日度退款率波动较大，一期一期的涨跌见退款趋势表。",
        ],
        evidence_reason=M.methodology_note(
            "逐期退款率走势描述。",
            M.METHOD_TREND_SLOPE,
        ),
        confounders=["促销周期", "季节性"],
        appendix="趋势方向用最小二乘斜率；逐期环比（delta/pct）见 refund_trend 表。",
    )
    return finding, trend_rows


_NOTE_FEATURES = ("composition_type", "scene_hint", "copy_angle")


def _note_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "notes"):
        limitations.append("缺少 notes 表，跳过笔记退款反思。")
        return None, []
    cols = _table_columns(con, "notes")
    if "note_refund_rate_pay" not in cols:
        limitations.append("notes 缺少 note_refund_rate_pay，跳过笔记退款反思。")
        return None, []
    has_features = _table_exists(con, "content_features")
    if has_features:
        rows = con.sql(
            """
            SELECT n.note_id, n.title, n.note_refund_rate_pay AS rate,
                   n.note_paid_orders AS paid,
                   f.composition_type, f.scene_hint, f.copy_angle
            FROM notes n LEFT JOIN content_features f USING (note_id)
            WHERE n.note_refund_rate_pay IS NOT NULL
            """
        ).fetchall()
        columns = [
            "note_id",
            "title",
            "rate",
            "paid",
            "composition_type",
            "scene_hint",
            "copy_angle",
        ]
    else:
        rows = con.sql(
            """
            SELECT note_id, title, note_refund_rate_pay AS rate, note_paid_orders AS paid
            FROM notes WHERE note_refund_rate_pay IS NOT NULL
            """
        ).fetchall()
        columns = ["note_id", "title", "rate", "paid"]
    records = [dict(zip(columns, r)) for r in rows]

    total_k = sum(_num(r["rate"]) * _num(r["paid"]) for r in records)
    total_n = sum(_num(r["paid"]) for r in records)
    baseline = total_k / total_n if total_n else 0.0

    high: list[dict] = []
    for r in records:
        paid = _num(r["paid"])
        rate = _num(r["rate"])
        k = round(rate * paid)
        lo, _ = wilson_interval(k, paid)
        if min_n_guard(paid) and lo > baseline:
            high.append(
                {
                    "note_id": r["note_id"],
                    "title": r["title"],
                    "note_refund_rate": rate,
                    "n": paid,
                    "composition_type": r.get("composition_type"),
                    "scene_hint": r.get("scene_hint"),
                    "copy_angle": r.get("copy_angle"),
                }
            )

    top_feature = _top_feature(high, _NOTE_FEATURES) if has_features else None
    caveats = [
        M.causal_disclaimer("选品差异、定价和客群不同") + "高退款笔记的共有特征仅供假设生成。"
    ]
    if not has_features:
        caveats.append("缺少 content_features，仅列高退款笔记，无法归因特征。")
    conclusion = (
        f"有 {qty(len(high))} 篇笔记退款率显著高于平均水平（{round(baseline * 100)}%）。"
        + (f" 高退款笔记更多集中在 {top_feature}。" if top_feature else "")
    )
    finding = Finding(
        title="笔记退款反思",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_n), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_n)),
        key_numbers={
            "high_refund_note_count": len(high),
            "baseline_rate": baseline,
            "top_feature": top_feature,
        },
        caveats=caveats,
        evidence_reason="以 Wilson 下界高于加权基线判定高退款笔记，避免小样本误报。",
        confounders=["选品差异", "定价", "客群"],
        next_test="先挑出疑似高退款特征，做重拍或 A-B 验证，跑完再复测退款率看有没有降下来。",
    )
    return finding, high


def _top_feature(cohort: list[dict], feature_keys: tuple[str, ...]) -> str | None:
    best: tuple[str, str, int] | None = None
    for key in feature_keys:
        counts: dict[str, int] = {}
        for r in cohort:
            value = r.get(key)
            if value is not None:
                counts[value] = counts.get(value, 0) + 1
        for value, count in counts.items():
            if best is None or count > best[2]:
                best = (key, value, count)
    return f"{best[0]}={best[1]}" if best else None


_PRODUCT_FEATURES = ("vessel_type", "series", "category", "price_band")


def _product_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "sku_performance"):
        limitations.append("缺少 sku_performance 表，跳过产品退款反思。")
        return None, []
    cols = _table_columns(con, "sku_performance")
    if "refund_rate_pay" not in cols or "product_id" not in cols:
        limitations.append("sku_performance 缺少 product_id/refund_rate_pay，跳过产品退款反思。")
        return None, []
    has_orders = "refund_orders_pay" in cols
    has_products = _table_exists(con, "products")
    orders_expr = "SUM(CAST(refund_orders_pay AS DOUBLE))" if has_orders else "NULL"
    gmv_expr = "SUM(CAST(gmv AS DOUBLE))" if "gmv" in cols else "NULL"
    net_expr = "SUM(CAST(net_gmv_pay AS DOUBLE))" if "net_gmv_pay" in cols else "NULL"
    agg = con.sql(
        f"""
        SELECT product_id, ANY_VALUE(product_name) AS product_name,
               {gmv_expr} AS gmv, {net_expr} AS net_gmv,
               AVG(CAST(refund_rate_pay AS DOUBLE)) AS rate,
               {orders_expr} AS refund_orders
        FROM sku_performance GROUP BY product_id
        """
    ).fetchall()
    columns = ["product_id", "product_name", "gmv", "net_gmv", "rate", "refund_orders"]
    records = [dict(zip(columns, r)) for r in agg]

    attrs: dict[str, dict] = {}
    if has_products:
        pcols = _table_columns(con, "products")
        sel = ", ".join(f for f in _PRODUCT_FEATURES if f in pcols)
        if sel:
            for r in con.sql(f"SELECT product_id, {sel} FROM products").fetchall():
                keys = ["product_id"] + [f for f in _PRODUCT_FEATURES if f in pcols]
                attrs[r[0]] = dict(zip(keys, r))

    total_refund = sum(_num(r["gmv"]) - _num(r["net_gmv"]) for r in records)
    total_k = (
        sum(_num(r["rate"]) * _num(r["refund_orders"]) for r in records) if has_orders else 0.0
    )
    total_n = sum(_num(r["refund_orders"]) for r in records) if has_orders else 0.0
    baseline = (
        (total_k / total_n)
        if total_n
        else (sum(_num(r["rate"]) for r in records) / len(records) if records else 0.0)
    )

    product_rows: list[dict] = []
    high: list[dict] = []
    for r in records:
        refund_amount = _num(r["gmv"]) - _num(r["net_gmv"])
        rate = _num(r["rate"])
        n = _num(r["refund_orders"])
        attr = attrs.get(r["product_id"], {})
        row = {
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "refund_amount": refund_amount,
            "amount_share": refund_amount / total_refund if total_refund else None,
            "refund_rate": rate,
            "n": n if has_orders else None,
            "vessel_type": attr.get("vessel_type"),
            "series": attr.get("series"),
            "category": attr.get("category"),
            "price_band": attr.get("price_band"),
        }
        product_rows.append(row)
        if has_orders and n > 0:
            lo, _ = wilson_interval(round(rate * n), n)
            flagged = min_n_guard(n) and lo > baseline
        else:
            flagged = rate > baseline
        if flagged:
            high.append(row)

    product_rows.sort(key=lambda r: r["refund_amount"], reverse=True)
    top_feature = _top_feature(high, _PRODUCT_FEATURES) if has_products else None
    top_share = sum(r["amount_share"] or 0 for r in product_rows[:3])
    caveats = [
        M.causal_disclaimer("品类结构、定价带和上新周期不同") + "高退款产品的共有特征仅供假设生成。"
    ]
    if not has_products:
        caveats.append("缺少 products，仅列高退款产品，无法归因特征。")
    if not has_orders:
        caveats.append("缺少 refund_orders_pay，产品退款率未做订单量 Wilson 守卫。")
    conclusion = f"高退款产品 {qty(len(high))} 个，退款金额前三占 {round(top_share * 100)}%。" + (
        f" 高退款集中在 {top_feature}。" if top_feature else ""
    )
    finding = Finding(
        title="产品退款反思",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_n) if has_orders else len(records),
            has_controls=False,
            confounder_count=1,
        ),
        descriptive_reliability=score_reliability(int(total_n) if has_orders else len(records)),
        key_numbers={
            "high_refund_product_count": len(high),
            "top_products_amount_share": top_share,
            "baseline_rate": baseline,
            "top_feature": top_feature,
        },
        caveats=caveats,
        recommended_action="先从退款金额最高的高退款产品下手：这周安排质量抽检，同时把详情页尺寸与色差描述改准；抽检差的再评估下架或换供应。",
        evidence_reason="产品退款金额=支付-退款后支付；高退款以退款率对比基线（有订单量时 Wilson 守卫）。",
        confounders=["品类结构", "定价带", "上新周期"],
        next_test="挑出可疑的器型/系列做质量抽检、或修订详情页描述，之后再复测一次退款率。",
    )
    return finding, product_rows


def _layer_zh(layer: str | None) -> str:
    return {"pre_ship": "发货前退款", "post_ship": "发货后退款", "return": "退货退款"}.get(
        layer, "未知层级"
    )


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
                title="退款结构不可诊断",
                conclusion="需要导出 refund_overview（退款概览）数据后才能诊断退款结构。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["退款概览缺失应视为导入缺口。"],
                recommended_action="导出退款概览（含发货前/发货后/退货退款金额）后重新构建。",
            )
        ],
        tables={"refund_layer_breakdown": []},
        limitations=[reason],
    )
