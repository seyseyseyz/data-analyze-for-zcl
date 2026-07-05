"""面向商家的单一「置信度」——呈现层唯一来源。

因果强度 (:class:`EvidenceStrength`) 恒受"有无对照组"限制,单窗口店铺数据永远最多
WEAK;把它当主标签会让每条结论都显示"低",并把大样本方向图打成坏图。这个原语改以
**描述可靠性** (:class:`DescriptiveReliability`,样本量/置信区间) 为主轴——它回答
"这个数字作为对本期的描述有多精确",大样本、窄区间的观察性事实理应"高"。因果口径降级
为一句 ``causal_caveat`` 脚注。纯函数,never-raise。

md / html / charts / priority 都从这里取置信度,保证同一条结论在各处措辞一致。
"""
from typing import NamedTuple

from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength


class ReaderConfidence(NamedTuple):
    level: str  # high / medium / low / not_judgable
    label: str  # 高 / 中 / 低 / 暂不下定论
    help: str
    de_emphasize: bool  # 图表/卡片是否降调呈现
    causal_caveat: str | None


_LABELS = {"high": "高", "medium": "中", "low": "低", "not_judgable": "暂不下定论"}
_HELP = {
    "high": "样本量大、口径清晰,可以直接作为本期经营依据。",
    "medium": "可以用于本周决策,建议持续观察。",
    "low": "样本偏小或区间较宽,先当参考方向,不宜直接下定论。",
    "not_judgable": "当前数据不足,需要先补齐导入或埋点。",
}
_CAUSAL_CAVEAT = "这是对已发生数据的描述,尚无对照组,不能据此断定因果。"

# 描述可靠性 → 面向商家的置信度等级。NOT_APPLICABLE 表示"没有可量化估计",回退到因果轴。
_RELIABILITY_TO_LEVEL: dict[DescriptiveReliability, str | None] = {
    DescriptiveReliability.HIGH: "high",
    DescriptiveReliability.MEDIUM: "medium",
    DescriptiveReliability.LOW: "low",
    DescriptiveReliability.NOT_APPLICABLE: None,
}
# 无描述精度时的软化因果映射:不再让观察性数据恒为低。
_EVIDENCE_FALLBACK: dict[EvidenceStrength, str] = {
    EvidenceStrength.STRONG: "high",
    EvidenceStrength.MEDIUM: "medium",
    EvidenceStrength.WEAK: "low",
    EvidenceStrength.NOT_JUDGABLE: "not_judgable",
}


def reader_confidence(finding: Finding) -> ReaderConfidence:
    """把一条 finding 的双证据轴折成单一、面向商家的置信度。Never-raise。"""
    if finding.evidence_strength is EvidenceStrength.NOT_JUDGABLE:
        level = "not_judgable"
    else:
        level: str | None = None
        reliability = finding.descriptive_reliability
        if reliability is not None:
            level = _RELIABILITY_TO_LEVEL.get(reliability)
        if level is None:
            level = _EVIDENCE_FALLBACK.get(finding.evidence_strength, "low")

    caveat = None if level == "not_judgable" else _CAUSAL_CAVEAT
    return ReaderConfidence(
        level=level,
        label=_LABELS[level],
        help=_HELP[level],
        de_emphasize=level in ("low", "not_judgable"),
        causal_caveat=caveat,
    )


# Fallback for result-level contexts with no scored finding (empty modules).
NOT_JUDGABLE = ReaderConfidence(
    level="not_judgable",
    label=_LABELS["not_judgable"],
    help=_HELP["not_judgable"],
    de_emphasize=True,
    causal_caveat=None,
)

# Ordered levels for distribution summaries (best → worst).
LEVELS: tuple[str, ...] = ("high", "medium", "low", "not_judgable")
LEVEL_LABELS = dict(_LABELS)
LEVEL_HELP = dict(_HELP)
