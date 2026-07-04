"""笔记级商业效能诊断 — note_commercial_diagnosis.

Sibling of ``audience_structure``: same module contract, shared stat helpers,
never-raise degradation discipline. Observational only — no causal attribution.
Every finding is gated on real columns via ``_table_columns`` (read_csv_auto
builds may omit any of them) and every division is guarded.
"""
import math
from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.concentration import gini, hhi
from xhs_ceramics_analytics.analytics.confidence import bounded_rate, wilson_interval
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

TASK_ID = "note_commercial_diagnosis"
TITLE = "笔记级商业效能诊断"

_MIN_PAID_ORDERS_FOR_REFUND_FLAG = 10
_PARETO_TARGET_SHARE = 0.8
_TOP_DECILE_FRACTION = 0.1

_CONFOUNDERS = ["笔记曝光结构差异", "商品与内容混合", "发布时间与活动节奏"]

_LEVER_PARETO = "头部依赖高：复制头部笔记选题/形式并测试腰部放量。"
_LEVER_CONV = "高曝光低转化笔记优化封面/标题与商详承接，或缩量测试新选题。"
_LEVER_REFUND = "对高退款笔记复核商品描述与预期一致性，必要时下线关联链接。"
_LEVER_REFERRAL = (
    "笔记站外引流成交显著：评估重拍/加投时应把引流贡献计入内容价值，"
    "并优化店铺主页承接（选品陈列、活动位）承接这部分外溢流量。"
)

# 笔记引流去向：每条 = (次数列, 支付金额列, 中文渠道名)。缺列即跳过该渠道，
# 金额恒为 0 的渠道（如本店无直播）在结论中自动省略，不硬报“0 元”。
_REFERRAL_CHANNELS = (
    ("引流店铺主页次数", "引流店铺主页支付金额", "店铺主页"),
    ("引流直播间次数", "引流直播间支付金额", "直播间"),
)

