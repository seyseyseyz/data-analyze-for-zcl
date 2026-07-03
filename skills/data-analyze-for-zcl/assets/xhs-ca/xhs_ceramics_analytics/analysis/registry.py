from pathlib import Path
from typing import Callable

from xhs_ceramics_analytics.analysis import (
    account_baseline,
    ad_quality,
    audience_structure,
    channel_structure_diagnosis,
    comment_demand,
    copy_effect,
    core_business,
    cover_effect,
    data_quality,
    experiment_matrix,
    hypothesis,
    note_commercial,
    note_funnel,
    paid_traffic,
    portfolio,
    product_interaction,
    product_opportunity,
    refund_diagnosis,
    refund_root_cause_diagnosis,
    response_curve,
    reshoot,
    search_efficiency,
    sku_lift,
    sku_structure,
    weekly_review,
)
from xhs_ceramics_analytics.analysis.result import AnalysisResult


TASKS: dict[str, Callable[[Path], AnalysisResult]] = {
    "data_quality_check": data_quality.run,
    "ad_data_quality_check": ad_quality.run,
    "paid_traffic_efficiency": paid_traffic.run,
    "account_baseline": account_baseline.run,
    "note_funnel": note_funnel.run,
    "sku_counterfactual_lift": sku_lift.run,
    "content_response_curve": response_curve.run,
    "cover_style_effect": cover_effect.run,
    "copy_angle_effect": copy_effect.run,
    "product_content_interaction": product_interaction.run,
    "product_opportunity_matrix": product_opportunity.run,
    "comment_demand_mining": comment_demand.run,
    "content_portfolio_optimization": portfolio.run,
    "weekly_experiment_matrix": experiment_matrix.run,
    "reshoot_repost_candidates": reshoot.run,
    "hypothesis_knowledge_base": hypothesis.run,
    "weekly_business_review": weekly_review.run,
    "refund_structure_diagnosis": refund_diagnosis.run,
    "core_business_diagnosis": core_business.run,
    "search_efficiency_diagnosis": search_efficiency.run,
    "audience_structure_diagnosis": audience_structure.run,
    "note_commercial_diagnosis": note_commercial.run,
    "sku_structure_diagnosis": sku_structure.run,
    "channel_structure_diagnosis": channel_structure_diagnosis.run,
    "refund_root_cause_diagnosis": refund_root_cause_diagnosis.run,
}


def run_task(task_id: str, db_path: Path) -> AnalysisResult:
    if task_id not in TASKS:
        raise KeyError(f"unknown analysis task: {task_id}")
    return TASKS[task_id](db_path)
