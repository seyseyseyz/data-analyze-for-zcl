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
_SHIP_STAGE_LAYERS = ("pre_ship", "post_ship")
_LAYER_LEVERS = {
    "pre_ship": "发货前退款最高：优化下单后拦截话术、库存与发货时效、价格波动预期管理。",
    "post_ship": "发货后退款最高：排查物流破损与时效、加强客服响应与签收提醒。",
    "return": "退货退款最高：核查商品质量、尺寸色差、详情页描述相符度（陶瓷重点：开裂、色差、规格一致性）。",
}


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "refund_overview"):
            return _missing_result("缺少 refund_overview 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        layer_finding, layer_rows = _layer_finding(con, limitations)
        findings.append(layer_finding)
        tables["refund_layer_breakdown"] = layer_rows

        carrier_finding, carrier_rows = _carrier_finding(con, limitations)
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
    finally:
        con.close()
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _layer_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "refund_overview")
    rows = _fetch_all(con, "refund_overview")
    present = {name: col for name, col in _LAYER_COLUMNS.items() if col in cols}
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
            {
                "layer": layer,
                "axis": axis,
                "refund_amount": amount,
                "share": amount / denom if denom else None,
            }
        )
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
        f"总退款 {money(total)} 元，按发货阶段划分（发货前+发货后=100%）占比最高的是 "
        f"{_layer_zh(dominant_layer)}（{round((dominant['share'] or 0) * 100)}%）。"
        if dominant
        else "发货阶段退款金额列缺失，无法拆解。"
    )
    caveats = [
        M.causal_disclaimer("促销节奏、季节性和品类结构不同"),
        "本节为退款金额份额口径；退款率口径见退款根因诊断，分渠道退款率见渠道结构与健康诊断，三者非重复。",
    ]
    return_row = next((r for r in layer_rows if r["axis"] == "return_type"), None)
    if return_row is not None:
        caveats.append(
            f"退货退款为发货后退款的子集（占总退款额 "
            f"{round((return_row['share'] or 0) * 100)}%），与发货前/后不在同一划分轴，份额不相加。"
        )
    if lo is not None:
        caveats.append(f"整体退款率 {rate_band(lo, hi)}（样本 n≈{qty(n)}）。")
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


def _carrier_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "refund_overview")
    if "carrier" not in cols:
        limitations.append("refund_overview 缺少 carrier 列，跳过载体对比。")
        return None, []
    rows = _fetch_all(con, "refund_overview")
    by_carrier: list[dict] = []
    for r in rows:
        rate = _num(r.get("refund_rate_pay"))
        orders = _num(r.get("refund_orders_pay"))
        n = round(orders / rate) if rate > 0 else 0
        by_carrier.append(
            {
                "carrier": r.get("carrier"),
                "refund_rate": rate,
                "refund_orders": orders,
                "n": n,
            }
        )
    if len({c["carrier"] for c in by_carrier}) < 2:
        limitations.append("refund_overview 只有单一载体，跳过载体对比。")
        return None, []
    top2 = sorted(by_carrier, key=lambda c: c["refund_rate"], reverse=True)[:2]
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
        {"period": s["period"], "refund_rate": s["value"], "refund_rate_delta": s["delta"],
         "pct": s["pct"], "direction": s["direction"]}
        for s in steps
    ]
    # Direction from OLS slope over all periods — a noisy endpoint can't flip it.
    summary = trend_summary(series)
    direction = summary["direction"]
    finding = Finding(
        title="退款率时间趋势",
        conclusion=(
            f"退款率整体呈{direction}趋势（{qty(len(series))} 期，"
            f"起 {round(series[0][1] * 100)}% 止 {round(series[-1][1] * 100)}%）。"
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
            "日度退款率波动较大，逐期环比见退款趋势表。",
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
        columns = ["note_id", "title", "rate", "paid",
                   "composition_type", "scene_hint", "copy_angle"]
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
        M.causal_disclaimer("选品差异、定价和客群不同")
        + "高退款笔记的共有特征仅供假设生成。"
    ]
    if not has_features:
        caveats.append("缺少 content_features，仅列高退款笔记，无法归因特征。")
    conclusion = (
        f"共 {qty(len(high))} 篇笔记退款率显著高于基线（{round(baseline * 100)}%）。"
        + (f" 高退款笔记更多集中在 {top_feature}。" if top_feature else "")
    )
    finding = Finding(
        title="笔记退款反思",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_n), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(int(total_n)),
        key_numbers={
            "high_refund_note_count": len(high),
            "baseline_rate": baseline,
            "top_feature": top_feature,
        },
        caveats=caveats,
        evidence_reason="以 Wilson 下界高于加权基线判定高退款笔记，避免小样本误报。",
        confounders=["选品差异", "定价", "客群"],
        next_test="对疑似高退款特征做重拍/A-B 验证后复测退款率。",
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
        sum(_num(r["rate"]) * _num(r["refund_orders"]) for r in records)
        if has_orders
        else 0.0
    )
    total_n = sum(_num(r["refund_orders"]) for r in records) if has_orders else 0.0
    baseline = (total_k / total_n) if total_n else (
        sum(_num(r["rate"]) for r in records) / len(records) if records else 0.0
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
        M.causal_disclaimer("品类结构、定价带和上新周期不同")
        + "高退款产品的共有特征仅供假设生成。"
    ]
    if not has_products:
        caveats.append("缺少 products，仅列高退款产品，无法归因特征。")
    if not has_orders:
        caveats.append("缺少 refund_orders_pay，产品退款率未做订单量 Wilson 守卫。")
    conclusion = (
        f"高退款产品 {qty(len(high))} 个，退款金额前三占 {round(top_share * 100)}%。"
        + (f" 高退款集中在 {top_feature}。" if top_feature else "")
    )
    finding = Finding(
        title="产品退款反思",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_n) if has_orders else len(records),
            has_controls=False,
            confounder_count=1,
        ),
        descriptive_reliability=score_reliability(
            int(total_n) if has_orders else len(records)
        ),
        key_numbers={
            "high_refund_product_count": len(high),
            "top_products_amount_share": top_share,
            "baseline_rate": baseline,
            "top_feature": top_feature,
        },
        caveats=caveats,
        recommended_action="对高退款产品优先做质量抽检 / 详情页尺寸与色差描述修订，评估下架或换供应。",
        evidence_reason="产品退款金额=支付-退款后支付；高退款以退款率对比基线（有订单量时 Wilson 守卫）。",
        confounders=["品类结构", "定价带", "上新周期"],
        next_test="对疑似器型/系列做质量抽检或描述修订后复测退款率。",
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