_OBS_CAVEAT = "观察性描述，非因果——笔记间差异可能由曝光结构、选品与发布节奏共同驱动。"


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("缺少 notes 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        pareto_finding, pareto_rows = _gmv_pareto_finding(con, limitations)
        findings.append(pareto_finding)
        tables["note_gmv_pareto"] = pareto_rows

        conv_finding, conv_rows = _conversion_finding(con, limitations)
        if conv_finding is not None:
            findings.append(conv_finding)
            tables["note_conversion_outliers"] = conv_rows

        refund_finding, refund_rows = _refund_finding(con, limitations)
        if refund_finding is not None:
            findings.append(refund_finding)
            tables["note_refund_outliers"] = refund_rows

        referral_finding, referral_rows = _referral_finding(con, limitations)
        if referral_finding is not None:
            findings.append(referral_finding)
            tables["note_referral_attribution"] = referral_rows
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
# Finding 1 — GMV 集中度（帕累托） (always emitted when note_gmv present)
# --------------------------------------------------------------------------- #
def _gmv_pareto_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "notes")
    if "note_gmv" not in cols:
        limitations.append("notes 缺少 note_gmv 列，无法计算 GMV 集中度。")
        finding = Finding(
            title="GMV 集中度（帕累托）",
            conclusion="notes 缺少 note_gmv 列，无法计算笔记 GMV 集中度，需补列后重新构建。",
            evidence_strength=EvidenceStrength.NOT_JUDGABLE,
            key_numbers={
                "note_count": 0,
                "gmv_total": None,
                "top_decile_gmv_share": None,
                "notes_for_80pct": None,
            },
            caveats=[_OBS_CAVEAT, "缺少 note_gmv 列。"],
            confounders=list(_CONFOUNDERS),
            evidence_reason="缺少 note_gmv，无法计算 GMV 集中度。",
        )
        return finding, []

    rows = _fetch_all(con, "notes")
    has_id = "note_id" in cols
    has_title = "title" in cols
    note_count = len(rows)
    total_gmv = sum(_num(r.get("note_gmv")) for r in rows)

    gmv_rows = sorted(
        (r for r in rows if _num(r.get("note_gmv")) > 0),
        key=lambda r: _num(r.get("note_gmv")),
        reverse=True,
    )

    top_decile_gmv_share: float | None = None
    notes_for_80pct: int | None = None
    pareto_rows: list[dict] = []

    if gmv_rows and total_gmv > 0:
        decile_n = max(1, math.ceil(len(gmv_rows) * _TOP_DECILE_FRACTION))
        top_decile_gmv = sum(_num(r.get("note_gmv")) for r in gmv_rows[:decile_n])
        top_decile_gmv_share = top_decile_gmv / total_gmv

        target = total_gmv * _PARETO_TARGET_SHARE
        cum = 0.0
        count_80 = 0
        for r in gmv_rows:
            cum += _num(r.get("note_gmv"))
            count_80 += 1
            if cum >= target:
                break
        notes_for_80pct = count_80

        cum_share = 0.0
        for r in gmv_rows[:20]:
            gmv = _num(r.get("note_gmv"))
            cum_share += gmv
            pareto_rows.append(
                {
                    "note_id": _label(r, has_id, has_title),
                    "note_gmv": gmv,
                    "gmv_share": gmv / total_gmv,
                    "cum_share": cum_share / total_gmv,
                }
            )

    # One comparable concentration number beside the head-share Pareto.
    note_gmv_gini = gini([_num(r.get("note_gmv")) for r in gmv_rows])
    note_gmv_hhi = hhi([_num(r.get("note_gmv")) for r in gmv_rows])

    if gmv_rows and total_gmv > 0:
        gini_note = (
            f" GMV 基尼系数 {round(note_gmv_gini, 2)}（越高越集中于头部笔记）。"
            if note_gmv_gini is not None
            else ""
        )
        conclusion = (
            f"共 {qty(note_count)} 篇笔记（{qty(len(gmv_rows))} 篇有 GMV）；"
            f"Top 10% 笔记贡献 GMV {round((top_decile_gmv_share or 0) * 100)}%，"
            f"{qty(notes_for_80pct)} 篇笔记贡献 80% GMV。" + gini_note
        )
    else:
        conclusion = f"共 {qty(note_count)} 篇笔记，但无正 GMV 记录，无法计算集中度。"

    finding = Finding(
        title="GMV 集中度（帕累托）",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(note_count), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(int(note_count)),
        key_numbers={
            "note_count": note_count,
            "gmv_total": total_gmv,
            "top_decile_gmv_share": top_decile_gmv_share,
            "notes_for_80pct": notes_for_80pct,
            "note_gmv_gini": note_gmv_gini,
            "note_gmv_hhi": note_gmv_hhi,
        },
        caveats=[_OBS_CAVEAT, "帕累托集中度为快照统计，非因果归因。"],
        recommended_action=_LEVER_PARETO,
        evidence_reason="GMV 集中度=Top 10% 笔记 GMV / 总 GMV；80% 覆盖笔记数为累计 GMV 门槛。",
        confounders=list(_CONFOUNDERS),
    )
    return finding, pareto_rows


