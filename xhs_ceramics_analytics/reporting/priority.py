"""跨模块「最弱环节 × 最高杠杆」优先级表 (D2).

Each analysis module answers "what's wrong here"; the reader then has to hold a
dozen modules in their head to decide what to fix *first*. This primitive collapses
that judgement into one cross-module ranking so the answer is visible on a single
page.

Priority = 预期影响 × 可行性:

- 预期影响 (impact) — a curated per-module business-lever weight (:data:`LEVER_WEIGHTS`).
  It encodes the same editorial judgement as the report's section grouping: core
  economics / refund / search move the needle most; baseline/funnel are context.
- 可行性 (feasibility) — how confidently the finding can be acted on *now*, derived
  from its two evidence axes: causal :class:`EvidenceStrength` (weighted higher) and
  descriptive :class:`DescriptiveReliability`. A strong, well-measured finding is
  safe to act on; a weak, thinly-measured one is a hypothesis, not a lever.

Only actionable findings qualify — a module must carry a ``recommended_action`` and
clear ``not_judgable`` evidence, otherwise there is no lever to pull. Appendix
(data-quality) modules are excluded: they back conclusions, they are not levers.
Pure and never-raise; degrades to ``[]`` when nothing is actionable.
"""
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.confidence import reader_confidence
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS

# 预期影响: curated per-module lever weight in [0, 1]. Same spirit as the report's
# section order — 经营/退款/搜索 lead, 商品/内容 follow, 参考模块 trail. Unlisted
# modules fall back to _DEFAULT_WEIGHT so a new module still ranks sensibly.
LEVER_WEIGHTS: dict[str, float] = {
    # 经营诊断：生意怎么样
    "core_business_diagnosis": 1.0,
    "refund_root_cause_diagnosis": 0.95,
    "refund_structure_diagnosis": 0.9,
    "search_efficiency_diagnosis": 0.9,
    "demand_funnel_diagnosis": 0.85,
    "channel_structure_diagnosis": 0.8,
    "audience_structure_diagnosis": 0.8,
    # 商品：卖什么
    "sku_structure_diagnosis": 0.8,
    "product_opportunity_matrix": 0.7,
    "sku_counterfactual_lift": 0.6,
    "content_response_curve": 0.55,
    # 内容：发什么
    "note_commercial_diagnosis": 0.7,
    "paid_traffic_efficiency": 0.7,
    "copy_angle_effect": 0.6,
    "cover_style_effect": 0.55,
    "content_portfolio_optimization": 0.55,
    "product_content_interaction": 0.5,
    # 用户需求 / 实验
    "comment_demand_mining": 0.65,
    "weekly_experiment_matrix": 0.6,
    "reshoot_repost_candidates": 0.55,
    "hypothesis_knowledge_base": 0.4,
    # 基础参考
    "account_baseline": 0.35,
    "note_funnel": 0.35,
    "weekly_business_review": 0.4,
}
_DEFAULT_WEIGHT = 0.5

# Causal evidence contributes more to "can I act on this" than descriptive precision.
_EVIDENCE_SCORE: dict[str, float] = {
    "strong": 1.0,
    "medium": 0.66,
    "weak": 0.33,
    "not_judgable": 0.0,
}
_RELIABILITY_SCORE: dict[str, float] = {
    "high": 1.0,
    "medium": 0.66,
    "low": 0.33,
    "not_applicable": 0.5,
}
# A finding a module never scored on the descriptive axis lands mid-scale, so its
# feasibility rides on the causal axis alone rather than being penalised or inflated.
_RELIABILITY_DEFAULT = 0.5
_EVIDENCE_WEIGHT = 0.6
_RELIABILITY_WEIGHT = 0.4

_HIGH_BAND = 0.75
_MID_BAND = 0.5
_MAX_ROWS = 8

# Reader-facing causal-evidence label, emitted once here so both the markdown and
# HTML compositors render the identical word. Kept as 强/中/弱 (distinct from the
# 高/中/低 impact/feasibility bands) so the three columns never read ambiguously.
_EVIDENCE_LABELS: dict[str, str] = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "not_judgable": "不可判断",
}


def _evidence_label(value: str) -> str:
    return _EVIDENCE_LABELS.get(value, value)


