"""SKU 结构与退款诊断 — sku_structure_diagnosis.

Same module contract as ``audience_structure``/``refund_diagnosis``: never-raise
degradation, ``_table_exists``/``_table_columns``/``_fetch_all``/``_num`` helpers,
per-Finding confounders + observational caveats. Observational only — no causal
attribution (SKU-level GMV/退款/转化 mix reflects品类、价格带与流量结构等多重因素叠加).
"""
import math
from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.concentration import gini, hhi
from xhs_ceramics_analytics.analytics.confidence import bounded_rate
from xhs_ceramics_analytics.analytics.distribution import band_of, histogram, quantile_edges
from xhs_ceramics_analytics.analytics.multiplicity import (
    benjamini_hochberg,
    expected_false_positives,
    one_sided_binomial_p,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import (
    EvidenceStrength,
    score_evidence,
    score_reliability,
)

TASK_ID = "sku_structure_diagnosis"
TITLE = "SKU 结构与退款诊断"

_MIN_ORDERS_GUARD = 10

_LEVER_PARETO = "GMV 高度集中 → 头部 SKU 保供与加投，腰部测新。"
_LEVER_REFUND = "高退款 SKU → 复核详情页/尺寸描述与发货时效，针对性优化退货流程。"
_LEVER_CONVERSION = "加购转化偏低或客单价失衡 → 优化详情页转化钩子，高客单 SKU 强化权益，低客单 SKU 测试搭配销售。"

_CONFOUNDERS = ["品类与价格带混合", "流量分配差异", "活动与折扣节奏"]

# Shared price-band vocabulary — the same four labels refund_root_cause uses, so a
# band name means the identical AOV window across both modules (口径 comes from
# analytics.distribution.quantile_edges).
_BAND_LABELS = ["低价位", "中低价位", "中高价位", "高价位"]
_LEVER_PRICE_BAND = (
    "GMV 若集中在某价位带 → 该带做主推与保供；空档价位带测新品补齐，"
    "避免流量与货盘只压在单一价位。"
)
_PRICE_BAND_CONFOUNDERS = ["品类结构差异", "流量分配差异", "活动与折扣节奏"]

# C5 甜点价位带 — 转化 × 退款 的净收益画像。
_LEVER_SWEET_SPOT = (
    "甜点价位带（转化高且退款低）→ 优先补齐该带货盘与主推；"
    "高转化但高退款的价位带先治退款，低转化价位带优化承接或收缩。"
)
_SWEET_SPOT_CONFOUNDERS = ["品类结构差异", "流量分配差异", "活动与折扣节奏", "售后与发货时效"]


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "sku_performance"):
            return _missing_result("缺少 sku_performance 表。")

        cols = _table_columns(con, "sku_performance")
        rows = _fetch_all(con, "sku_performance")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        # Finding 1 is always emitted (documented gap-notice when gmv absent).
        pareto_finding, pareto_rows, category_rows = _pareto_finding(rows, cols, limitations)
        findings.append(pareto_finding)
        tables["sku_gmv_pareto"] = pareto_rows
        if category_rows is not None:
            tables["sku_category_mix"] = category_rows

        refund_finding, refund_rows = _refund_finding(rows, cols, limitations)
        if refund_finding is not None:
            findings.append(refund_finding)
            tables["sku_refund_outliers"] = refund_rows

        conv_finding, conv_rows = _conversion_finding(rows, cols, limitations)
        if conv_finding is not None:
            findings.append(conv_finding)
            tables["sku_conversion_and_aov"] = conv_rows

        band_finding, band_rows = _price_band_distribution_finding(rows, cols, limitations)
        if band_finding is not None:
            findings.append(band_finding)
            tables["sku_price_band_distribution"] = band_rows

        sweet_finding, sweet_rows = _price_sweet_spot_finding(rows, cols, limitations)
        if sweet_finding is not None:
            findings.append(sweet_finding)
            tables["sku_price_sweet_spot"] = sweet_rows

        l2_finding, l2_rows = _category_l2_finding(rows, cols, limitations)
        if l2_finding is not None:
            findings.append(l2_finding)
            tables["sku_category_l2_mix"] = l2_rows
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
# Finding 1 — GMV 集中度与类目结构（帕累托） (always emitted)
# --------------------------------------------------------------------------- #
def _pareto_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding, list[dict], list[dict] | None]:
    if "gmv" not in cols:
        limitations.append("sku_performance 缺少 gmv 列，无法计算 GMV 集中度与类目结构。")
        finding = Finding(
            title="GMV 集中度与类目结构（帕累托）",
            conclusion="sku_performance 缺少 gmv 列，无法计算 GMV 集中度与类目结构，需补充真实 GMV 列。",
            evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            key_numbers={"sku_count": 0, "gmv_total": None},
            caveats=["观察性诊断，非因果；缺少真实 GMV 列。"],
            confounders=list(_CONFOUNDERS),
            evidence_reason="缺少 gmv 列，无法计算 GMV 集中度。",
        )
        return finding, [], None

    has_name = "sku_name" in cols
    valid = [r for r in rows if _num(r.get("gmv")) > 0]
    valid.sort(key=lambda r: _num(r.get("gmv")), reverse=True)
    total_gmv = sum(_num(r.get("gmv")) for r in valid)
    sku_count = len(valid)

    pareto_rows: list[dict] = []
    cum = 0.0
    skus_for_80pct = None
    for idx, r in enumerate(valid):
        gmv = _num(r.get("gmv"))
        cum += gmv
        share = (gmv / total_gmv) if total_gmv else None
        cum_share = (cum / total_gmv) if total_gmv else None
        if skus_for_80pct is None and cum_share is not None and cum_share >= 0.8:
            skus_for_80pct = idx + 1
        if idx < 20:
            pareto_rows.append(
                {
                    "sku_name": r.get("sku_name") if has_name else r.get("sku_id"),
                    "gmv": gmv,
                    "gmv_share": share,
                    "cum_share": cum_share,
                }
            )
    if skus_for_80pct is None and valid:
        skus_for_80pct = len(valid)

    top_decile_n = max(1, math.ceil(sku_count * 0.1)) if sku_count else 0
    top_decile_gmv = sum(_num(r.get("gmv")) for r in valid[:top_decile_n])
    top_decile_gmv_share = (top_decile_gmv / total_gmv) if total_gmv else None

    category_rows: list[dict] | None = None
    top_category = None
    if "category_l1" in cols:
        cat_groups: dict = {}
        for r in valid:
            key = r.get("category_l1")
            cat_groups[key] = cat_groups.get(key, 0.0) + _num(r.get("gmv"))
        category_rows = [
            {
                "category_l1": key,
                "gmv": gmv,
                "gmv_share": (gmv / total_gmv) if total_gmv else None,
            }
            for key, gmv in cat_groups.items()
        ]
        category_rows.sort(key=lambda r: r["gmv"], reverse=True)
        top_category = category_rows[0]["category_l1"] if category_rows else None

    # Single-value concentration alongside the Pareto head-share: one comparable
    # number (Gini/HHI) makes "more concentrated than last period" checkable.
    gmv_values = [_num(r.get("gmv")) for r in valid]
    gmv_gini = gini(gmv_values)
    gmv_hhi = hhi(gmv_values)

    key_numbers: dict[str, object] = {
        "sku_count": sku_count,
        "gmv_total": total_gmv,
        "top_decile_gmv_share": top_decile_gmv_share,
        "skus_for_80pct": skus_for_80pct,
        "gmv_gini": gmv_gini,
        "gmv_hhi": gmv_hhi,
    }
    if top_category is not None:
        key_numbers["top_category"] = top_category

    gini_reason = (
        f"集中度以基尼系数衡量：{round(gmv_gini, 2)}（0=均摊，越高越集中在少数）。"
        if gmv_gini is not None
        else None
    )
    conclusion = (
        f"共 {qty(sku_count)} 个有效 SKU，GMV 合计 {money(total_gmv)}。"
        f"头部 10% SKU 贡献 {round((top_decile_gmv_share or 0) * 100)}% GMV，"
        f"累计 80% GMV 需 {qty(skus_for_80pct)} 个 SKU。"
        + (f" 主力类目为 {top_category}。" if top_category else "")
    )

    finding = Finding(
        title="GMV 集中度与类目结构（帕累托）",
        conclusion=conclusion,
        evidence_strength=score_evidence(sku_count, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sku_count),
        key_numbers=key_numbers,
        caveats=[M.causal_disclaimer("品类结构、价格带和活动节奏不同")],
        # No positive-GMV SKU →集中度不可计算，此时不给出加投动作（避免无数据支撑的建议）。
        recommended_action=_LEVER_PARETO if valid else None,
        evidence_reason=M.methodology_note(
            "GMV 集中度基于真实 gmv 列排序聚合，观察性描述，非因果。",
            gini_reason,
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, pareto_rows, category_rows


# --------------------------------------------------------------------------- #
# Finding 2 — 高退款 SKU 识别 (degrade-gated)
# --------------------------------------------------------------------------- #
def _refund_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if not {"refund_rate_pay", "paid_orders"} <= cols:
        limitations.append("sku_performance 缺少 refund_rate_pay/paid_orders 列，跳过高退款 SKU 识别。")
        return None, []

    has_name = "sku_name" in cols
    has_refund_orders = "refund_orders_pay" in cols
    has_pre = "pre_ship_refund_rate_pay" in cols
    has_post = "post_ship_refund_rate_pay" in cols

    usable = [r for r in rows if _num(r.get("paid_orders")) > 0]
    if not usable:
        limitations.append("sku_performance 无有效支付订单数据，跳过高退款 SKU 识别。")
        return None, []

    total_orders = sum(_num(r.get("paid_orders")) for r in usable)
    if has_refund_orders:
        total_refund_orders = sum(_num(r.get("refund_orders_pay")) for r in usable)
        baseline = (total_refund_orders / total_orders) if total_orders else None
    else:
        weighted_sum = sum(
            (bounded_rate(r.get("refund_rate_pay")) or 0.0) * _num(r.get("paid_orders"))
            for r in usable
        )
        baseline = (weighted_sum / total_orders) if total_orders else None

    outliers: list[dict] = []
    for r in usable:
        rate = bounded_rate(r.get("refund_rate_pay"))
        orders = _num(r.get("paid_orders"))
        if rate is None or baseline is None:
            continue
        if rate > baseline and orders >= _MIN_ORDERS_GUARD:
            refund_orders = (
                _num(r.get("refund_orders_pay")) if has_refund_orders else rate * orders
            )
            row = {
                "sku_name": r.get("sku_name") if has_name else r.get("sku_id"),
                "paid_orders": orders,
                "refund_orders_pay": refund_orders,
                "refund_rate_pay": rate,
            }
            if has_pre:
                row["pre_ship_refund_rate_pay"] = bounded_rate(r.get("pre_ship_refund_rate_pay"))
            if has_post:
                row["post_ship_refund_rate_pay"] = bounded_rate(r.get("post_ship_refund_rate_pay"))
            outliers.append(row)

    # Thousands of SKUs are scanned for "rate > baseline"; without control, many
    # clear the bar by chance. Benjamini-Hochberg over one-sided binomial p-values
    # caps the expected false-discovery rate among the flagged SKUs.
    pvals = [
        one_sided_binomial_p(r["refund_orders_pay"], r["paid_orders"], baseline)
        for r in outliers
    ]
    survived = benjamini_hochberg(pvals, alpha=0.05)
    for r, p, s in zip(outliers, pvals, survived):
        r["p_value"] = p
        r["fdr_significant"] = bool(s)
    fdr_survivors = sum(1 for s in survived if s)
    exp_false_positives = expected_false_positives(len(outliers), 0.05)
    outliers.sort(key=lambda r: r["refund_rate_pay"], reverse=True)

    conclusion = (
        f"整体退款率基线约 {round((baseline or 0) * 100, 1)}%，"
        f"识别出 {qty(len(outliers))} 个高退款 SKU（退款率高于基线且支付订单数 ≥{_MIN_ORDERS_GUARD}），"
        f"其中 {qty(fdr_survivors)} 个在排除统计误报后仍明显偏高。"
    )

    finding = Finding(
        title="高退款 SKU 识别",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(usable), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(usable)),
        key_numbers={
            "baseline_refund_rate": baseline,
            "high_refund_sku_count": len(outliers),
            "fdr_survivors": fdr_survivors,
            "expected_false_positives": exp_false_positives,
        },
        caveats=[
            M.causal_disclaimer("品类、发货时效和售后政策不同"),
            "多重比较用 Benjamini-Hochberg FDR 控制假阳性；缺退款单列时退款单以率×成交单估计。",
        ],
        recommended_action=_LEVER_REFUND,
        evidence_reason=M.methodology_note(
            "退款基线用真实 paid_orders 加权聚合；高退款 SKU 先经基线筛选，"
            "再以单侧二项 p 值 + BH-FDR 控制多重比较假阳性。",
            M.METHOD_FDR,
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, outliers


# --------------------------------------------------------------------------- #
# Finding — 价格带分布（SKU × GMV） (degrade-gated)
# --------------------------------------------------------------------------- #
def _price_band_distribution_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if not {"aov", "gmv"} <= cols:
        limitations.append("sku_performance 缺少 aov/gmv 列，跳过价格带分布。")
        return None, []

    # Same universe + caliber as the refund price-band split: gmv>0 SKUs, AOV
    # quantile edges from analytics.distribution. A band label therefore denotes
    # the identical AOV window in both modules.
    usable = [r for r in rows if _num(r.get("gmv")) > 0 and _num(r.get("aov")) > 0]
    aovs = [_num(r.get("aov")) for r in usable]
    edges = quantile_edges(aovs, 4)
    if not edges:
        limitations.append("gmv>0 且 aov>0 的 SKU 不足 4 个，无法计算价格带分位，跳过价格带分布。")
        return None, []

    aov_max = max(aovs)
    thresholds = list(edges) + [aov_max]
    total_gmv = sum(_num(r.get("gmv")) for r in usable)

    # histogram gives the SKU-count distribution over the shared edges; GMV is a
    # weighted sum per band via the same left-closed band_of, so counts and money
    # never drift onto different band boundaries.
    hist = histogram(aovs, edges)
    band_gmv = {i: 0.0 for i in range(4)}
    for r in usable:
        idx = band_of(_num(r.get("aov")), edges)
        band_gmv[idx] += _num(r.get("gmv"))

    band_rows: list[dict] = []
    for i in range(4):
        count = hist[i]["count"] if i < len(hist) else 0
        gmv = band_gmv[i]
        band_rows.append(
            {
                "band": _BAND_LABELS[i],
                "aov_low": thresholds[i],
                "aov_high": thresholds[i + 1],
                "sku_count": count,
                "sku_share": hist[i]["share"] if i < len(hist) else 0.0,
                "gmv": gmv,
                "gmv_share": (gmv / total_gmv) if total_gmv else None,
            }
        )

    top_band = max(band_rows, key=lambda r: (r["gmv_share"] or 0.0))
    conclusion = (
        f"共 {qty(len(usable))} 个有效 SKU 按客单价高低分成 4 个价位带，"
        f"GMV 最集中于{top_band['band']}"
        f"（占 GMV {round((top_band['gmv_share'] or 0) * 100)}%、"
        f"占 SKU 数 {round((top_band['sku_share'] or 0) * 100)}%）。"
    )

    finding = Finding(
        title="价格带分布（SKU × GMV）",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(usable), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(usable)),
        key_numbers={
            "band_count": len(band_rows),
            "top_gmv_band": top_band["band"],
            "top_gmv_band_share": top_band["gmv_share"],
        },
        caveats=[
            M.causal_disclaimer("品类结构、流量分配和活动节奏不同"),
            "价位带口径与退款根因诊断一致（客单价高低分档），便于跨模块对照。",
        ],
        recommended_action=_LEVER_PRICE_BAND,
        evidence_reason=(
            "价位带由 gmv>0 SKU 的客单价四分位切分（analytics.distribution 共享口径），"
            "SKU 数用 histogram、GMV 用同一 band_of 加权聚合，观察性描述。"
        ),
        confounders=list(_PRICE_BAND_CONFOUNDERS),
    )
    return finding, band_rows


# --------------------------------------------------------------------------- #
# Finding — 价格甜点（价格带 × 转化 × 退款） (degrade-gated)
# --------------------------------------------------------------------------- #
def _price_sweet_spot_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    """价格带 × 加购转化 × 退款 三维联表，标记「转化高且退款低」甜点带.

    复用价格带分布同一套客单价四分位口径 (``quantile_edges``/``band_of``)，把转化
    与退款折叠到同一价位带上：一个价位带只有同时「转化不低于整体、退款不高于整体」才
    记为甜点带。三个维度缺一即降级跳过（never-raise），观察性、非因果。
    """
    needed = {"aov", "add_to_cart_users", "paid_buyers", "refund_rate_pay", "paid_orders"}
    missing = needed - cols
    if missing:
        limitations.append(
            f"sku_performance 缺少 {'/'.join(sorted(missing))}，跳过价格甜点（价格带 × 转化 × 退款）。"
        )
        return None, []

    # Universe = priced SKUs; edges use the same AOV-quartile caliber as the price
    # band distribution so a band label denotes the identical window across findings.
    usable = [r for r in rows if _num(r.get("aov")) > 0]
    aovs = [_num(r.get("aov")) for r in usable]
    edges = quantile_edges(aovs, 4)
    if not edges:
        limitations.append("aov>0 的 SKU 不足 4 个，无法切分价位带，跳过价格甜点。")
        return None, []
    thresholds = list(edges) + [max(aovs)]

    # Per band: fold conversion (cart→pay) and refund (refund orders / paid orders)
    # onto the shared price band. Each dimension aggregates over the SKUs that
    # actually report it, so a SKU missing carts still contributes to refund.
    has_refund_orders = "refund_orders_pay" in cols
    bands: dict[int, dict] = {
        i: {"skus": 0, "cart": 0.0, "pay": 0.0, "orders": 0.0, "refunds": 0.0}
        for i in range(4)
    }
    for r in usable:
        idx = band_of(_num(r.get("aov")), edges)
        if idx is None:
            continue
        b = bands[idx]
        b["skus"] += 1
        b["cart"] += _num(r.get("add_to_cart_users"))
        b["pay"] += _num(r.get("paid_buyers"))
        orders = _num(r.get("paid_orders"))
        b["orders"] += orders
        if has_refund_orders:
            b["refunds"] += _num(r.get("refund_orders_pay"))
        else:
            b["refunds"] += (bounded_rate(r.get("refund_rate_pay")) or 0.0) * orders

    total_cart = sum(b["cart"] for b in bands.values())
    total_pay = sum(b["pay"] for b in bands.values())
    total_orders = sum(b["orders"] for b in bands.values())
    total_refunds = sum(b["refunds"] for b in bands.values())
    overall_conv = (total_pay / total_cart) if total_cart else None
    overall_refund = (total_refunds / total_orders) if total_orders else None
    if overall_conv is None or overall_refund is None:
        limitations.append("价位带缺少有效的加购或成交订单，跳过价格甜点。")
        return None, []

    band_rows: list[dict] = []
    for i in range(4):
        b = bands[i]
        conv = (b["pay"] / b["cart"]) if b["cart"] else None
        refund = (b["refunds"] / b["orders"]) if b["orders"] else None
        # Net margin = conversion minus refund rate; the sweet spot maximizes it
        # among bands that are both above-conversion and below-refund vs overall.
        tradeoff = (conv - refund) if (conv is not None and refund is not None) else None
        is_sweet = bool(
            conv is not None
            and refund is not None
            and conv >= overall_conv
            and refund <= overall_refund
        )
        band_rows.append(
            {
                "band": _BAND_LABELS[i],
                "aov_low": thresholds[i],
                "aov_high": thresholds[i + 1],
                "sku_count": b["skus"],
                "cart_to_pay": bounded_rate(conv) if conv is not None else None,
                "refund_rate_pay": bounded_rate(refund) if refund is not None else None,
                "net_margin": tradeoff,
                "is_sweet_spot": is_sweet,
            }
        )

    qualified = [r for r in band_rows if r["is_sweet_spot"] and r["net_margin"] is not None]
    sweet = max(qualified, key=lambda r: r["net_margin"], default=None)
    sweet_band = sweet["band"] if sweet else None

    if sweet is not None:
        conclusion = (
            f"整体加购转化 {round(overall_conv * 100, 1)}%、退款率 {round(overall_refund * 100, 1)}%。"
            f"甜点价位带为{sweet_band}"
            f"（转化 {round((sweet['cart_to_pay'] or 0) * 100, 1)}% ≥ 整体、"
            f"退款 {round((sweet['refund_rate_pay'] or 0) * 100, 1)}% ≤ 整体）。"
        )
    else:
        conclusion = (
            f"整体加购转化 {round(overall_conv * 100, 1)}%、退款率 {round(overall_refund * 100, 1)}%。"
            "无价位带同时满足转化不低于整体且退款不高于整体，暂无明确甜点带。"
        )

    finding = Finding(
        title="价格甜点（价格带 × 转化 × 退款）",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(usable), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(usable)),
        key_numbers={
            "band_count": len(band_rows),
            "sweet_spot_band": sweet_band,
            "overall_cart_to_pay": bounded_rate(overall_conv),
            "overall_refund_rate": bounded_rate(overall_refund),
            "sweet_net_margin": sweet["net_margin"] if sweet else None,
        },
        caveats=[
            M.causal_disclaimer("品类、流量和活动结构不同"),
            "价位带口径与价格带分布/退款根因一致（客单价高低分档），便于跨模块对照。",
            "转化与退款按价位带内 SKU 聚合，非顾客个体口径；甜点带为描述性最优，非因果最优。",
        ],
        recommended_action=_LEVER_SWEET_SPOT,
        evidence_reason=(
            "价位带由 aov>0 SKU 的客单价四分位切分（共享口径）；转化=Σ成交/Σ加购、"
            "退款=Σ退款单/Σ成交单，甜点带取「转化≥整体且退款≤整体」中净收益最高者，观察性。"
        ),
        confounders=list(_SWEET_SPOT_CONFOUNDERS),
    )
    return finding, band_rows


# --------------------------------------------------------------------------- #
# Finding 3 — 加购转化与客单价结构 (degrade-gated)
# --------------------------------------------------------------------------- #
def _conversion_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if not {"add_to_cart_users", "paid_buyers"} <= cols:
        limitations.append(
            "sku_performance 缺少 add_to_cart_users/paid_buyers 列，跳过加购转化与客单价结构。"
        )
        return None, []

    has_name = "sku_name" in cols
    has_aov = "aov" in cols

    usable = [r for r in rows if _num(r.get("add_to_cart_users")) > 0]
    if not usable:
        limitations.append("sku_performance 无有效加购数据，跳过加购转化与客单价结构。")
        return None, []

    # This finding's universe (加购人数>0) differs from the GMV-Pareto universe
    # (GMV>0). A SKU with carts but no paid GMV counts here yet not there, so the
    # two SKU counts legitimately diverge — reconcile them explicitly.
    gmv_universe = sum(1 for r in rows if _num(r.get("gmv")) > 0) if "gmv" in cols else None

    total_cart = sum(_num(r.get("add_to_cart_users")) for r in usable)
    total_pay = sum(_num(r.get("paid_buyers")) for r in usable)
    overall_cart_to_pay = bounded_rate(total_pay / total_cart) if total_cart else None

    median_aov = None
    if has_aov:
        aov_values = sorted(_num(r.get("aov")) for r in usable if r.get("aov") is not None)
        if aov_values:
            median_aov = _median(aov_values)

    conv_rows: list[dict] = []
    for r in usable:
        cart = _num(r.get("add_to_cart_users"))
        pay = _num(r.get("paid_buyers"))
        row: dict = {
            "sku_name": r.get("sku_name") if has_name else r.get("sku_id"),
            "add_to_cart_users": cart,
            "paid_buyers": pay,
            "cart_to_pay": bounded_rate(pay / cart) if cart else None,
        }
        if has_aov and r.get("aov") is not None:
            aov = _num(r.get("aov"))
            row["aov"] = aov
            if median_aov:
                if aov >= median_aov * 1.5:
                    row["aov_tag"] = "高客单"
                elif aov <= median_aov * 0.5:
                    row["aov_tag"] = "低客单"
                else:
                    row["aov_tag"] = "中位"
        conv_rows.append(row)
    conv_rows.sort(key=lambda r: r["add_to_cart_users"], reverse=True)

    conclusion = (
        f"整体加购转化率约 {round((overall_cart_to_pay or 0) * 100, 1)}%。"
        + (f" 客单价中位数约 {money(median_aov)}。" if median_aov else "")
    )

    finding = Finding(
        title="加购转化与客单价结构",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(usable), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(usable)),
        key_numbers={
            "overall_cart_to_pay": overall_cart_to_pay,
            "median_aov": median_aov,
            "conversion_universe": len(usable),
            "gmv_universe": gmv_universe,
        },
        caveats=_conversion_caveats(len(usable), gmv_universe),
        recommended_action=_LEVER_CONVERSION,
        evidence_reason="加购转化用真实 add_to_cart_users/paid_buyers 聚合，客单价用 aov 中位数描述，均为观察性。",
        confounders=list(_CONFOUNDERS),
    )
    return finding, conv_rows