# --------------------------------------------------------------------------- #
# Finding 2 — 转化效率分布 (degrade-gated)
# --------------------------------------------------------------------------- #
def _conversion_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "notes")
    has_paid_col = "note_paid_orders" in cols or "note_paid_buyers" in cols
    if "reads" not in cols or not has_paid_col:
        limitations.append(
            "notes 缺少 reads 或 note_paid_orders/note_paid_buyers，跳过转化效率分布。"
        )
        return None, []

    rows = _fetch_all(con, "notes")
    has_id = "note_id" in cols
    has_title = "title" in cols
    use_orders = "note_paid_orders" in cols

    records: list[dict] = []
    for r in rows:
        reads = _num(r.get("reads"))
        paid = _num(r.get("note_paid_orders")) if use_orders else _num(r.get("note_paid_buyers"))
        conv = bounded_rate(paid / reads) if reads > 0 else None
        records.append(
            {
                "note_id": _label(r, has_id, has_title),
                "reads": reads,
                "paid": paid,
                "conversion": conv,
            }
        )

    valid = [r for r in records if r["conversion"] is not None]
    if not valid:
        limitations.append("notes 无有效 reads/成交数据，跳过转化效率分布。")
        return None, []

    # Note conversion is zero-inflated (most notes never convert), so the median
    # is 0 and any "below median" rule is degenerate. Disclose the converting
    # share and judge low performers against a positive, traffic-weighted baseline.
    notes_with_reads = [r for r in records if r["reads"] > 0]
    notes_with_orders = sum(1 for r in records if r["paid"] > 0)
    converting_share = (
        notes_with_orders / len(notes_with_reads) if notes_with_reads else None
    )
    total_reads = sum(r["reads"] for r in records)
    total_paid = sum(r["paid"] for r in records)
    baseline = (total_paid / total_reads) if total_reads > 0 else None

    quartile_n = max(1, math.ceil(len(records) * 0.25))
    top_reads_idx = sorted(
        range(len(records)), key=lambda i: records[i]["reads"], reverse=True
    )[:quartile_n]
    # High-traffic-low-conversion: among the top-read quartile, keep only notes
    # whose Wilson upper bound is confidently below the baseline (guards against
    # small-sample false alarms — a low-read note has a wide CI and won't flag).
    high_traffic_low_conv = []
    if baseline is not None:
        for i in top_reads_idx:
            r = records[i]
            if r["reads"] <= 0:
                continue
            _, hi = wilson_interval(r["paid"], r["reads"])
            if hi is not None and hi < baseline:
                high_traffic_low_conv.append(r)
    top_converters = sorted(valid, key=lambda r: r["conversion"], reverse=True)[:10]

    outlier_rows: list[dict] = []
    seen_ids = set()
    for r in high_traffic_low_conv:
        outlier_rows.append({**r, "outlier_type": "high_traffic_low_conv"})
        seen_ids.add(r["note_id"])
    for r in top_converters:
        if r["note_id"] in seen_ids:
            continue
        outlier_rows.append({**r, "outlier_type": "top_converter"})

    conclusion = (
        f"仅 {round((converting_share or 0) * 100)}% 有阅读笔记产生成交"
        f"（{qty(notes_with_orders)}/{qty(len(notes_with_reads))}）；"
        f"整体转化基线 {round((baseline or 0) * 100, 2)}%；"
        f"{qty(len(high_traffic_low_conv))} 篇高曝光低转化笔记（阅读前 25% 且转化 Wilson 上界低于基线）。"
    )
    finding = Finding(
        title="转化效率分布",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(valid), has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(len(valid)),
        key_numbers={
            "notes_with_orders": notes_with_orders,
            "notes_with_reads": len(notes_with_reads),
            "converting_share": converting_share,
            "baseline_conversion": baseline,
            "high_traffic_low_conv_count": len(high_traffic_low_conv),
        },
        caveats=[
            _OBS_CAVEAT,
            "笔记转化零膨胀（多数笔记无成交，中位数=0），故以正基线 Σ成交/Σ阅读 为判据。",
            "高曝光低转化=阅读前25%分位且转化率 Wilson 上界低于整体基线（守卫小样本）。",
        ],
        recommended_action=_LEVER_CONV if high_traffic_low_conv else None,
        evidence_reason=(
            "转化率=成交/阅读；基线=Σ成交/Σ阅读（加权正基线，规避零膨胀中位数）；"
            "高曝光低转化以阅读前25%分位 + Wilson 上界<基线判定。"
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, outlier_rows


# --------------------------------------------------------------------------- #
# Finding 3 — 笔记级退款异常 (degrade-gated)
# --------------------------------------------------------------------------- #
def _refund_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "notes")
    if "note_refund_rate_pay" not in cols or "note_paid_orders" not in cols:
        limitations.append("notes 缺少 note_refund_rate_pay/note_paid_orders，跳过笔记级退款异常。")
        return None, []

    rows = _fetch_all(con, "notes")
    has_id = "note_id" in cols
    has_title = "title" in cols
    has_refund_orders = "note_refund_orders_pay" in cols

    total_paid_orders = sum(_num(r.get("note_paid_orders")) for r in rows)
    if total_paid_orders <= 0:
        limitations.append("notes 无有效成交订单，跳过笔记级退款异常。")
        return None, []

    if has_refund_orders:
        total_refund_orders = sum(_num(r.get("note_refund_orders_pay")) for r in rows)
        baseline = total_refund_orders / total_paid_orders
    else:
        weighted_sum = sum(
            (bounded_rate(r.get("note_refund_rate_pay")) or 0.0) * _num(r.get("note_paid_orders"))
            for r in rows
        )
        baseline = weighted_sum / total_paid_orders

    high_refund_rows: list[dict] = []
    for r in rows:
        paid_orders = _num(r.get("note_paid_orders"))
        rate = bounded_rate(r.get("note_refund_rate_pay"))
        if rate is None:
            continue
        if paid_orders >= _MIN_PAID_ORDERS_FOR_REFUND_FLAG and rate > baseline:
            refund_orders = (
                _num(r.get("note_refund_orders_pay"))
                if has_refund_orders
                else rate * paid_orders
            )
            high_refund_rows.append(
                {
                    "note_id": _label(r, has_id, has_title),
                    "note_paid_orders": paid_orders,
                    "note_refund_orders_pay": refund_orders,
                    "note_refund_rate_pay": rate,
                    "baseline_refund_rate": baseline,
                }
            )

    # Scanning many notes for "rate > baseline" inflates false positives. Control
    # the family-wise false-discovery rate with Benjamini-Hochberg over one-sided
    # binomial p-values; only FDR survivors are treated as genuine outliers.
    pvals = [
        one_sided_binomial_p(r["note_refund_orders_pay"], r["note_paid_orders"], baseline)
        for r in high_refund_rows
    ]
    survived = benjamini_hochberg(pvals, alpha=0.05)
    for r, p, s in zip(high_refund_rows, pvals, survived):
        r["p_value"] = p
        r["fdr_significant"] = bool(s)
    fdr_survivors = sum(1 for s in survived if s)
    exp_false_positives = expected_false_positives(len(high_refund_rows), 0.05)
    high_refund_rows.sort(key=lambda r: r["note_refund_rate_pay"], reverse=True)

    conclusion = (
        f"笔记退款基线 {round(baseline * 100, 2)}%；"
        f"{qty(len(high_refund_rows))} 篇笔记退款率高于基线（成交 ≥ "
        f"{_MIN_PAID_ORDERS_FOR_REFUND_FLAG} 单守卫小样本），"
        f"其中 {qty(fdr_survivors)} 篇经 BH-FDR 5% 显著（预计假阳性约 {round(exp_false_positives, 1)} 个）。"
    )
    finding = Finding(
        title="笔记级退款异常",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_paid_orders), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(int(total_paid_orders)),
        key_numbers={
            "baseline_refund_rate": baseline,
            "high_refund_note_count": len(high_refund_rows),
            "fdr_survivors": fdr_survivors,
            "expected_false_positives": exp_false_positives,
        },
        caveats=[
            _OBS_CAVEAT,
            "退款率异常可能由品类/尺码/物流等因素驱动，需人工复核高退款笔记的商品与描述一致性。",
            "多重比较用 Benjamini-Hochberg FDR 控制假阳性；缺退款单列时退款单以率×成交单估计。",
        ],
        recommended_action=_LEVER_REFUND if high_refund_rows else None,
        evidence_reason=(
            "基线退款率=Σ退款单/Σ成交单（缺退款单列时按成交单加权均值兜底）；"
            "异常笔记以成交≥10单守卫小样本后与基线比较，再经 BH-FDR 控制多重比较假阳性。"
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, high_refund_rows


# --------------------------------------------------------------------------- #
# Finding 4 — 笔记站外引流成交 (degrade-gated)
# --------------------------------------------------------------------------- #
def _referral_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    """Surface GMV that notes drive *off the note* (to the shop main page or a
    live room) — a value stream the note_gmv/直接成交 caliber never counts.

    On this shop notes route a large payment volume to the shop main page that
    is invisible to the direct-attribution findings; leaving it out systematically
    understates content value and can mis-rank reshoot/ad decisions. The amount is
    reported as a *separate lens*, never summed with note_gmv (a purchase counted
    once under direct attribution must not be double-counted here).
    """
    cols = _table_columns(con, "notes")
    present = [c for c in _REFERRAL_CHANNELS if c[0] in cols or c[1] in cols]
    if not present:
        limitations.append(
            "notes 缺少 引流店铺主页/直播间 次数与支付金额列，跳过笔记站外引流成交。"
        )
        return None, []

    rows = _fetch_all(con, "notes")
    has_id = "note_id" in cols
    has_title = "title" in cols
    has_gmv = "note_gmv" in cols
    direct_gmv = sum(_num(r.get("note_gmv")) for r in rows) if has_gmv else None

    # Aggregate each present channel; keep only channels with positive GMV so a
    # structurally-absent channel (e.g. no livestream) is silently omitted.
    channel_totals: list[dict] = []
    for count_col, gmv_col, zh in present:
        gmv = sum(_num(r.get(gmv_col)) for r in rows)
        orders = sum(_num(r.get(count_col)) for r in rows)
        channel_totals.append(
            {"channel": zh, "gmv_col": gmv_col, "count_col": count_col,
             "referral_gmv": gmv, "referral_count": orders}
        )
    active = [c for c in channel_totals if c["referral_gmv"] > 0]
    total_referral = sum(c["referral_gmv"] for c in channel_totals)

    shop = next((c for c in channel_totals if c["channel"] == "店铺主页"), None)
    live = next((c for c in channel_totals if c["channel"] == "直播间"), None)
    shop_gmv = shop["referral_gmv"] if shop else 0.0
    live_gmv = live["referral_gmv"] if live else 0.0
    shop_share = (
        (shop_gmv / direct_gmv) if (has_gmv and direct_gmv and direct_gmv > 0) else None
    )

    # Rank notes by the dominant channel's referral GMV (店铺主页 if present, else
    # the first active channel) so the table names the notes worth crediting.
    rank_col = (shop or (active[0] if active else channel_totals[0]))["gmv_col"]
    count_col = (shop or (active[0] if active else channel_totals[0]))["count_col"]
    referral_rows = [
        {
            "note_id": _label(r, has_id, has_title),
            "referral_orders": _num(r.get(count_col)),
            "referral_gmv": _num(r.get(rank_col)),
            "note_gmv": _num(r.get("note_gmv")) if has_gmv else None,
        }
        for r in rows
        if _num(r.get(rank_col)) > 0
    ]
    referral_rows.sort(key=lambda r: r["referral_gmv"], reverse=True)

    if active:
        parts = "、".join(f"{c['channel']} {money(c['referral_gmv'])} 元" for c in active)
        share_part = (
            f"，其中店铺主页引流约为直接成交口径的 {round((shop_share or 0) * 100)}%"
            if shop_share is not None and shop_gmv > 0
            else ""
        )
        direct_part = f"直接成交 {money(direct_gmv)} 元之外，" if direct_gmv else ""
        conclusion = f"{direct_part}笔记另引流至{parts}{share_part}。"
        recommended_action = (
            _LEVER_REFERRAL if (shop_share is not None and shop_share >= 0.2) else None
        )
    else:
        conclusion = "笔记引流次数/金额列存在但合计为 0，未见站外引流成交。"
        recommended_action = None

    finding = Finding(
        title="笔记站外引流成交",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_referral), has_controls=False, confounder_count=1
        ),
        descriptive_reliability=score_reliability(int(total_referral)),
        key_numbers={
            "direct_note_gmv": direct_gmv,
            "shop_referral_gmv": shop_gmv,
            "shop_referral_share": shop_share,
            "shop_referral_orders": shop["referral_count"] if shop else None,
            "live_referral_gmv": live_gmv,
        },
        caveats=[
            _OBS_CAVEAT,
            "站外引流成交与笔记直接成交为两套归因口径，同一笔成交不重复计数，两者不相加。",
            "引流金额为后台归因快照，受店铺主页/直播间承接与活动节奏影响。",
        ],
        recommended_action=recommended_action,
        evidence_reason=(
            "汇总 notes 的 引流店铺主页/直播间 支付金额，与 note_gmv 直接口径并列展示；"
            "占比=店铺主页引流金额/直接成交 GMV，观察性描述。"
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, referral_rows


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _label(r: dict, has_id: bool, has_title: bool):
    if has_id and r.get("note_id") is not None:
        return r.get("note_id")
    if has_title and r.get("title") is not None:
        return r.get("title")
    return None


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
                title="笔记商业效能不可诊断",
                conclusion="需要导出 notes（笔记级商业数据）后才能诊断笔记级商业效能。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["笔记级商业数据缺失应视为导入缺口。"],
                recommended_action="导出商品笔记数据后重新构建。",
            )
        ],
        tables={"note_gmv_pareto": []},
        limitations=[reason],
    )