# 面向读者的「为什么值得先做」一句话,回答"凭什么排这么前"。它拼两半:
# 影响面 (impact) + 可动手程度 (feasibility)。旧版只看 impact,而核心模块 impact
# 几乎全是「高」→ 八行文案完全一致、成了废列;现在两轴一起决定措辞,同为高影响但
# 证据强弱不同的两行会读出「本周直接落地」vs「先小样本验证」的差别。
_IMPACT_CLAUSE: dict[str, str] = {
    "高": "影响面大、直接牵动整体生意",
    "中": "对生意有明显带动",
    "低": "影响相对局部",
}
_READY_CLAUSE: dict[str, str] = {
    "高": "证据扎实、本周可直接落地,回报最快",
    "中": "证据中等,建议小步推进、边做边看",
    "低": "证据偏薄,先小样本验证再放大",
}


def _why(impact_label: str, feasibility_label: str) -> str:
    impact = _IMPACT_CLAUSE.get(impact_label, _IMPACT_CLAUSE["中"])
    ready = _READY_CLAUSE.get(feasibility_label, _READY_CLAUSE["中"])
    return f"{impact},{ready}。"


def _band(score: float) -> str:
    if score >= _HIGH_BAND:
        return "高"
    if score >= _MID_BAND:
        return "中"
    return "低"


def _feasibility(finding: Finding) -> float:
    evidence = _EVIDENCE_SCORE.get(finding.evidence_strength.value, 0.0)
    reliability = finding.descriptive_reliability
    reliability_score = (
        _RELIABILITY_SCORE.get(reliability.value, _RELIABILITY_DEFAULT)
        if reliability is not None
        else _RELIABILITY_DEFAULT
    )
    return _EVIDENCE_WEIGHT * evidence + _RELIABILITY_WEIGHT * reliability_score


def _is_actionable(finding: Finding) -> bool:
    return bool(finding.recommended_action) and (
        finding.evidence_strength is not EvidenceStrength.NOT_JUDGABLE
    )


def _best_actionable(result: AnalysisResult) -> Finding | None:
    """The actionable finding a reader should act on first — highest feasibility.

    Modules list their headline finding first, but the most *actionable* one may sit
    lower (a strong, well-measured sub-finding under a hedged headline). Ranking by
    feasibility surfaces the lever the reader can actually pull with confidence.
    """
    candidates = [finding for finding in result.findings if _is_actionable(finding)]
    if not candidates:
        return None
    return max(candidates, key=_feasibility)


def result_priority(result: AnalysisResult) -> float:
    """Per-result 预期影响 × 可行性 score, for cross-module ordering.

    Reuses the module's most actionable finding (:func:`_best_actionable`). Modules
    with no actionable finding score ``0.0`` so they sort after actionable ones while
    keeping a stable relative order. Pure and never-raise — the single source of the
    same ranking used by :func:`build_priority_table` and the domain grouping.
    """
    finding = _best_actionable(result)
    if finding is None:
        return 0.0
    impact = LEVER_WEIGHTS.get(result.task_id, _DEFAULT_WEIGHT)
    return impact * _feasibility(finding)


def build_priority_table(
    results: list[AnalysisResult], max_rows: int = _MAX_ROWS
) -> list[dict[str, object]]:
    """Rank each module's strongest actionable finding by 预期影响 × 可行性.

    Returns a priority-sorted list of rows (highest first), one per contributing
    module, capped at ``max_rows``. Each row carries both the raw scores and their
    reader-facing 高/中/低 bands. Empty when no module has an actionable finding;
    never raises.
    """
    rows: list[dict[str, object]] = []
    for result in results:
        if result.task_id in APPENDIX_TASKS:
            continue
        finding = _best_actionable(result)
        if finding is None:
            continue
        impact = LEVER_WEIGHTS.get(result.task_id, _DEFAULT_WEIGHT)
        feasibility = _feasibility(finding)
        impact_label = _band(impact)
        feasibility_label = _band(feasibility)
        # Single reader-facing 置信度 (same primitive as everywhere else), folded from
        # the two statistical axes — it rides as one tag inside 「为什么值得先做」 rather
        # than the old 预期影响/可行性/证据 three-column grid.
        confidence = reader_confidence(finding)
        rows.append(
            {
                "task_id": result.task_id,
                "module": result.title,
                "weak_link": finding.title,
                "detail": finding.conclusion,
                "lever": finding.recommended_action,
                "why": _why(impact_label, feasibility_label),
                "confidence_label": confidence.label,
                "confidence_class": confidence.level,
                "impact": impact,
                "impact_label": impact_label,
                "feasibility": feasibility,
                "feasibility_label": feasibility_label,
                "priority": impact * feasibility,
                "evidence": finding.evidence_strength.value,
                "evidence_label": _evidence_label(finding.evidence_strength.value),
                "evidence_class": finding.evidence_strength.value,
            }
        )
    rows.sort(key=lambda row: row["priority"], reverse=True)
    return rows[:max_rows]
