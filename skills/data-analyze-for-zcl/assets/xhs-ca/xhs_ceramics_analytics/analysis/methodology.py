"""方法学措辞的集中来源 —— 病根 C 的设计源头。

契约:``Finding.conclusion`` 与 ``Finding.caveats`` 只放**商家能懂的经营语言**;一切
带统计术语的方法学句子(显著性、去趋势、残差、多变点、最小二乘斜率、z 检验、BH-FDR、
LMDI、Wilson 区间、赫芬达尔/基尼、分位、效应量、"观察性")一律进 ``appendix`` /
``evidence_reason`` —— 由 :func:`combined_methodology` 汇到报告的"方法与附录"折叠区。

这里把跨模块**重复**的两类文本收成共享原语:
- :func:`causal_disclaimer` —— 人话版"别当因果"提醒,供 ``caveats``(不含术语);
- ``METHOD_*`` 常量 + :func:`methodology_note` —— 方法学附录句(可含术语),供 appendix。

纯函数,never-raise。
"""
from xhs_ceramics_analytics.analysis.result import Finding


def causal_disclaimer(alt_drivers: str) -> str:
    """人话版"别当因果"提醒,进 ``caveats``。

    ``alt_drivers`` 用商家词描述可能的其他原因(如"流量结构和选品不同"),不含统计术语。
    """
    return f"这不是因果关系:{alt_drivers}也会影响，先当方向线索、别急着归因。"


# —— 方法学附录句:可含统计术语,只进 appendix / evidence_reason ——
METHOD_PROPORTION_TEST = (
    "组间差异用两样本比例 z 检验,并要求效应量超过最小门槛后才判定为真实差异,仅作比较、非因果。"
)
METHOD_TREND_SLOPE = (
    "趋势方向按逐期数值的最小二乘斜率判定(非首末两点),未对趋势另做显著性检验。"
)
METHOD_FDR = "多类同时比较时用 BH-FDR 控制预计假阳性数,避免小样本误报,非逐类因果证明。"
METHOD_WILSON = "小样本比率用 Wilson 置信区间守卫(取区间边界而非点估计),避免个别样本误报。"
METHOD_OBSERVATIONAL = "以上为观察性聚合描述,反映方向与规模,非因果推断。"


def methodology_note(*parts: str | None) -> str:
    """把若干方法学句子拼成一段 appendix 文本,自动去空、去重(保序)。"""
    seen: list[str] = []
    for part in parts:
        text = (part or "").strip()
        if text and text not in seen:
            seen.append(text)
    return " ".join(seen)


def combined_methodology(finding: Finding) -> str | None:
    """报告渲染层调用:把 finding 的 ``appendix`` 与 ``evidence_reason`` 合成一段方法学附录。

    两者都属于"方法与附录"折叠区的内容 —— appendix 是显式附录,evidence_reason 是
    证据/口径说明。合并后读者在一处看到完整方法学,主卡片保持干净。
    """
    text = methodology_note(finding.appendix, finding.evidence_reason)
    return text or None
