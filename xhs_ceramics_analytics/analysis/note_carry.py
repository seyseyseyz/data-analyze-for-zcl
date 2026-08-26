"""笔记承接效率诊断 — note_carry_efficiency.

笔记通过进店与直播间的承接效率：进店次数、进店支付、直播间次数、
直播间支付，以及承接率与平均支付金额。观察性描述，never-raise 降级纪律。
"""

from pathlib import Path

from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.analysis import methodology as M
from xhs_ceramics_analytics.analysis.prose import money, qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import bounded_rate
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence, score_reliability

TASK_ID = "note_carry_efficiency"
TITLE = "笔记承接效率（进店与直播）"

# 笔记承接去向：每条 = (次数列, 支付金额列, 中文渠道名)。
# 缺列即跳过该渠道。
_CARRY_CHANNELS = (
    ("to_shop_home_count", "to_shop_home_gmv", "进店"),
    ("to_live_count", "to_live_gmv", "直播间"),
)

_OBS_CAVEAT = M.causal_disclaimer("笔记之间的曝光结构、承接页面与引流策略不同")


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "notes"):
            return _missing_result("缺少 notes 表。")

        cols = _table_columns(con, "notes")
        # 检查是否有任何承接字段
        has_carry = any(c[0] in cols or c[1] in cols for c in _CARRY_CHANNELS)
        if not has_carry:
            return _not_judgable_result(
                "notes 缺少进店/直播承接字段（to_shop_home_count/gmv 或 to_live_count/gmv），"
                "无法诊断笔记承接效率。"
            )

        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        carry_finding, carry_rows = _carry_efficiency_finding(con, limitations)
        findings.append(carry_finding)
        tables["note_carry"] = carry_rows

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
# Finding — 笔记承接效率汇总与明细
# --------------------------------------------------------------------------- #
def _carry_efficiency_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "notes")
    rows = _fetch_all(con, "notes")

    has_id = "note_id" in cols
    has_title = "title" in cols
    has_reads = "reads" in cols
    has_impressions = "impressions" in cols

    # 检查是否需要用 impressions fallback
    used_impressions_for_carry_rate = False
    if has_reads and has_impressions:
        reads_total = sum(_num(r.get("reads")) for r in rows)
        if reads_total == 0 and sum(_num(r.get("impressions")) for r in rows) > 0:
            used_impressions_for_carry_rate = True

    # 为每个渠道计算汇总与明细
    channel_data = {}
    for count_col, gmv_col, zh in _CARRY_CHANNELS:
        has_count = count_col in cols
        has_gmv = gmv_col in cols

        if not has_count or not has_gmv:
            # 渠道列缺失，跳过
            channel_data[zh] = {
                "total_count": 0.0,
                "total_gmv": 0.0,
                "carry_rate": None,
                "avg_payment": None,
                "missing": True,
            }
            continue

        total_count = sum(_num(r.get(count_col)) for r in rows)
        total_gmv = sum(_num(r.get(gmv_col)) for r in rows)

        # 计算承接率
        carry_rate = None
        if has_reads and has_impressions:
            # 优先用 reads，缺则用 impressions
            reads_total = sum(_num(r.get("reads")) for r in rows)
            if reads_total == 0:
                impressions_total = sum(_num(r.get("impressions")) for r in rows)
                if impressions_total > 0:
                    carry_rate = bounded_rate(total_count / impressions_total)
            else:
                carry_rate = bounded_rate(total_count / reads_total)
        elif has_reads:
            reads_total = sum(_num(r.get("reads")) for r in rows)
            if reads_total > 0:
                carry_rate = bounded_rate(total_count / reads_total)
        elif has_impressions:
            impressions_total = sum(_num(r.get("impressions")) for r in rows)
            if impressions_total > 0:
                carry_rate = bounded_rate(total_count / impressions_total)

        # 平均支付（只在计数 > 0 时计算）
        avg_payment = None
        if total_count > 0 and total_gmv > 0:
            avg_payment = total_gmv / total_count

        channel_data[zh] = {
            "total_count": total_count,
            "total_gmv": total_gmv,
            "carry_rate": carry_rate,
            "avg_payment": avg_payment,
            "missing": False,
        }

    # 生成 key_numbers
    key_numbers = {
        "total_shop_home_count": channel_data.get("进店", {}).get("total_count", 0.0),
        "total_shop_home_gmv": channel_data.get("进店", {}).get("total_gmv", 0.0),
        "shop_home_carry_rate": channel_data.get("进店", {}).get("carry_rate"),
        "avg_shop_home_payment": channel_data.get("进店", {}).get("avg_payment"),
        "total_live_count": channel_data.get("直播间", {}).get("total_count", 0.0),
        "total_live_gmv": channel_data.get("直播间", {}).get("total_gmv", 0.0),
        "live_carry_rate": channel_data.get("直播间", {}).get("carry_rate"),
        "avg_live_payment": channel_data.get("直播间", {}).get("avg_payment"),
    }

    # 结论
    conclusion_parts = []
    missing_channels = []
    for zh in ["进店", "直播间"]:
        data = channel_data.get(zh, {})
        if data.get("missing"):
            conclusion_parts.append(f"{zh}：数据缺失")
            missing_channels.append(zh)
            limitations.append(f"notes 缺少 {zh}承接字段，无法计算 {zh}相关指标。")
        else:
            count = data["total_count"]
            gmv = data["total_gmv"]
            rate = data["carry_rate"]
            avg_pay = data["avg_payment"]

            rate_str = f"{round((rate or 0) * 100, 2)}%" if rate is not None else "数据不足"
            avg_pay_str = f"{money(avg_pay)}" if avg_pay is not None else "无"

            conclusion_parts.append(
                f"{zh}：{qty(count)} 次，{money(gmv)}（承接率 {rate_str}，平均 {avg_pay_str}/次）"
            )

    conclusion = "；".join(conclusion_parts) if conclusion_parts else "数据不足，无法诊断承接效率。"

    # 构建 caveats
    caveats = [_OBS_CAVEAT, "承接率 = 承接次数 / 曝光或阅读（缺阅读则用曝光）；平均支付 = 承接支付 / 承接次数。"]

    # 缺 reads/impressions 时加 caveat
    if not has_reads and not has_impressions:
        caveats.append("notes 缺少 reads/impressions，无法计算承接率。")
    elif not has_reads and has_impressions:
        caveats.append("notes 缺少 reads，用 impressions 计算承接率。")
    elif used_impressions_for_carry_rate:
        caveats.append("阅读数全为空或 0，承接率改用 impressions 计算。")

    # 缺某渠道字段时加 caveat
    if missing_channels:
        caveats.append(f"缺少 {'/'.join(missing_channels)} 承接数据。")

    # 生成明细表：Top 20，按 (to_shop_home_gmv + to_live_gmv) 降序
    shop_col = "to_shop_home_gmv" if "to_shop_home_gmv" in cols else None
    live_col = "to_live_gmv" if "to_live_gmv" in cols else None

    detail_rows = []
    for r in rows:
        shop_gmv = _num(r.get(shop_col)) if shop_col else 0.0
        live_gmv = _num(r.get(live_col)) if live_col else 0.0
        total_gmv = shop_gmv + live_gmv

        if total_gmv > 0:  # 只记录有 GMV 的笔记
            detail_rows.append({
                "note_id": r.get("note_id") if has_id else None,
                "note_title": _label(r, has_id, has_title),
                "impressions": _num(r.get("impressions")) if has_impressions else None,
                "reads": _num(r.get("reads")) if has_reads else None,
                "to_shop_home_count": _num(r.get("to_shop_home_count"))
                if "to_shop_home_count" in cols
                else None,
                "to_shop_home_gmv": shop_gmv,
                "to_live_count": _num(r.get("to_live_count"))
                if "to_live_count" in cols
                else None,
                "to_live_gmv": live_gmv,
                "_sort_key": total_gmv,
            })

    # 按 _sort_key 降序，取 Top 20
    detail_rows.sort(key=lambda x: x["_sort_key"], reverse=True)
    carry_rows = [
        {k: v for k, v in r.items() if k != "_sort_key"} for r in detail_rows[:20]
    ]

    # 计算样本量（用于 evidence 评分）
    sample_n = len(rows)

    finding = Finding(
        title="笔记承接效率（进店与直播）",
        conclusion=conclusion,
        evidence_strength=score_evidence(sample_n, has_controls=False, confounder_count=1),
        descriptive_reliability=score_reliability(sample_n),
        key_numbers=key_numbers,
        caveats=caveats,
        evidence_reason=M.methodology_note(
            "笔记承接效率 = 进店/直播次数与支付金额汇总，以及承接率与平均支付。",
        ),
        confounders=["笔记曝光结构差异", "店铺主页承接与直播间体验差异", "内容类型与渠道匹配"],
    )
    return finding, carry_rows


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #


