"""退款根因诊断 (refund_root_cause_diagnosis) — decompose refunds by ship stage,
category tree, and price band.

Sibling of ``audience_structure`` / ``sku_structure``: same module contract,
shared stat helpers, never-raise degradation discipline. Observational only —
no causal attribution. Category and price-band scans additionally use
``multiplicity.py`` (one-sided binomial test + Benjamini-Hochberg) to control
the false-discovery rate across many simultaneous "above baseline" checks.
"""
from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    bounded_rate,
    min_n_guard,
    wilson_interval,
)
from xhs_ceramics_analytics.analytics.distribution import band_of, quantile_edges
from xhs_ceramics_analytics.analytics.multiplicity import (
    benjamini_hochberg,
    expected_false_positives,
    one_sided_binomial_p,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence, score_reliability

TASK_ID = "refund_root_cause_diagnosis"
TITLE = "退款根因诊断"

_LEVER_PRE_SHIP = "发货前退款为主：这周先把发货前退款的订单逐单翻一遍看原因，对照物流时效承诺、悔单率与价保规则，挑最集中的那条先改。"
_LEVER_POST_SHIP = "发货后退款为主：这周先集中看发货后退款的退货留言和差评，对照商品质量、描述一致性与尺寸/包装，找出被吐槽最多的那点先补。"
_LEVER_CATEGORY = "高退款品类：优先跟进 BH-FDR 显著品类，再复核其详情页描述、尺寸表与质检标准。"
_LEVER_PRICE_BAND = "高退款价位带：这周先想清楚这档价位买家为什么觉得不值——核对价格与预期落差，再复核该价位带的赠品/活动政策。"

_SHIP_CONFOUNDERS = ["品类与尺寸结构", "物流与时效", "描述一致性"]
_CATEGORY_CONFOUNDERS = ["品类内价格带混合", "尺寸与包装", "季节与活动"]
_PRICE_BAND_CONFOUNDERS = ["价格与预期差", "高价类目结构", "赠品与活动"]

_BAND_LABELS = ["低价位", "中低价位", "中高价位", "高价位"]

_SHIP_STAGE_ZH = {"pre_ship": "发货前", "post_ship": "发货后"}


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

        ship_finding, ship_rows = _ship_stage_finding(con, rows, cols, limitations)
        findings.append(ship_finding)
        tables["refund_by_ship_stage"] = ship_rows

        cat_finding, cat_rows = _category_finding(rows, cols, limitations)
        if cat_finding is not None:
            findings.append(cat_finding)
            tables["refund_by_category"] = cat_rows

        band_finding, band_rows = _price_band_finding(rows, cols, limitations)
        if band_finding is not None:
            findings.append(band_finding)
            tables["refund_by_price_band"] = band_rows
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
# Finding 1 — 发货前 vs 发货后分解 (always emitted)
# --------------------------------------------------------------------------- #
def _ship_stage_finding(
    con, sku_rows: list[dict], sku_cols: set[str], limitations: list[str]
) -> tuple[Finding, list[dict]]:
    ship_cols = {"pre_ship_refund_rate_pay", "post_ship_refund_rate_pay", "paid_orders"}

    bod_exists = _table_exists(con, "business_overview_daily")
    bod_cols = _table_columns(con, "business_overview_daily") if bod_exists else set()
    use_bod = bod_exists and ship_cols <= bod_cols
    use_sku = ship_cols <= sku_cols

    if not use_bod and not use_sku:
        limitations.append(
            "business_overview_daily 与 sku_performance 均缺少发货前后退款率/paid_orders 列，跳过发货前后分解。"
        )
        finding = Finding(
            title="发货前后退款分解",
            conclusion="导出数据里没有发货前、发货后的退款率，看不出退款主要发生在发货前还是发货后。",
            evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            key_numbers={
                "pre_ship_rate": None,
                "post_ship_rate": None,
                "dominant_stage": None,
                "source": None,
            },
            caveats=["导出数据里没有发货前、发货后的退款率，暂时看不出退款主要卡在哪个阶段。"],
            confounders=list(_SHIP_CONFOUNDERS),
            evidence_reason=M.methodology_note(
                "business_overview_daily 与 sku_performance 均无发货前后退款率列，无法计算。",
                M.METHOD_OBSERVATIONAL,
            ),
        )
        return finding, []

    if use_bod:
        rows = _fetch_all(con, "business_overview_daily")
        source = "business_overview"
    else:
        rows = [r for r in sku_rows if _num(r.get("paid_orders")) > 0]
        source = "sku_performance"

    total_orders = sum(_num(r.get("paid_orders")) for r in rows)
    pre_weighted = sum(
        (bounded_rate(r.get("pre_ship_refund_rate_pay")) or 0.0) * _num(r.get("paid_orders"))
        for r in rows
    )
    post_weighted = sum(
        (bounded_rate(r.get("post_ship_refund_rate_pay")) or 0.0) * _num(r.get("paid_orders"))
        for r in rows
    )
    pre_rate = (pre_weighted / total_orders) if total_orders else None
    post_rate = (post_weighted / total_orders) if total_orders else None

    dominant_stage = None
    if pre_rate is not None and post_rate is not None and pre_rate != post_rate:
        dominant_stage = "pre_ship" if pre_rate > post_rate else "post_ship"

    caveats = [
        M.causal_disclaimer("品类结构、物流时效和描述一致性不同"),
        "这里算的是按订单数加权的退款率；退款金额的占比见退款结构诊断，分渠道的退款率见渠道结构与健康诊断，这三处算的不是一回事、并不重复。",
    ]
    if dominant_stage is not None:
        dominant_zh = _SHIP_STAGE_ZH[dominant_stage]
        lever_hint = "物流时效/悔单/价保" if dominant_stage == "pre_ship" else "质量/描述不符/尺寸"
        conclusion = (
            f"退款以{dominant_zh}为主（发货前 {round((pre_rate or 0) * 100, 1)}% vs "
            f"发货后 {round((post_rate or 0) * 100, 1)}%）——优先排查{lever_hint}。"
        )
        recommended_action = _LEVER_PRE_SHIP if dominant_stage == "pre_ship" else _LEVER_POST_SHIP
    elif pre_rate is not None and post_rate is not None:
        conclusion = (
            f"发货前后退款率相近（发货前 {round(pre_rate * 100, 1)}% vs 发货后 {round(post_rate * 100, 1)}%），未见明显阶段集中。"
        )
        recommended_action = None
    else:
        limitations.append("发货前后退款分解可用列存在但样本 paid_orders 合计为 0，无法计算阶段占比。")
        conclusion = "有发货前后的退款率，但对应的订单数是 0，看不出退款集中在哪个阶段。"
        recommended_action = None

    ship_rows = [
        {"stage": "pre_ship", "stage_zh": "发货前", "rate": pre_rate},
        {"stage": "post_ship", "stage_zh": "发货后", "rate": post_rate},
    ]

    finding = Finding(
        title="发货前后退款分解",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_orders), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_orders)),
        key_numbers={
            "pre_ship_rate": pre_rate,
            "post_ship_rate": post_rate,
            "dominant_stage": dominant_stage,
            "source": source,
        },
        caveats=caveats,
        recommended_action=recommended_action,
        evidence_reason=M.methodology_note(
            f"发货前后退款率用 {source} 的 paid_orders 加权聚合。",
            M.METHOD_OBSERVATIONAL,
        ),
        confounders=list(_SHIP_CONFOUNDERS),
    )
    return finding, ship_rows


