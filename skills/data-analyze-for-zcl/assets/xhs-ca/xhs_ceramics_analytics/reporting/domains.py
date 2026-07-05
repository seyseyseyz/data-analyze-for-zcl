"""业务主题域注册表 —— 报告的两级信息架构 (病根 B).

复盘投诉「报告碎、没轻重、找不到北」的病根:分析模块本来就是围绕几个业务问题展开的,
但报告过去把二十多个模块平铺成一长串,读者得自己在脑子里重新归堆。这个注册表把模块按
**业务主题域**收成 6 组(生意大盘 / 流量与内容 / 商品结构 / 用户与需求 / 退款与售后 /
实验与下周行动),域内再按跨模块优先级降序——读者先看"哪块生意",再看"这块里先动谁"。

md / html 两个 compositor 都从 :func:`group_by_domain` 取域结构,保证两种产物分组一致。
附录(数据质量)不进域,由 :mod:`section_order` 单独收尾。任何未列入域的 task 落到兜底
"其他参考"域,绝不丢。纯函数,never-raise。
"""
from typing import NamedTuple

from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.reporting.priority import result_priority
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS

# (域标题, 域一句话导语, 归入的 task_id 元组)。顺序即报告里域出现的顺序:先看生意本身,
# 再看流量/内容怎么带,商品卖什么,用户想什么,售后哪漏,最后落到下周怎么做。
DOMAINS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "生意大盘",
        "整体 GMV、转化、客单与增长归因,先看生意本身怎么样。",
        ("core_business_diagnosis", "demand_funnel_diagnosis"),
    ),
    (
        "流量与内容",
        "笔记商业效能、搜索承接、渠道结构与重拍机会,发什么、从哪来。",
        (
            "note_commercial_diagnosis",
            "search_efficiency_diagnosis",
            "channel_structure_diagnosis",
            "reshoot_repost_candidates",
            "cover_style_effect",
            "copy_angle_effect",
            "content_portfolio_optimization",
            "product_content_interaction",
            "paid_traffic_efficiency",
            "content_response_curve",
            "note_funnel",
        ),
    ),
    (
        "商品结构",
        "SKU 的 GMV/退款结构与销售反馈,卖什么、补哪些。",
        (
            "sku_structure_diagnosis",
            "product_opportunity_matrix",
            "sku_counterfactual_lift",
        ),
    ),
    (
        "用户与需求",
        "人群结构与评论里的真实疑问,谁在买、还想问什么。",
        ("audience_structure_diagnosis", "comment_demand_mining"),
    ),
    (
        "退款与售后",
        "退款结构、层级与根因合并成一块,售后哪里在漏。",
        ("refund_structure_diagnosis", "refund_root_cause_diagnosis"),
    ),
    (
        "实验与下周行动",
        "把结论转成一周可执行排期与假设留存。",
        (
            "weekly_experiment_matrix",
            "weekly_business_review",
            "hypothesis_knowledge_base",
            "account_baseline",
        ),
    ),
)

# 数据质量附录不进业务域,由 section_order 收尾;标题与导语在此单点定义,md / html 共用。
APPENDIX_DOMAIN_TITLE = "附录：数据质量与口径说明"
APPENDIX_DOMAIN_INTRO = (
    "数据导入、口径与完整度说明,为上面所有结论标注可信度;"
    "阻断性问题在建库阶段已处置,这里只作透明留证。"
)

# 未列入任何域的 task 收容在这里,绝不丢——新增模块即便忘记归域也仍进报告。
_FALLBACK_TITLE = "其他参考"
_FALLBACK_INTRO = "暂未归入固定业务主题的模块,仍保留结论与明细,方便继续扩展。"

# 所有已归域的 task_id,用来判定兜底。
_DOMAIN_TASKS: frozenset[str] = frozenset(t for _, _, tasks in DOMAINS for t in tasks)


class DomainGroup(NamedTuple):
    title: str
    intro: str
    results: list[AnalysisResult]  # 域内按跨模块优先级降序


def group_by_domain(results: list[AnalysisResult]) -> list[DomainGroup]:
    """把结果按业务主题域收成两级结构,域内按优先级降序。Never-raise。

    附录(数据质量)任务被剔除,由 :mod:`section_order` 单独收尾。未列入任何域的 task
    落到末尾的兜底"其他参考"域,不丢。空输入返回 ``[]``。
    """
    body = [result for result in results if result.task_id not in APPENDIX_TASKS]

    groups: list[DomainGroup] = []
    for title, intro, tasks in DOMAINS:
        members = [result for result in body if result.task_id in tasks]
        if not members:
            continue
        # stable sort by priority desc: ties keep caller order.
        members.sort(key=result_priority, reverse=True)
        groups.append(DomainGroup(title=title, intro=intro, results=members))

    leftover = [result for result in body if result.task_id not in _DOMAIN_TASKS]
    if leftover:
        leftover.sort(key=result_priority, reverse=True)
        groups.append(
            DomainGroup(title=_FALLBACK_TITLE, intro=_FALLBACK_INTRO, results=leftover)
        )

    return groups