def _conversion_caveats(conversion_universe: int, gmv_universe: int | None) -> list[str]:
    caveats = [M.causal_disclaimer("流量质量、活动折扣和品类不同")]
    if gmv_universe is not None:
        caveats.append(
            f"本节口径为「加购人数>0」的 SKU 全集（{qty(conversion_universe)} 个），"
            f"与 GMV 集中度的「GMV>0」有效 SKU 全集（{qty(gmv_universe)} 个）不同："
            f"有加购但未成交/无 GMV 的 SKU 计入本节、不计入 GMV 集中度，故两处 SKU 数不一致。"
        )
    return caveats


# --------------------------------------------------------------------------- #
# Finding 4 — 二级品类结构（营收 vs 退款） (degrade-gated)
# --------------------------------------------------------------------------- #
_LEVER_L2 = (
    "高营收 L2 保供选品、稳流量；高退款 L2 单独复核尺寸/描述/发货，"
    "把营收贡献与退款风险分开管理，避免一刀切。"
)


def _category_l2_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if "category_l2" not in cols or "gmv" not in cols:
        limitations.append("sku_performance 缺少 category_l2/gmv 列，跳过二级品类结构下钻。")
        return None, []

    valid = [r for r in rows if _num(r.get("gmv")) > 0]
    if not valid:
        limitations.append("sku_performance 无有效 GMV 数据，跳过二级品类结构下钻。")
        return None, []

    has_refund = {"refund_rate_pay", "paid_orders"} <= cols
    has_refund_orders = "refund_orders_pay" in cols

    # Aggregate GMV + refund per L2. Refund rate uses真实退款单/成交单 when present,
    # otherwise falls back to成交单加权的 refund_rate_pay（口径一致，避免小样本失真）。
    groups: dict = {}
    for r in valid:
        key = r.get("category_l2")
        g = groups.setdefault(key, {"gmv": 0.0, "orders": 0.0, "refund_orders": 0.0})
        g["gmv"] += _num(r.get("gmv"))
        if has_refund:
            orders = _num(r.get("paid_orders"))
            g["orders"] += orders
            if has_refund_orders:
                g["refund_orders"] += _num(r.get("refund_orders_pay"))
            else:
                rate = bounded_rate(r.get("refund_rate_pay")) or 0.0
                g["refund_orders"] += rate * orders

    total_gmv = sum(g["gmv"] for g in groups.values())

    l2_rows: list[dict] = []
    for key, g in groups.items():
        refund_rate = None
        if has_refund and g["orders"] >= _MIN_ORDERS_GUARD:
            refund_rate = bounded_rate(g["refund_orders"] / g["orders"]) if g["orders"] else None
        l2_rows.append(
            {
                "category_l2": key,
                "gmv": g["gmv"],
                "gmv_share": (g["gmv"] / total_gmv) if total_gmv else None,
                "paid_orders": g["orders"] if has_refund else None,
                "refund_rate": refund_rate,
            }
        )
    l2_rows.sort(key=lambda r: r["gmv"], reverse=True)

    top_gmv = l2_rows[0] if l2_rows else None
    top_gmv_category = top_gmv["category_l2"] if top_gmv else None
    top_gmv_share = top_gmv["gmv_share"] if top_gmv else None

    # Refund hotspot is ranked independently of GMV — the whole point is that the
    # revenue leader and the refund leak are often different二级品类。
    refund_ranked = [r for r in l2_rows if r["refund_rate"] is not None]
    refund_ranked.sort(key=lambda r: r["refund_rate"], reverse=True)
    top_refund = refund_ranked[0] if refund_ranked else None

    key_numbers: dict[str, object] = {
        "category_l2_count": len(l2_rows),
        "top_gmv_category_l2": top_gmv_category,
        "top_gmv_category_l2_share": top_gmv_share,
    }
    if top_refund is not None:
        key_numbers["top_refund_category_l2"] = top_refund["category_l2"]
        key_numbers["top_refund_category_l2_rate"] = top_refund["refund_rate"]

    conclusion = (
        f"共 {qty(len(l2_rows))} 个二级品类，营收头部为 {top_gmv_category}"
        f"（占 GMV {round((top_gmv_share or 0) * 100)}%）。"
    )
    if top_refund is not None and top_refund["category_l2"] != top_gmv_category:
        conclusion += (
            f" 退款集中在 {top_refund['category_l2']}"
            f"（退款率约 {round((top_refund['refund_rate'] or 0) * 100, 1)}%），"
            f"与营收头部并非同一品类，应分开管理。"
        )
    elif top_refund is not None:
        conclusion += (
            f" 营收头部 {top_gmv_category} 同时也是退款率最高品类"
            f"（约 {round((top_refund['refund_rate'] or 0) * 100, 1)}%），需重点复核。"
        )

    caveats = [M.causal_disclaimer("价格带、发货时效和流量结构不同")]
    if not has_refund:
        caveats.append("缺少 refund_rate_pay/paid_orders 列，本节仅呈现营收结构，退款率留空。")
    else:
        caveats.append(
            f"退款率仅对成交单数 ≥{_MIN_ORDERS_GUARD} 的二级品类计算，样本不足的品类退款率留空以免失真。"
        )

    finding = Finding(
        title="二级品类结构（营收 vs 退款）",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(valid), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(valid)),
        key_numbers=key_numbers,
        caveats=caveats,
        recommended_action=_LEVER_L2,
        evidence_reason=(
            "按 category_l2 聚合真实 gmv 与成交/退款单，营收与退款独立排序；观察性描述，非因果。"
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, l2_rows


# --------------------------------------------------------------------------- #
# Shared helpers (ported from audience_structure/refund_diagnosis)
# --------------------------------------------------------------------------- #
def _num(value) -> float:
    return to_finite_float(value, 0.0)


def _median(values: list[float]) -> float:
    n = len(values)
    mid = n // 2
    if n % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


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
                title="SKU 结构不可诊断",
                conclusion="需要导出 sku_performance（SKU 销售明细）数据后才能诊断 SKU 结构与退款情况。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["SKU 销售明细缺失应视为导入缺口。"],
                recommended_action="导出规格明细/SKU 销售数据后重新构建。",
            )
        ],
        tables={"sku_gmv_pareto": []},
        limitations=[reason],
    )