# --------------------------------------------------------------------------- #
# Finding 2 — 品类退款分解 (degrade-gated)
# --------------------------------------------------------------------------- #
def _category_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if "category_l1" not in cols:
        limitations.append("sku_performance 缺少 category_l1，跳过品类退款分解。")
        return None, []
    has_refund_orders = "refund_orders_pay" in cols
    has_refund_rate = "refund_rate_pay" in cols
    if "paid_orders" not in cols or not (has_refund_orders or has_refund_rate):
        limitations.append(
            "sku_performance 缺少 paid_orders 或 refund_orders_pay/refund_rate_pay，跳过品类退款分解。"
        )
        return None, []

    usable = [r for r in rows if _num(r.get("paid_orders")) > 0]
    if not usable:
        limitations.append("sku_performance 无有效支付订单数据，跳过品类退款分解。")
        return None, []

    total_orders = sum(_num(r.get("paid_orders")) for r in usable)
    total_refund = sum(_refund_orders(r, has_refund_orders) for r in usable)
    baseline = (total_refund / total_orders) if total_orders else None

    groups: dict = {}
    for r in usable:
        key = r.get("category_l1")
        g = groups.setdefault(key, {"paid_orders": 0.0, "refund_orders": 0.0})
        g["paid_orders"] += _num(r.get("paid_orders"))
        g["refund_orders"] += _refund_orders(r, has_refund_orders)

    category_rows: list[dict] = []
    guarded: list[dict] = []
    for key, g in groups.items():
        n = g["paid_orders"]
        k = g["refund_orders"]
        rate = (k / n) if n else None
        lo, hi = wilson_interval(k, n) if min_n_guard(n) else (None, None)
        row = {
            "category_l1": key,
            "paid_orders": n,
            "refund_orders": k,
            "refund_rate": rate,
            "wilson_low": lo,
            "wilson_high": hi,
            "fdr_significant": False,
        }
        category_rows.append(row)
        if min_n_guard(n) and baseline is not None:
            guarded.append(row)

    if guarded and baseline is not None:
        pvalues = [
            one_sided_binomial_p(r["refund_orders"], r["paid_orders"], baseline) for r in guarded
        ]
        survived = benjamini_hochberg(pvalues, alpha=0.05)
        for row, sig in zip(guarded, survived):
            row["fdr_significant"] = sig
        fdr_count = sum(1 for s in survived if s)
    else:
        fdr_count = 0
    exp_fp = expected_false_positives(len(guarded), alpha=0.05)

    category_rows.sort(
        key=lambda r: (r["refund_rate"] if r["refund_rate"] is not None else -1.0), reverse=True
    )
    top = category_rows[0] if category_rows else None

    has_category = top is not None and top["refund_rate"] is not None
    if has_category:
        fdr_clause = (
            "没有品类明显高于大盘（已排除统计误报）"
            if fdr_count == 0
            else f"{qty(fdr_count)} 个品类明显高于大盘（已排除统计误报）"
        )
        conclusion = (
            f"最高退款品类为 {top['category_l1']}（退款率 {round(top['refund_rate'] * 100, 1)}%）；"
            f"{fdr_clause}。"
        )
    else:
        conclusion = "SKU 数据里的品类信息不足，判断不出退款最高的是哪个品类。"

    finding = Finding(
        title="品类退款分解",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_orders), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_orders)),
        key_numbers={
            "baseline_refund_rate": baseline,
            "top_category": top["category_l1"] if top else None,
            "top_category_rate": top["refund_rate"] if top else None,
            "fdr_significant_count": fdr_count,
            "expected_false_positives": exp_fp,
        },
        caveats=[
            M.causal_disclaimer("品类内价格带、尺寸和季节活动不同"),
        ],
        # 品类不可判断时不给出跟进动作（避免无数据支撑的建议）。
        recommended_action=_LEVER_CATEGORY if has_category else None,
        evidence_reason=M.methodology_note(
            "品类退款率用真实 paid_orders 加权聚合基线，显著性用单侧二项检验判定。",
            M.METHOD_FDR,
        ),
        confounders=list(_CATEGORY_CONFOUNDERS),
    )
    return finding, category_rows


