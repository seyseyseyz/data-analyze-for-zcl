"""买家复购结构诊断 — buyer_repurchase_diagnosis.

买家去重、复购率、复购买家 GMV 占比、客单价对比与复购间隔分析。
观察性描述，never-raise 降级纪律，买家哈希做了截断保护。
"""

from datetime import datetime
from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence, score_reliability

TASK_ID = "buyer_repurchase_diagnosis"
TITLE = "买家复购结构诊断"

_COVERAGE_THRESHOLD = 0.5  # < 50% 覆盖时降级
_OBS_CAVEAT = M.causal_disclaimer("观察期不同买家群体的成熟度与留存机制差异")


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "orders"):
            return _missing_result("缺少 orders 表。")

        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        repurchase_finding, buyer_struct_rows, repeat_top_rows = _repurchase_diagnosis_finding(
            con, limitations
        )
        findings.append(repurchase_finding)
        if buyer_struct_rows:
            tables["buyer_structure"] = buyer_struct_rows
        if repeat_top_rows:
            tables["repeat_buyer_top"] = repeat_top_rows

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
# Finding — 买家复购结构
# --------------------------------------------------------------------------- #
def _repurchase_diagnosis_finding(
    con, limitations: list[str]
) -> tuple[Finding, list[dict], list[dict]]:
    cols = _table_columns(con, "orders")

    # 检查必需列
    if "buyer_id_hash" not in cols:
        return _not_judgable_finding("buyer_id_hash 列缺失或全空，无法追踪买家复购。"), [], []

    if "paid_time" not in cols or "paid_amount" not in cols:
        return _not_judgable_finding(
            "orders 缺少 paid_time/paid_amount 列，无法计算复购间隔与 GMV。"
        ), [], []

    rows = _fetch_all(con, "orders")

    # 检查 buyer_id_hash 覆盖率
    orders_with_hash = sum(1 for r in rows if r.get("buyer_id_hash") is not None)
    total_orders = len(rows)
    coverage = orders_with_hash / total_orders if total_orders > 0 else 0.0

    if orders_with_hash == 0:
        return _not_judgable_finding(
            "orders 中 buyer_id_hash 全为空，无法去重买家。"
        ), [], []

    # 筛选有 buyer_id_hash 的订单
    orders_with_hash_list = [r for r in rows if r.get("buyer_id_hash") is not None]

    # 去重买家：按 buyer_id_hash 分组
    buyers: dict[str, list[dict]] = {}
    for r in orders_with_hash_list:
        buyer_id = r.get("buyer_id_hash")
        if buyer_id not in buyers:
            buyers[buyer_id] = []
        buyers[buyer_id].append(r)

    unique_buyers = len(buyers)

    # 分类：单次 vs 复购
    single_buyers = [b for b, orders in buyers.items() if len(orders) == 1]
    repeat_buyers = [b for b, orders in buyers.items() if len(orders) >= 2]

    repeat_buyer_count = len(repeat_buyers)
    repurchase_rate = repeat_buyer_count / unique_buyers if unique_buyers > 0 else None

    # 计算 GMV 和订单数
    single_buyer_gmv = sum(
        _num(r.get("paid_amount"))
        for b in single_buyers
        for r in buyers.get(b, [])
    )
    single_buyer_orders = len(single_buyers)

    repeat_buyer_gmv = sum(
        _num(r.get("paid_amount"))
        for b in repeat_buyers
        for r in buyers.get(b, [])
    )
    repeat_buyer_orders = sum(len(buyers.get(b, [])) for b in repeat_buyers)

    total_gmv = single_buyer_gmv + repeat_buyer_gmv
    repeat_buyer_gmv_share = repeat_buyer_gmv / total_gmv if total_gmv > 0 else None

    # 平均客单价
    avg_aov_single = single_buyer_gmv / single_buyer_orders if single_buyer_orders > 0 else None
    avg_aov_repeat_per_order = (
        repeat_buyer_gmv / repeat_buyer_orders if repeat_buyer_orders > 0 else None
    )
    avg_aov_repeat_per_buyer = (
        repeat_buyer_gmv / repeat_buyer_count if repeat_buyer_count > 0 else None
    )

    # 复购间隔计算
    median_interval_days = None
    avg_interval_days = None
    intervals = []

    for buyer_id in repeat_buyers:
        buyer_orders = buyers.get(buyer_id, [])
        # 按支付时间排序
        try:
            sorted_orders = sorted(
                buyer_orders,
                key=lambda r: _parse_datetime(r.get("paid_time")) or datetime.max,
            )
            if len(sorted_orders) >= 2:
                for i in range(len(sorted_orders) - 1):
                    t1 = _parse_datetime(sorted_orders[i].get("paid_time"))
                    t2 = _parse_datetime(sorted_orders[i + 1].get("paid_time"))
                    if t1 and t2:
                        delta_days = (t2 - t1).days
                        if delta_days >= 0:
                            intervals.append(delta_days)
        except Exception:
            pass

    if intervals:
        intervals.sort()
        median_interval_days = float(intervals[len(intervals) // 2])
        avg_interval_days = sum(intervals) / len(intervals)

    # 结论
    conclusion = (
        f"去重买家 {qty(unique_buyers)} 个（覆盖率 {round(coverage * 100, 1)}%）；"
        f"复购买家 {qty(repeat_buyer_count)} 个，复购率 {round((repurchase_rate or 0) * 100, 1)}%；"
        f"复购买家 GMV 占比 {round((repeat_buyer_gmv_share or 0) * 100, 1)}%；"
        f"单次买家平均客单 {money(avg_aov_single)}，复购买家平均客单 {money(avg_aov_repeat_per_buyer)}"
    )

    if median_interval_days is not None:
        conclusion += f"；复购间隔中位数 {round(median_interval_days)} 天"

    # 构建 caveats
    caveats = [
        _OBS_CAVEAT,
        "观察窗截断：窗口末期首购的买家可能没机会复购，期内复购率是下限估计。",
    ]

    if coverage < _COVERAGE_THRESHOLD:
        caveats.append(
            f"buyer_id_hash 覆盖率仅 {round(coverage * 100, 1)}%（<50%），"
            "部分订单无法追踪买家，复购数据不完整。"
        )

    # key_numbers
    key_numbers = {
        "unique_buyers": unique_buyers,
        "repeat_buyers": repeat_buyer_count,
        "repurchase_rate": repurchase_rate,
        "buyer_hash_coverage": coverage,
        "total_gmv": total_gmv,
        "repeat_buyers_gmv_share": repeat_buyer_gmv_share,
        "avg_aov_single_buyer": avg_aov_single,
        "avg_aov_repeat_buyer": avg_aov_repeat_per_buyer,
        "median_repurchase_interval_days": median_interval_days,
        "avg_repurchase_interval_days": avg_interval_days,
    }

    # 确定 evidence_strength
    evidence_strength = score_evidence(unique_buyers, has_controls=False, confounder_count=1)
    if coverage < _COVERAGE_THRESHOLD:
        # 覆盖率低时降级为 WEAK
        if evidence_strength.value != "not_judgable":
            evidence_strength = EvidenceStrength.WEAK

    # 构建 buyer_structure 表
    buyer_struct_rows = []
    if single_buyers or repeat_buyers:
        if single_buyers:
            buyer_struct_rows.append({
                "buyer_type": "单次购买",
                "buyer_count": len(single_buyers),
                "order_count": len(single_buyers),
                "gmv": single_buyer_gmv,
                "avg_aov": avg_aov_single,
            })
        if repeat_buyers:
            buyer_struct_rows.append({
                "buyer_type": "复购",
                "buyer_count": len(repeat_buyers),
                "order_count": repeat_buyer_orders,
                "gmv": repeat_buyer_gmv,
                "avg_aov": avg_aov_repeat_per_order,
            })

    # 构建 repeat_buyer_top 表（Top 10 复购买家，按 GMV 降序）
    repeat_buyer_gmv_list = [
        {
            "buyer_id_hash": _truncate_hash(buyer_id),
            "order_count": len(buyers.get(buyer_id, [])),
            "gmv": sum(_num(r.get("paid_amount")) for r in buyers.get(buyer_id, [])),
        }
        for buyer_id in repeat_buyers
    ]
    repeat_buyer_gmv_list.sort(key=lambda x: x["gmv"], reverse=True)
    repeat_buyer_top = repeat_buyer_gmv_list[:10]

    finding = Finding(
        title="买家复购结构诊断",
        conclusion=conclusion,
        evidence_strength=evidence_strength,
        descriptive_reliability=score_reliability(unique_buyers),
        key_numbers=key_numbers,
        caveats=caveats,
        evidence_reason=M.methodology_note(
            "复购率 = 复购买家数 / 去重买家数（≥2 单）；"
            "复购间隔 = 同一买家相邻订单支付时间差；"
            "覆盖率 < 50% 时证据强度降级为 LOW。",
        ),
        confounders=["买家成熟度与留存机制", "观察期长度", "活动与促销强度"],
    )

    return finding, buyer_struct_rows, repeat_buyer_top


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _num(value) -> float:
    """安全转换为有限数值，缺失时返回 0.0."""
    return to_finite_float(value, 0.0)


def _truncate_hash(hash_str: str, max_len: int = 8) -> str:
    """截断哈希字符串到 max_len 字符 + "…"（防止泄露原始哈希）."""
    if not hash_str or len(hash_str) <= max_len:
        return hash_str
    return hash_str[:max_len] + "…"


def _parse_datetime(value) -> datetime | None:
    """尝试解析时间戳."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        # 尝试常见格式
        for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"]:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                pass
    return None


def _fetch_all(con, table: str) -> list[dict]:
    """获取表的所有行."""
    rel = con.sql(f"SELECT * FROM {table}")
    columns = rel.columns
    return [dict(zip(columns, row)) for row in rel.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    """检查表是否存在."""
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    """获取表的列名集合."""
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}


def _missing_result(reason: str) -> AnalysisResult:
    """表缺失时返回 NOT_JUDGABLE."""
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=[
            Finding(
                title="买家复购结构不可诊断",
                conclusion="需要导出 orders（订单级数据）后才能诊断买家复购结构。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["订单级数据缺失应视为导入缺口。"],
                recommended_action="导出订单数据后重新构建。",
            )
        ],
        tables={"buyer_structure": [], "repeat_buyer_top": []},
        limitations=[reason],
    )


def _not_judgable_finding(reason: str) -> Finding:
    """返回 NOT_JUDGABLE Finding."""
    return Finding(
        title="买家复购结构不可诊断",
        conclusion=f"无法诊断买家复购结构：{reason}",
        evidence_strength=EvidenceStrength.NOT_JUDGABLE,
        key_numbers={},
        caveats=[reason],
        recommended_action="检查导出数据中是否包含 buyer_id_hash、paid_time、paid_amount 等必需字段。",
    )
