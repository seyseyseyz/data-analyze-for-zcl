from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    min_n_guard,
    rate_band,
    two_proportion,
    wilson_interval,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

TASK_ID = "refund_structure_diagnosis"
TITLE = "退款结构诊断"

_LAYER_COLUMNS = {
    "pre_ship": "pre_ship_refund_amount",
    "post_ship": "post_ship_refund_amount",
    "return": "return_refund_amount",
}
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
    layer_rows: list[dict] = []
    total = sum(_num(r.get("refund_amount_pay")) for r in rows)
    for layer, col in present.items():
        amount = sum(_num(r.get(col)) for r in rows)
        share = amount / total if total else None
        layer_rows.append({"layer": layer, "refund_amount": amount, "share": share})
    for missing in _LAYER_COLUMNS.keys() - present.keys():
        limitations.append(f"refund_overview 缺少 {_LAYER_COLUMNS[missing]}，跳过 {missing} 层。")

    dominant = max(layer_rows, key=lambda r: r["refund_amount"], default=None)
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
        f"总退款 {round(total)} 元中，占比最高的是 {_layer_zh(dominant_layer)}"
        f"（{round((dominant['share'] or 0) * 100)}%）。"
        if dominant
        else "退款金额层级列缺失，无法拆解。"
    )
    caveats = ["观察性拆解，非因果；层级份额基于聚合快照。"]
    if lo is not None:
        caveats.append(f"整体退款率 {rate_band(lo, hi)}（样本 n≈{round(n)}）。")
    finding = Finding(
        title="退款主漏点层级",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(n), has_controls=False, confounder_count=1),
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
        evidence_reason="退款率为观察性比例，样本量以退款订单/退款率反推支付订单基数估计。",
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
        key_numbers={
            "carrier_high": a["carrier"],
            "diff": test["diff"],
            "significant": test["significant"],
            "ci_overlap": test["ci_overlap"],
        },
        caveats=[
            "观察性对比，非因果；样本量以退款订单/退款率反推。",
            "显著性用两样本比例 z 检验，辅以 Wilson 区间重叠判断。",
        ],
        evidence_reason="载体间退款率差异用两样本比例检验，观察性。",
        confounders=["载体流量结构", "客群差异"],
    )
    return finding, by_carrier


def _layer_zh(layer: str | None) -> str:
    return {"pre_ship": "发货前退款", "post_ship": "发货后退款", "return": "退货退款"}.get(
        layer, "未知层级"
    )


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