# --------------------------------------------------------------------------- #
# Finding 3 — 价格带退款分解 (degrade-gated)
# --------------------------------------------------------------------------- #
def _price_band_finding(
    rows: list[dict], cols: set[str], limitations: list[str]
) -> tuple[Finding | None, list[dict]]:
    if "aov" not in cols:
        limitations.append("sku_performance 缺少 aov，跳过价格带退款分解。")
        return None, []
    has_refund_orders = "refund_orders_pay" in cols
    has_refund_rate = "refund_rate_pay" in cols
    if "paid_orders" not in cols or not (has_refund_orders or has_refund_rate):
        limitations.append(
            "sku_performance 缺少 paid_orders 或 refund_orders_pay/refund_rate_pay，跳过价格带退款分解。"
        )
        return None, []
    has_gmv = "gmv" in cols

    usable = [
        r
        for r in rows
        if _num(r.get("paid_orders")) > 0 and r.get("aov") is not None and _num(r.get("aov")) > 0
    ]
    if not usable:
        limitations.append("sku_performance 无有效 aov/paid_orders 样本，跳过价格带退款分解。")
        return None, []

    gmv_positive_aovs = [
        _num(r.get("aov")) for r in usable if has_gmv and _num(r.get("gmv")) > 0
    ]
    # Price bands come from the shared caliber (analytics.distribution): quartile
    # left edges + left-closed band_of. sku_structure bands prices the same way, so
    # "中高价位" means the identical AOV window in both modules.
    edges = quantile_edges(gmv_positive_aovs, 4)
    if not edges:
        limitations.append("gmv>0 的 SKU 样本不足 4 个，无法计算价格带分位，跳过价格带退款分解。")
        return None, []
    aov_max = max(gmv_positive_aovs)
    thresholds = list(edges) + [aov_max]

    total_orders = sum(_num(r.get("paid_orders")) for r in usable)
    total_gmv = sum(_num(r.get("gmv")) for r in usable) if has_gmv else None

    bands: dict[int, dict] = {
        i: {"paid_orders": 0.0, "refund_orders": 0.0, "gmv": 0.0} for i in range(4)
    }
    for r in usable:
        idx = band_of(_num(r.get("aov")), edges)
        b = bands[idx]
        b["paid_orders"] += _num(r.get("paid_orders"))
        b["refund_orders"] += _refund_orders(r, has_refund_orders)
        if has_gmv:
            b["gmv"] += _num(r.get("gmv"))

    band_rows: list[dict] = []
    for i in range(4):
        b = bands[i]
        n = b["paid_orders"]
        k = b["refund_orders"]
        rate = (k / n) if n else None
        gmv_share = (b["gmv"] / total_gmv) if (has_gmv and total_gmv) else None
        band_rows.append(
            {
                "band": _BAND_LABELS[i],
                "aov_low": thresholds[i],
                "aov_high": thresholds[i + 1],
                "paid_orders": n,
                "refund_rate": rate,
                "gmv_share": gmv_share,
            }
        )

    guarded = [r for r in band_rows if min_n_guard(r["paid_orders"]) and r["refund_rate"] is not None]
    highest = max(guarded, key=lambda r: r["refund_rate"], default=None)
    highest_band = highest["band"] if highest else None

    if highest is not None:
        conclusion = (
            f"{highest_band}带退款率最高（{round(highest['refund_rate'] * 100, 1)}%），"
            f"GMV 占比 {round((highest['gmv_share'] or 0) * 100, 1)}%。"
        )
    else:
        limitations.append("各价格带样本量均不足 30 或退款率不可计算，无法判断最高退款价位带。")
        conclusion = "各价位段的订单太少，看不出哪个价位退款最高。"

    finding = Finding(
        title="价格带退款分解",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(total_orders), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(total_orders)),
        key_numbers={
            "highest_refund_band": highest_band,
            "band_count": len(band_rows),
        },
        caveats=[M.causal_disclaimer("价格与预期落差、类目结构和赠品活动不同")],
        recommended_action=_LEVER_PRICE_BAND,
        evidence_reason=M.methodology_note(
            "价格带由 gmv>0 SKU 的 aov 四分位切分，退款率用真实 paid_orders 加权聚合。",
            M.METHOD_OBSERVATIONAL,
        ),
        confounders=list(_PRICE_BAND_CONFOUNDERS),
    )
    return finding, band_rows


# --------------------------------------------------------------------------- #
# Shared helpers (ported from audience_structure)
# --------------------------------------------------------------------------- #
def _refund_orders(r: dict, has_refund_orders: bool) -> float:
    if has_refund_orders:
        return _num(r.get("refund_orders_pay"))
    return (bounded_rate(r.get("refund_rate_pay")) or 0.0) * _num(r.get("paid_orders"))


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
                title="退款根因不可诊断",
                conclusion="需要导出 sku_performance（SKU 表现）数据后才能诊断退款根因。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["没有 SKU 表现数据，应当视为导出时漏掉了、需要补齐。"],
                recommended_action="导出 SKU 表现（含品类、aov、发货前后退款率、退款订单数）后重新构建。",
            )
        ],
        tables={"refund_by_ship_stage": []},
        limitations=[reason],
    )