def _label(r: dict, has_id: bool, has_title: bool):
    """优先返回人类可读的 title，缺则用 note_id，均缺则返回 None."""
    if has_title and r.get("title") is not None:
        return r.get("title")
    if has_id and r.get("note_id") is not None:
        return r.get("note_id")
    return None


def _num(value) -> float:
    """安全转换为有限数值，缺失时返回 0.0."""
    return to_finite_float(value, 0.0)


def _fetch_all(con, table: str) -> list[dict]:
    """获取表的所有行。"""
    rel = con.sql(f"SELECT * FROM {table}")
    columns = rel.columns
    return [dict(zip(columns, row)) for row in rel.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    """检查表是否存在。"""
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    """获取表的列名集合。"""
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}


def _missing_result(reason: str) -> AnalysisResult:
    """表缺失时返回 NOT_JUDGABLE."""
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=[
            Finding(
                title="笔记承接效率不可诊断",
                conclusion="需要导出 notes（笔记级数据）后才能诊断笔记承接效率。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["笔记级数据缺失应视为导入缺口。"],
                recommended_action="导出商品笔记数据后重新构建。",
            )
        ],
        tables={"note_carry": []},
        limitations=[reason],
    )


def _not_judgable_result(reason: str) -> AnalysisResult:
    """承接字段全缺时返回 NOT_JUDGABLE."""
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=[
            Finding(
                title="笔记承接效率不可诊断",
                conclusion="千帆笔记导出缺少进店/直播承接字段，无法诊断笔记承接效率。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=[reason],
                recommended_action="检查千帆导出是否包含进店次数、进店支付、进直播间次数、进直播间支付等字段。",
            )
        ],
        tables={"note_carry": []},
        limitations=[reason],
    )
