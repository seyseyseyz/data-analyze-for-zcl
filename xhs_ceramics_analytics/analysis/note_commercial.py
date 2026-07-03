"""笔记级商业效能诊断 — note_commercial_diagnosis.

Sibling of ``audience_structure``: same module contract, shared stat helpers,
never-raise degradation discipline. Observational only — no causal attribution.
Every finding is gated on real columns via ``_table_columns`` (read_csv_auto
builds may omit any of them) and every division is guarded.
"""
import math
import statistics
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import bounded_rate
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

TASK_ID = "note_commercial_diagnosis"
TITLE = "笔记级商业效能诊断"

_MIN_PAID_ORDERS_FOR_REFUND_FLAG = 10
_PARETO_TARGET_SHARE = 0.8
_TOP_DECILE_FRACTION = 0.1

_CONFOUNDERS = ["笔记曝光结构差异", "商品与内容混合", "发布时间与活动节奏"]

_LEVER_PARETO = "头部依赖高：复制头部笔记选题/形式并测试腰部放量。"
_LEVER_CONV = "高曝光低转化笔记优化封面/标题与商详承接，或缩量测试新选题。"
_LEVER_REFUND = "对高退款笔记复核商品描述与预期一致性，必要时下线关联链接。"

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

    if gmv_rows and total_gmv > 0:
        conclusion = (
            f"共 {note_count} 篇笔记（{len(gmv_rows)} 篇有 GMV）；"
            f"Top 10% 笔记贡献 GMV {round((top_decile_gmv_share or 0) * 100)}%，"
            f"{notes_for_80pct} 篇笔记贡献 80% GMV。"
        )
    else:
        conclusion = f"共 {note_count} 篇笔记，但无正 GMV 记录，无法计算集中度。"

    finding = Finding(
        title="GMV 集中度（帕累托）",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(note_count), has_controls=False, confounder_count=1),
        key_numbers={
            "note_count": note_count,
            "gmv_total": total_gmv,
            "top_decile_gmv_share": top_decile_gmv_share,
            "notes_for_80pct": notes_for_80pct,
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

    median_conv = statistics.median(r["conversion"] for r in valid)

    quartile_n = max(1, math.ceil(len(records) * 0.25))
    top_reads_idx = sorted(
        range(len(records)), key=lambda i: records[i]["reads"], reverse=True
    )[:quartile_n]
    high_traffic_low_conv = [
        records[i]
        for i in top_reads_idx
        if records[i]["conversion"] is not None and records[i]["conversion"] < median_conv
    ]
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
        f"笔记转化中位数 {round(median_conv * 100, 2)}%；"
        f"{len(high_traffic_low_conv)} 篇高曝光低转化笔记（阅读前 25% 分位但转化低于中位数）。"
    )
    finding = Finding(
        title="转化效率分布",
        conclusion=conclusion,
        evidence_strength=score_evidence(len(valid), has_controls=False, confounder_count=1),
        key_numbers={
            "median_conversion": median_conv,
            "high_traffic_low_conv_count": len(high_traffic_low_conv),
        },
        caveats=[_OBS_CAVEAT, "转化=成交/阅读（bounded_rate 归一），高曝光低转化以阅读前25%分位判定。"],
        recommended_action=_LEVER_CONV if high_traffic_low_conv else None,
        evidence_reason="转化率=成交/阅读；高曝光低转化=阅读前25%分位且转化低于全量中位数。",
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
            high_refund_rows.append(
                {
                    "note_id": _label(r, has_id, has_title),
                    "note_paid_orders": paid_orders,
                    "note_refund_rate_pay": rate,
                    "baseline_refund_rate": baseline,
                }
            )
    high_refund_rows.sort(key=lambda r: r["note_refund_rate_pay"], reverse=True)

    conclusion = (
        f"笔记退款基线 {round(baseline * 100, 2)}%；"
        f"{len(high_refund_rows)} 篇笔记退款率高于基线（成交 ≥ "
        f"{_MIN_PAID_ORDERS_FOR_REFUND_FLAG} 单守卫小样本）。"
    )
    finding = Finding(
        title="笔记级退款异常",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_paid_orders), has_controls=False, confounder_count=1
        ),
        key_numbers={
            "baseline_refund_rate": baseline,
            "high_refund_note_count": len(high_refund_rows),
        },
        caveats=[
            _OBS_CAVEAT,
            "退款率异常可能由品类/尺码/物流等因素驱动，需人工复核高退款笔记的商品与描述一致性。",
        ],
        recommended_action=_LEVER_REFUND if high_refund_rows else None,
        evidence_reason=(
            "基线退款率=Σ退款单/Σ成交单（缺退款单列时按成交单加权均值兜底）；"
            "异常笔记以成交≥10单守卫小样本后与基线比较。"
        ),
        confounders=list(_CONFOUNDERS),
    )
    return finding, high_refund_rows


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
