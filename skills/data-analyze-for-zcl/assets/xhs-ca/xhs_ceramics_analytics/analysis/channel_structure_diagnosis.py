"""渠道结构与健康诊断 — channel_structure_diagnosis.

Sibling of ``audience_structure``/``refund_diagnosis``: same module contract,
shared stat helpers, never-raise degradation discipline. Observational only —
no causal attribution. Compares the two sales channels captured in
``business_overview_daily``: 笔记 (note) vs 商品卡 (card).

Real counts available for 笔记/商卡: the daily table carries genuine per-carrier
买家数/访客数/退款订单数/支付订单数, so conversion and refund rate prefer real
Σk/Σn counts over the pre-computed rate columns — no reverse derivation.
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    bounded_rate,
    min_n_guard,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

TASK_ID = "channel_structure_diagnosis"
TITLE = "渠道结构与健康诊断"

_CARRIER_ZH = {"note": "笔记", "card": "商品卡"}

# A difference below this (absolute proportion) is treated as trivial even when
# the z-test flags it — "显著" is gated on a reported non-trivial effect size.
_MIN_MEANINGFUL_DIFF = 0.01

_OBS_CAVEAT = "观察性对比，非因果——渠道差异可能由流量结构与选品共同驱动。"

_SCALE_CONFOUNDERS = ["渠道流量结构差异", "选品与内容混合", "投放与活动节奏"]
_CONV_CONFOUNDERS = ["客群与流量质量差异", "价格带与品类结构", "承接页差异"]
_REFUND_CONFOUNDERS = ["品类与尺寸结构", "物流与时效", "描述一致性"]


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "business_overview_daily"):
            return _missing_result("缺少 business_overview_daily 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        scale_finding, scale_rows = _scale_finding(con, limitations)
        findings.append(scale_finding)
        tables["channel_scale"] = scale_rows

        conv_finding, conv_rows = _conversion_finding(con, limitations)
        if conv_finding is not None:
            findings.append(conv_finding)
            tables["channel_conversion"] = conv_rows

        refund_finding, refund_rows = _refund_finding(con, limitations)
        if refund_finding is not None:
            findings.append(refund_finding)
            tables["channel_refund"] = refund_rows
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
# Finding 1 — 渠道收入与规模对比 (always emitted when note_gmv/card_gmv present)
# --------------------------------------------------------------------------- #
def _scale_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "business_overview_daily")
    if not {"note_gmv", "card_gmv"} <= cols:
        limitations.append("business_overview_daily 缺少 note_gmv/card_gmv 列，无法进行渠道收入对比。")
        finding = Finding(
            title="渠道收入与规模对比",
            conclusion="business_overview_daily 缺少 note_gmv/card_gmv 列，无法判断笔记与商品卡的渠道规模。",
            evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            key_numbers={
                "note_gmv": None,
                "card_gmv": None,
                "dominant_carrier": None,
                "dominant_gmv_share": None,
            },
            caveats=[_OBS_CAVEAT],
            confounders=list(_SCALE_CONFOUNDERS),
            evidence_reason="缺少 note_gmv/card_gmv，无法计算渠道 GMV 份额。",
        )
        return finding, []

    rows = _fetch_all(con, "business_overview_daily")
    note_gmv = sum(_num(r.get("note_gmv")) for r in rows)
    card_gmv = sum(_num(r.get("card_gmv")) for r in rows)
    total_gmv = note_gmv + card_gmv

    has_orders = {"note_paid_orders", "card_paid_orders"} <= cols
    note_orders = sum(_num(r.get("note_paid_orders")) for r in rows) if has_orders else None
    card_orders = sum(_num(r.get("card_paid_orders")) for r in rows) if has_orders else None

    has_buyers = {"笔记支付买家数", "商卡支付买家数"} <= cols
    note_buyers = sum(_num(r.get("笔记支付买家数")) for r in rows) if has_buyers else None
    card_buyers = sum(_num(r.get("商卡支付买家数")) for r in rows) if has_buyers else None

    has_net = {"笔记退款后支付金额_支付时间", "商卡退款后支付金额_支付时间"} <= cols
    note_net = sum(_num(r.get("笔记退款后支付金额_支付时间")) for r in rows) if has_net else None
    card_net = sum(_num(r.get("商卡退款后支付金额_支付时间")) for r in rows) if has_net else None

    caveats = [_OBS_CAVEAT]
    dominant_carrier: str | None = None
    other_carrier: str | None = None
    dominant_share: float | None = None

    if total_gmv <= 0:
        limitations.append("business_overview_daily 中 note_gmv/card_gmv 求和为 0，无法判断主渠道。")
        conclusion = "笔记与商品卡 GMV 求和为 0，无法判断主渠道。"
        sample_size = len(rows)
    else:
        note_share = note_gmv / total_gmv
        card_share = card_gmv / total_gmv
        dominant_carrier = "card" if card_share >= note_share else "note"
        other_carrier = "note" if dominant_carrier == "card" else "card"
        dominant_share = card_share if dominant_carrier == "card" else note_share
        other_share = note_share if dominant_carrier == "card" else card_share
        conclusion = (
            f"{_CARRIER_ZH[dominant_carrier]}为主渠道（GMV 占比 {round(dominant_share * 100)}%），"
            f"{_CARRIER_ZH[other_carrier]}占 {round(other_share * 100)}%。"
        )
        if has_orders and (note_orders + card_orders) > 0:
            sample_size = int(note_orders + card_orders)
        else:
            sample_size = len(rows)

    scale_rows = [
        {
            "carrier": "note",
            "carrier_zh": _CARRIER_ZH["note"],
            "gmv": note_gmv,
            "gmv_share": (note_gmv / total_gmv) if total_gmv > 0 else None,
            "paid_orders": note_orders,
            "buyers": note_buyers,
            "net_gmv": note_net,
        },
        {
            "carrier": "card",
            "carrier_zh": _CARRIER_ZH["card"],
            "gmv": card_gmv,
            "gmv_share": (card_gmv / total_gmv) if total_gmv > 0 else None,
            "paid_orders": card_orders,
            "buyers": card_buyers,
            "net_gmv": card_net,
        },
    ]
    scale_rows.sort(key=lambda r: r["gmv"], reverse=True)

    if dominant_carrier is not None:
        lever = (
            f"重点巩固主渠道{_CARRIER_ZH[dominant_carrier]}的供给与内容承接；"
            f"同时排查{_CARRIER_ZH[other_carrier]}渠道转化/退款是否存在健康问题，"
            "判断是否值得追加资源。"
        )
    else:
        lever = "GMV 数据不足，暂无法给出渠道资源建议。"

    finding = Finding(
        title="渠道收入与规模对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(sample_size), has_controls=False, confounder_count=len(_SCALE_CONFOUNDERS)
        ),
        key_numbers={
            "note_gmv": note_gmv,
            "card_gmv": card_gmv,
            "dominant_carrier": dominant_carrier,
            "dominant_gmv_share": dominant_share,
        },
        caveats=caveats,
        recommended_action=lever,
        evidence_reason="GMV/订单/买家数为 business_overview_daily 逐日求和，渠道份额为观察性描述。",
        confounders=list(_SCALE_CONFOUNDERS),
    )
    return finding, scale_rows


# --------------------------------------------------------------------------- #
# Finding 2 — 渠道转化与客单对比 (degrade-gated)
# --------------------------------------------------------------------------- #
def _conversion_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "business_overview_daily")
    count_cols = {"笔记支付买家数", "笔记商品访客数", "商卡支付买家数", "商卡商品访客数"}
    rate_cols = {"笔记支付转化率", "商卡支付转化率"}
    has_counts = count_cols <= cols
    has_rates = rate_cols <= cols
    if not has_counts and not has_rates:
        limitations.append(
            "business_overview_daily 缺少笔记/商卡访客-买家计数及转化率列，跳过渠道转化对比。"
        )
        return None, []

    rows = _fetch_all(con, "business_overview_daily")
    caveats = [_OBS_CAVEAT]
    note_visitors = card_visitors = note_buyers = card_buyers = None
    note_ci = card_ci = (None, None)

    if has_counts:
        source = "count"
        note_visitors = sum(_num(r.get("笔记商品访客数")) for r in rows)
        note_buyers = sum(_num(r.get("笔记支付买家数")) for r in rows)
        card_visitors = sum(_num(r.get("商卡商品访客数")) for r in rows)
        card_buyers = sum(_num(r.get("商卡支付买家数")) for r in rows)
        note_conversion = note_buyers / note_visitors if note_visitors else None
        card_conversion = card_buyers / card_visitors if card_visitors else None
        if min_n_guard(note_visitors):
            note_ci = wilson_interval(note_buyers, note_visitors)
        if min_n_guard(card_visitors):
            card_ci = wilson_interval(card_buyers, card_visitors)
        sample_size = int(note_visitors + card_visitors)
    else:
        source = "column"
        caveats.append(
            "转化率取自 笔记支付转化率/商卡支付转化率 列均值（非真实计数），source=column。"
        )
        note_conversion = _column_mean_rate(rows, "笔记支付转化率")
        card_conversion = _column_mean_rate(rows, "商卡支付转化率")
        sample_size = len(rows)

    has_aov = {"笔记客单价", "商卡客单价"} <= cols
    if has_aov:
        note_aov = _column_mean(rows, "笔记客单价")
        card_aov = _column_mean(rows, "商卡客单价")
    else:
        limitations.append("business_overview_daily 缺少 笔记客单价/商卡客单价 列，渠道客单价对比缺失。")
        note_aov = card_aov = None

    conv_diff = None
    if note_conversion is not None and card_conversion is not None:
        conv_diff = note_conversion - card_conversion

    conv_significant = None
    if source == "count" and note_visitors and card_visitors:
        test = two_proportion(note_buyers, note_visitors, card_buyers, card_visitors)
        diff = test["diff"]
        conv_significant = bool(
            test["significant"] and diff is not None and abs(diff) >= _MIN_MEANINGFUL_DIFF
        )
        conv_diff = diff
        caveats.append("显著性用两样本比例 z 检验，辅以效应量门槛（≥1pp）。")

    better_carrier = None
    if note_conversion is not None and card_conversion is not None:
        better_carrier = "note" if note_conversion > card_conversion else "card"

    conclusion = _conversion_conclusion(
        note_conversion, card_conversion, conv_diff, conv_significant, note_aov, card_aov, better_carrier
    )

    finding = Finding(
        title="渠道转化与客单对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(sample_size), has_controls=False, confounder_count=len(_CONV_CONFOUNDERS)
        ),
        key_numbers={
            "note_conversion": note_conversion,
            "card_conversion": card_conversion,
            "conv_diff": conv_diff,
            "conv_significant": conv_significant,
            "note_aov": note_aov,
            "card_aov": card_aov,
            "conversion_source": source,
        },
        caveats=caveats,
        recommended_action="向转化更弱的渠道做承接页/内容优化，向转化更强的渠道倾斜投放与选品。",
        evidence_reason="转化率优先用真实 买家数/访客数 计数；缺失时退回转化率列均值（source=column）。",
        confounders=list(_CONV_CONFOUNDERS),
    )

    conversion_rows = [
        {
            "carrier": "note",
            "carrier_zh": _CARRIER_ZH["note"],
            "visitors": note_visitors,
            "buyers": note_buyers,
            "conversion": note_conversion,
            "aov": note_aov,
            "ci_low": note_ci[0],
            "ci_high": note_ci[1],
        },
        {
            "carrier": "card",
            "carrier_zh": _CARRIER_ZH["card"],
            "visitors": card_visitors,
            "buyers": card_buyers,
            "conversion": card_conversion,
            "aov": card_aov,
            "ci_low": card_ci[0],
            "ci_high": card_ci[1],
        },
    ]
    return finding, conversion_rows


def _conversion_conclusion(
    note_conversion: float | None,
    card_conversion: float | None,
    conv_diff: float | None,
    conv_significant: bool | None,
    note_aov: float | None,
    card_aov: float | None,
    better_carrier: str | None,
) -> str:
    if note_conversion is None or card_conversion is None:
        return "渠道转化数据不足，无法比较笔记与商品卡的转化率。"
    sig_part = ""
    if conv_significant is not None:
        sig_part = f"（{'显著' if conv_significant else '不显著'}）"
    diff_part = f"，差异 {round(conv_diff * 100, 1)}pp{sig_part}" if conv_diff is not None else ""
    conclusion = (
        f"笔记转化 {round(note_conversion * 100, 1)}% vs 商品卡转化 {round(card_conversion * 100, 1)}%"
        f"{diff_part}。"
    )
    if note_aov is not None and card_aov is not None:
        conclusion += f" 客单价：笔记 {round(note_aov, 1)} 元，商品卡 {round(card_aov, 1)} 元。"
    if better_carrier is not None:
        conclusion += f"{_CARRIER_ZH[better_carrier]}转化更好。"
    return conclusion


# --------------------------------------------------------------------------- #
# Finding 3 — 渠道退款健康 (degrade-gated)
# --------------------------------------------------------------------------- #
def _refund_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "business_overview_daily")
    count_cols = {
        "笔记退款订单数_支付时间",
        "note_paid_orders",
        "商卡退款订单数_支付时间",
        "card_paid_orders",
    }
    rate_cols = {"笔记退款率_支付时间", "商卡退款率_支付时间"}
    has_counts = count_cols <= cols
    has_rates = rate_cols <= cols
    if not has_counts and not has_rates:
        limitations.append(
            "business_overview_daily 缺少笔记/商卡退款订单-支付订单计数及退款率列，跳过渠道退款健康。"
        )
        return None, []

    rows = _fetch_all(con, "business_overview_daily")
    caveats = [
        _OBS_CAVEAT,
        "本节为分渠道退款率口径；整体退款金额份额见退款结构诊断，订单加权发货前后率见退款根因诊断，三者非重复。",
    ]
    note_orders = card_orders = note_refund_orders = card_refund_orders = None
    note_ci = card_ci = (None, None)

    if has_counts:
        note_orders = sum(_num(r.get("note_paid_orders")) for r in rows)
        card_orders = sum(_num(r.get("card_paid_orders")) for r in rows)
        note_refund_orders = sum(_num(r.get("笔记退款订单数_支付时间")) for r in rows)
        card_refund_orders = sum(_num(r.get("商卡退款订单数_支付时间")) for r in rows)
        note_refund_rate = note_refund_orders / note_orders if note_orders else None
        card_refund_rate = card_refund_orders / card_orders if card_orders else None
        if min_n_guard(note_orders):
            note_ci = wilson_interval(note_refund_orders, note_orders)
        if min_n_guard(card_orders):
            card_ci = wilson_interval(card_refund_orders, card_orders)
        sample_size = int(note_orders + card_orders)
    else:
        caveats.append("退款率取自 笔记退款率_支付时间/商卡退款率_支付时间 列均值（非真实计数）。")
        note_refund_rate = _column_mean_rate(rows, "笔记退款率_支付时间")
        card_refund_rate = _column_mean_rate(rows, "商卡退款率_支付时间")
        sample_size = len(rows)

    has_note_stage = {"笔记发货前退款率_支付时间", "笔记发货后退款率_支付时间"} <= cols
    has_card_stage = {"商卡发货前退款率_支付时间", "商卡发货后退款率_支付时间"} <= cols
    note_pre = _column_mean_rate(rows, "笔记发货前退款率_支付时间") if has_note_stage else None
    note_post = _column_mean_rate(rows, "笔记发货后退款率_支付时间") if has_note_stage else None
    card_pre = _column_mean_rate(rows, "商卡发货前退款率_支付时间") if has_card_stage else None
    card_post = _column_mean_rate(rows, "商卡发货后退款率_支付时间") if has_card_stage else None

    note_stage = _dominant_stage(note_pre, note_post)
    card_stage = _dominant_stage(card_pre, card_post)

    refund_diff = None
    if note_refund_rate is not None and card_refund_rate is not None:
        refund_diff = note_refund_rate - card_refund_rate

    refund_significant = None
    if has_counts and note_orders and card_orders:
        test = two_proportion(note_refund_orders, note_orders, card_refund_orders, card_orders)
        diff = test["diff"]
        refund_significant = bool(
            test["significant"] and diff is not None and abs(diff) >= _MIN_MEANINGFUL_DIFF
        )
        refund_diff = diff
        caveats.append("显著性用两样本比例 z 检验，辅以效应量门槛（≥1pp）。")

    higher_refund_carrier = None
    higher_stage = None
    if note_refund_rate is not None and card_refund_rate is not None:
        higher_refund_carrier = "note" if note_refund_rate > card_refund_rate else "card"
        higher_stage = note_stage if higher_refund_carrier == "note" else card_stage

    conclusion = _refund_conclusion(
        note_refund_rate, card_refund_rate, refund_significant, higher_refund_carrier, higher_stage
    )
    lever = _refund_lever(higher_refund_carrier, higher_stage)

    finding = Finding(
        title="渠道退款健康",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(sample_size), has_controls=False, confounder_count=len(_REFUND_CONFOUNDERS)
        ),
        key_numbers={
            "note_refund_rate": note_refund_rate,
            "card_refund_rate": card_refund_rate,
            "refund_diff": refund_diff,
            "refund_significant": refund_significant,
            "higher_refund_carrier": higher_refund_carrier,
        },
        caveats=caveats,
        recommended_action=lever,
        evidence_reason="退款率优先用真实 退款订单数/支付订单数 计数；缺失时退回退款率列均值。",
        confounders=list(_REFUND_CONFOUNDERS),
    )

    refund_rows = [
        {
            "carrier": "note",
            "carrier_zh": _CARRIER_ZH["note"],
            "refund_rate": note_refund_rate,
            "pre_ship_rate": note_pre,
            "post_ship_rate": note_post,
            "ci_low": note_ci[0],
            "ci_high": note_ci[1],
        },
        {
            "carrier": "card",
            "carrier_zh": _CARRIER_ZH["card"],
            "refund_rate": card_refund_rate,
            "pre_ship_rate": card_pre,
            "post_ship_rate": card_post,
            "ci_low": card_ci[0],
            "ci_high": card_ci[1],
        },
    ]
    return finding, refund_rows


def _dominant_stage(pre: float | None, post: float | None) -> str | None:
    if pre is None or post is None:
        return None
    return "发货前" if pre >= post else "发货后"


def _refund_conclusion(
    note_refund_rate: float | None,
    card_refund_rate: float | None,
    refund_significant: bool | None,
    higher_refund_carrier: str | None,
    higher_stage: str | None,
) -> str:
    if note_refund_rate is None or card_refund_rate is None:
        return "渠道退款数据不足，无法比较笔记与商品卡的退款健康。"
    higher_rate = note_refund_rate if higher_refund_carrier == "note" else card_refund_rate
    lower_carrier = "card" if higher_refund_carrier == "note" else "note"
    lower_rate = card_refund_rate if higher_refund_carrier == "note" else note_refund_rate
    sig_part = ""
    if refund_significant is not None:
        sig_part = f"（{'显著' if refund_significant else '不显著'}）"
    conclusion = (
        f"{_CARRIER_ZH[higher_refund_carrier]}退款率 {round(higher_rate * 100, 1)}% 高于"
        f"{_CARRIER_ZH[lower_carrier]} {round(lower_rate * 100, 1)}%{sig_part}。"
    )
    if higher_stage:
        conclusion += f"且以{higher_stage}退款为主。"
    return conclusion


def _refund_lever(higher_refund_carrier: str | None, higher_stage: str | None) -> str:
    if higher_refund_carrier is None or higher_stage is None:
        return "退款数据不足，暂无法给出针对性退款优化建议。"
    if higher_stage == "发货前":
        stage_lever = "重点排查物流时效、揽收/发货时长、退款前置提醒与价保机制。"
    else:
        stage_lever = "重点排查商品质量与图文/详情描述一致性问题。"
    return f"{_CARRIER_ZH[higher_refund_carrier]}退款率更高且以{higher_stage}为主：{stage_lever}"


# --------------------------------------------------------------------------- #
# Local helpers — column-mean fallbacks
# --------------------------------------------------------------------------- #
def _column_mean(rows: list[dict], col: str) -> float | None:
    vals = [_num(r.get(col)) for r in rows if r.get(col) is not None]
    return (sum(vals) / len(vals)) if vals else None


def _column_mean_rate(rows: list[dict], col: str) -> float | None:
    vals = [bounded_rate(r.get(col)) for r in rows if r.get(col) is not None]
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


# --------------------------------------------------------------------------- #
# Shared helpers (ported from audience_structure / refund_diagnosis)
# --------------------------------------------------------------------------- #
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
                title="渠道结构不可诊断",
                conclusion="需要导出 business_overview_daily（生意概况日报）数据后才能诊断渠道结构。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["生意概况日报缺失应视为导入缺口。"],
                recommended_action="导出生意概况日报（含笔记/商品卡 GMV、访客、买家、退款列）后重新构建。",
            )
        ],
        tables={"channel_scale": []},
        limitations=[reason],
    )
