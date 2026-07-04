"""SKU 结构与退款诊断 — sku_structure_diagnosis.

Same module contract as ``audience_structure``/``refund_diagnosis``: never-raise
degradation, ``_table_exists``/``_table_columns``/``_fetch_all``/``_num`` helpers,
per-Finding confounders + observational caveats. Observational only — no causal
attribution (SKU-level GMV/退款/转化 mix reflects品类、价格带与流量结构等多重因素叠加).
"""
import math
from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import bounded_rate
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

    key_numbers: dict[str, object] = {
        "sku_count": sku_count,
        "gmv_total": total_gmv,
        "top_decile_gmv_share": top_decile_gmv_share,
        "skus_for_80pct": skus_for_80pct,
    }
    if top_category is not None:
        key_numbers["top_category"] = top_category

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
        caveats=["观察性诊断，非因果——GMV 集中度可能由品类结构、价格带与活动节奏共同驱动。"],
        recommended_action=_LEVER_PARETO,
        evidence_reason="GMV 集中度基于真实 gmv 列排序聚合，观察性描述，非因果。",
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
        f"其中 {qty(fdr_survivors)} 个经 BH-FDR 5% 显著（预计假阳性约 {round(exp_false_positives, 1)} 个）。"
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
            "观察性诊断，非因果——退款率差异可能由品类、发货时效与售后政策共同驱动。",
            "多重比较用 Benjamini-Hochberg FDR 控制假阳性；缺退款单列时退款单以率×成交单估计。",
        ],
        recommended_action=_LEVER_REFUND,
        evidence_reason=(
            "退款基线用真实 paid_orders 加权聚合；高退款 SKU 先经基线筛选，"
            "再以单侧二项 p 值 + BH-FDR 控制多重比较假阳性。"
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, outliers


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
    caveats = [
        "观察性诊断，非因果——加购转化与客单价结构可能受流量质量、活动折扣与品类共同影响。"
    ]
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

    caveats = [
        "观察性诊断，非因果——二级品类的营收与退款差异可能由价格带、发货时效与流量结构共同驱动。"
    ]
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
    return float(value) if value is not None else 0.0


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
