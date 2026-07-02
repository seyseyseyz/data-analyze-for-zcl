from numbers import Number

from jinja2 import Environment, PackageLoader

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.reporting.markdown import render_markdown
from xhs_ceramics_analytics.reporting.labels import (
    VALUE_LABELS as _VALUE_LABELS,
    format_number as _format_number,
    format_percent as _format_percent,
)
from xhs_ceramics_analytics.reporting import charts


_EVIDENCE_LABELS = {
    "strong": "高",
    "medium": "中",
    "weak": "低",
    "not_judgable": "不可判断",
}

_EVIDENCE_HELP = {
    "strong": "数据较充分，可以直接作为经营依据。",
    "medium": "可以用于本周决策，但建议继续观察。",
    "weak": "适合作为实验方向，暂不适合直接下定论。",
    "not_judgable": "当前数据不足，需要先补齐导入或埋点。",
}

_FIELD_LABELS = {
    "absolute_lift": ("绝对提升", "发布后销量减去发布前销量。"),
    "active_days": ("活跃发布天数", "有笔记发布记录的天数。"),
    "avg_collect_rate": ("平均收藏率", "收藏数除以阅读数后的平均值。"),
    "avg_collects": ("平均收藏数", "每组内容平均获得的收藏数。"),
    "avg_comment_rate": ("平均评论率", "评论数除以阅读数后的平均值。"),
    "avg_like_rate": ("平均点赞率", "点赞数除以阅读数后的平均值。"),
    "avg_read_rate": ("平均阅读率", "阅读数除以曝光数后的平均值。"),
    "avg_reads": ("平均阅读数", "每组内容平均获得的阅读数。"),
    "budget_action": ("预算动作", "系统根据消耗、点击和投产给出的下周预算建议。"),
    "campaign_name_optional": ("投放计划", "后台导出的投放计划名称。"),
    "candidate_notes": ("候选笔记数", "进入重拍或重发候选池的笔记数量。"),
    "collect_rate": ("收藏率", "收藏数除以阅读数。"),
    "collects": ("收藏数", "笔记获得的收藏数量。"),
    "comment_rate": ("评论率", "评论数除以阅读数。"),
    "comment_share": ("评论占比", "该需求类型在全部评论中的占比。"),
    "comments": ("评论数", "评论数量。"),
    "composition_type": ("封面构图", "首图或封面的画面类型。"),
    "conservative_collect_rate": ("保守收藏率", "对小样本降权后的收藏率。"),
    "content_angles": ("内容角度数", "计划里覆盖的文案角度数量。"),
    "copy_angle": ("文案角度", "内容采用的表达方向，例如送礼、生活方式、餐桌场景。"),
    "copy_groups": ("文案角度组数", "参与文案角度对比的分组数量。"),
    "cover_groups": ("封面类型组数", "参与封面效果对比的分组数量。"),
    "cpc_calc": ("点击成本", "投放消耗除以点击量。"),
    "cpm_calc": ("千次曝光成本", "每一千次曝光对应的投放消耗。"),
    "cost_per_order_calc": ("单订单成本", "投放消耗除以成交订单数。"),
    "ctr_calc": ("点击率", "点击量除以曝光量。"),
    "creative_name_optional": ("创意名称", "后台导出的素材或创意名称。"),
    "date": ("日期", "对应的数据日期。"),
    "day_index": ("第几天", "实验计划中的第几天。"),
    "days": ("实验天数", "计划覆盖的天数。"),
    "demand_group": ("需求类型", "从评论中识别出的用户需求类别。"),
    "detected_grain": ("识别粒度", "系统根据字段判断出的导出粒度。"),
    "d0_1_units": ("0-1 天销量", "笔记发布后 0 到 1 天内的销量。"),
    "d1_3_units": ("1-3 天销量", "笔记发布后 1 到 3 天内的销量。"),
    "d4_7_units": ("4-7 天销量", "笔记发布后 4 到 7 天内的销量。"),
    "d8_14_units": ("8-14 天销量", "笔记发布后 8 到 14 天内的销量。"),
    "d8_14_rows": ("长窗口样本数", "有 8 到 14 天观察窗口的样本数量。"),
    "evidence_count": ("证据数量", "支撑该判断的数据条数。"),
    "evidence_items": ("证据项", "复盘中可用的证据数量。"),
    "evidence_strength": ("可信度", "这条结论目前能被用于经营决策的程度。"),
    "evidence_summary": ("证据摘要", "支撑假设的简短说明。"),
    "example_comments": ("评论示例", "该需求类型下的代表性评论。"),
    "experiment_seed": ("实验标识", "用于追踪这次实验组合的唯一标记。"),
    "first_d8_14_absolute_lift": (
        "首个 8-14 天绝对提升",
        "第一条长窗口样本的发布后销量减发布前销量。",
    ),
    "first_d8_14_post_units": (
        "首个 8-14 天发布后销量",
        "第一条长窗口样本的发布后销量。",
    ),
    "gmv": ("销售额", "该 SKU 在观察期内产生的成交金额。"),
    "gmv_optional": ("成交金额", "投放后台或订单侧可见的成交金额。"),
    "hypotheses": ("假设数量", "当前生成的经营假设数量。"),
    "hypothesis": ("经营假设", "等待下周实验验证的判断。"),
    "hypothesis_id": ("假设编号", "用于持续追踪同一条假设的编号。"),
    "impressions": ("曝光数", "内容被看到的次数。"),
    "label": ("标签", "假设或分组的人类可读名称。"),
    "like_rate": ("点赞率", "点赞数除以阅读数。"),
    "likes": ("点赞数", "笔记获得的点赞数量。"),
    "link_source": ("关联来源", "笔记和 SKU 之间的匹配方式。"),
    "metric": ("指标", "该模块当前用于判断的核心指标。"),
    "mix_share": ("内容占比", "该内容角度在全部内容中的占比。"),
    "needs_more_data": ("是否需要更多数据", "样本不足时会标记为需要继续观察。"),
    "next_test": ("下一步实验", "建议下周验证这条假设的方式。"),
    "note_id": ("笔记编号", "笔记的内部编号，用来追踪具体是哪一条内容。"),
    "note_sku_links": ("笔记-SKU 关联数", "可用于归因分析的笔记和 SKU 组合数量。"),
    "note_sku_rows": ("笔记-SKU 数据行", "响应窗口中可用的笔记和 SKU 组合行数。"),
    "notes": ("笔记数", "参与该统计的笔记数量。"),
    "observed_groups": ("观察到的需求组数", "评论中实际出现的需求类型数量。"),
    "opportunity_score": ("机会分", "综合收藏率和阅读空间计算的候选优先级。"),
    "opportunity_type": ("机会类型", "系统给商品机会的初步分类。"),
    "paid_active_days": ("活跃投放天数", "该投放对象出现数据的天数。"),
    "paid_amount": ("成交金额", "订单实际支付金额。"),
    "planned_rows": ("计划档期数", "下周实验矩阵生成的发布档期数量。"),
    "platform_source": ("投放平台", "聚光、薯条、商家后台或其他来源。"),
    "post_units": ("发布后销量", "笔记发布后窗口内的 SKU 销量。"),
    "posts": ("发布笔记数", "统计期内发布的笔记数量。"),
    "pre_units": ("发布前销量", "笔记发布前窗口内的 SKU 销量。"),
    "price": ("价格", "商品价格或用于估算的金额。"),
    "publish_time": ("发布时间", "笔记发布的具体时间。"),
    "rank": ("排序", "候选项的优先级顺序。"),
    "read_gap_to_max": ("阅读差距", "相对最高阅读数还差多少。"),
    "read_rate": ("阅读率", "阅读数除以曝光数。"),
    "reads": ("阅读数", "笔记获得的阅读数量。"),
    "ready_sections": ("有源数据模块数", "复盘里已经找到可用数据的模块数量。"),
    "reason": ("入选原因", "系统将该项列入候选的原因。"),
    "relative_lift": ("相对提升", "绝对提升相对发布前销量的比例。"),
    "roas_calc": ("投产比", "成交金额除以投放消耗。"),
    "roles": ("内容角色数", "内容组合中出现的文案角色数量。"),
    "rows": ("数据行数", "该数据表里可用于分析的记录数量。"),
    "sales_days": ("销售天数", "观察期内有销售记录的天数。"),
    "section": ("复盘模块", "每周复盘中的模块名称。"),
    "sections": ("模块数", "每周复盘覆盖的模块数量。"),
    "seed": ("假设种子", "生成假设时使用的稳定追踪键。"),
    "sku_count": ("SKU 数量", "参与商品机会分析的 SKU 数量。"),
    "sku_id": ("SKU 编号", "具体商品规格的内部编号。"),
    "sku_name": ("SKU 名称", "商品规格名称。"),
    "slot_index": ("第几个时段", "当天计划中的发布时段序号。"),
    "slot_time": ("发布时间段", "建议发布的时间段。"),
    "slots_per_day": ("每日时段数", "每天安排的发布档期数量。"),
    "source": ("来源任务", "该复盘模块来自哪个分析任务。"),
    "spend": ("投放消耗", "投放后台记录的广告消耗。"),
    "status": ("状态", "该项当前是否可用或需要补数据。"),
    "summary": ("摘要", "该模块的可读说明。"),
    "success_metric": ("判断指标", "用于判断实验是否有效的核心指标。"),
    "table": ("数据表", "导入数据库中的表名。"),
    "table_count": ("数据表数量", "成功导入的数据表数量。"),
    "theme": ("假设主题", "假设所属的经营主题。"),
    "title": ("标题", "笔记或项目标题。"),
    "top_candidate": ("首选候选", "当前排序最高的候选笔记。"),
    "top_group": ("最高需求类型", "评论里数量最多的需求类型。"),
    "top_role": ("最高内容角度", "当前出现最多或表现较好的内容角度。"),
    "top_sku_units": ("头部 SKU 销量", "销量最高 SKU 的销售件数。"),
    "total_spend": ("总投放消耗", "当前投放表里汇总的广告消耗。"),
    "unique_skus": ("SKU 覆盖数", "实验计划里覆盖的 SKU 数量。"),
    "units": ("销售件数", "该 SKU 在观察期内卖出的件数。"),
    "value": ("数值", "该模块对应指标的结果。"),
    "window": ("观察窗口", "围绕笔记发布时间划分的时间窗口。"),
    "windows": ("观察窗口数", "生成的时间窗口数量。"),
    "combinations": ("内容组合数", "封面和文案角度组合后的分组数量。"),
}

_MAX_TABLE_ROWS = 20

_BUSINESS_HIGHLIGHT_TASKS = (
    "product_opportunity_matrix",
    "copy_angle_effect",
    "content_portfolio_optimization",
    "comment_demand_mining",
    "reshoot_repost_candidates",
    "weekly_experiment_matrix",
)

_ANALYSIS_GROUPS = (
    {
        "title": "商品：卖什么",
        "description": "先看哪些 SKU 已经有销售反馈，哪些商品还需要继续补内容或补销售数据。",
        "tasks": (
            "product_opportunity_matrix",
            "sku_counterfactual_lift",
            "content_response_curve",
        ),
    },
    {
        "title": "内容：发什么",
        "description": "把封面、文案角度和内容组合拆开看，避免只凭单篇爆款做判断。",
        "tasks": (
            "cover_style_effect",
            "copy_angle_effect",
            "product_content_interaction",
            "content_portfolio_optimization",
        ),
    },
    {
        "title": "用户需求：用户在问什么",
        "description": "从评论里提炼价格、容量、购买入口和送礼等真实疑问，反推内容和详情页要补什么。",
        "tasks": ("comment_demand_mining",),
    },
    {
        "title": "实验：下周怎么验证",
        "description": "把当前结论转成可以执行的一周计划，并标出适合重拍或重发的候选笔记。",
        "tasks": (
            "weekly_experiment_matrix",
            "reshoot_repost_candidates",
            "hypothesis_knowledge_base",
        ),
    },
    {
        "title": "数据可信度",
        "description": "最后再看数据导入、账号基线、笔记漏斗和周复盘，判断哪些结论能直接用，哪些只能当实验线索。",
        "tasks": (
            "data_quality_check",
            "account_baseline",
            "note_funnel",
            "weekly_business_review",
        ),
    },
)

_TABLE_LABELS = {
    "table_row_counts": "导入数据检查",
    "daily_posts": "账号日发布与互动",
    "note_funnel": "笔记漏斗明细",
    "cover_effects": "封面效果对比",
    "copy_effects": "文案角度对比",
    "product_opportunities": "商品机会明细",
    "sku_lift": "SKU 销量响应",
    "response_windows": "内容响应窗口",
    "product_interactions": "商品与内容组合",
    "portfolio_mix": "内容组合占比",
    "comment_demands": "评论需求分组",
    "experiment_plan": "下周实验排期",
    "reshoot_candidates": "重拍候选笔记",
    "hypotheses": "经营假设库",
    "weekly_sections": "周复盘模块",
    "ad_data_quality": "投放数据可用性",
    "paid_traffic_efficiency": "投放效率明细",
}

_USER_TABLE_COLUMNS = {
    "table_row_counts": ("table", "rows"),
    "daily_posts": ("date", "posts", "reads", "collects", "comments"),
    "note_funnel": (
        "note_id",
        "reads",
        "read_rate",
        "like_rate",
        "collect_rate",
        "comment_rate",
    ),
    "cover_effects": ("composition_type", "notes", "avg_reads", "avg_collects"),
    "copy_effects": ("copy_angle", "notes", "avg_reads", "avg_collects"),
    "product_opportunities": ("sku_name", "units", "gmv", "opportunity_type"),
    "sku_lift": (
        "sku_name",
        "window",
        "pre_units",
        "post_units",
        "absolute_lift",
        "relative_lift",
    ),
    "response_windows": (
        "note_id",
        "sku_name",
        "window",
        "pre_units",
        "post_units",
        "relative_lift",
    ),
    "product_interactions": (
        "composition_type",
        "copy_angle",
        "notes",
        "avg_reads",
        "avg_collects",
    ),
    "portfolio_mix": (
        "copy_angle",
        "notes",
        "mix_share",
        "avg_reads",
        "avg_collect_rate",
    ),
    "comment_demands": (
        "demand_group",
        "comments",
        "comment_share",
        "example_comments",
    ),
    "experiment_plan": (
        "date",
        "slot_time",
        "sku_name",
        "copy_angle",
        "success_metric",
    ),
    "reshoot_candidates": (
        "rank",
        "title",
        "reads",
        "collects",
        "collect_rate",
        "reason",
    ),
    "hypotheses": (
        "theme",
        "hypothesis",
        "evidence_summary",
        "next_test",
        "status",
    ),
    "weekly_sections": ("section", "status", "metric", "value", "summary"),
    "ad_data_quality": (
        "rows",
        "first_date",
        "last_date",
        "total_spend",
        "detected_grain",
        "has_click_metrics",
        "has_gmv_metrics",
    ),
    "paid_traffic_efficiency": (
        "campaign_name_optional",
        "creative_name_optional",
        "spend",
        "impressions",
        "clicks",
        "ctr_calc",
        "cpc_calc",
        "gmv_optional",
        "roas_calc",
        "budget_action",
    ),
}

_PERCENT_FIELDS = {
    "avg_collect_rate",
    "avg_comment_rate",
    "avg_like_rate",
    "avg_read_rate",
    "collect_rate",
    "comment_rate",
    "comment_share",
    "confidence_weight",
    "ctr_calc",
    "like_rate",
    "mix_share",
    "read_gap_to_max",
    "read_rate",
    "relative_lift",
}

_MONEY_FIELDS = {
    "cost_per_order_calc",
    "cpc_calc",
    "cpm_calc",
    "gmv",
    "gmv_optional",
    "paid_amount",
    "price",
    "spend",
    "total_spend",
}


def render_html(results: list[AnalysisResult]) -> str:
    env = Environment(
        loader=PackageLoader("xhs_ceramics_analytics.reporting", "templates"),
        autoescape=True,
    )
    env.filters["evidence_label"] = _evidence_label
    env.filters["field_label"] = _field_label
    env.filters["field_help"] = _field_help
    env.filters["display_value"] = _display_value
    env.filters["display_cell"] = _display_cell_filter
    template = env.get_template("report.html.j2")
    return template.render(
        markdown_report=render_markdown(results),
        report=_build_report_context(results),
        results=results,
    )


def _build_report_context(results: list[AnalysisResult]) -> dict[str, object]:
    findings = [finding for result in results for finding in result.findings]
    total_table_rows = sum(len(rows) for result in results for rows in result.tables.values())
    result_views = [_result_view(result) for result in results]
    return {
        "task_count": len(results),
        "finding_count": len(findings),
        "table_count": sum(len(result.tables) for result in results),
        "total_table_rows": total_table_rows,
        "highlights": _business_highlights(results),
        "actions": _business_actions(results, findings),
        "analysis_groups": _analysis_groups(result_views),
        "evidence_counts": _evidence_counts(findings),
        "evidence_chart_svg": charts.evidence_distribution(_evidence_counts(findings)),
        "codex_questions": _codex_questions(results),
        "glossary": [
            {
                "term": "可信度",
                "definition": "说明这条结论能被多大程度用于经营决策，不代表结论有没有价值。",
            },
            {
                "term": "弱归因",
                "definition": "数据能提供方向，但还不能证明某条笔记直接带来了某个订单。",
            },
            {
                "term": "受控实验",
                "definition": "一次只改变一个变量，例如只换文案角度，其他 SKU、发布时间和封面尽量保持一致。",
            },
            {
                "term": "SKU",
                "definition": "具体商品规格，例如单只杯子、礼盒装、不同颜色或容量。",
            },
        ],
    }


def _result_view(result: AnalysisResult) -> dict[str, object]:
    return {
        "task_id": result.task_id,
        "title": result.title,
        "label": _result_label(result.task_id, result.title),
        "findings": [_finding_view(finding) for finding in result.findings],
        "table_views": [
            _table_view(table_name, rows) for table_name, rows in result.tables.items()
        ],
        "limitations": result.limitations,
    }


def _finding_view(finding: Finding) -> dict[str, object]:
    summary = _finding_summary(finding)
    return {
        **summary,
        "key_numbers": [
            {
                "label": _field_label(key),
                "help": _field_help(key),
                "value": _display_cell(key, value),
            }
            for key, value in finding.key_numbers.items()
        ],
        "caveats": finding.caveats,
        "recommended_action": finding.recommended_action,
        "evidence_reason": finding.evidence_reason,
    }


def _table_view(table_name: str, rows: list[dict[str, object]]) -> dict[str, object]:
    all_columns = list(rows[0].keys()) if rows else []
    preferred_columns = _USER_TABLE_COLUMNS.get(table_name, tuple(all_columns[:6]))
    user_columns = [column for column in preferred_columns if column in all_columns]
    if not user_columns:
        user_columns = all_columns[:6]

    showing_count = min(len(rows), _MAX_TABLE_ROWS)
    display_text = f"共 {len(rows)} 行，当前展示 {showing_count} 行"
    if len(rows) > _MAX_TABLE_ROWS:
        display_text = f"共 {len(rows)} 行，当前展示前 {showing_count} 行"

    return {
        "name": table_name,
        "label": _TABLE_LABELS.get(table_name, table_name.replace("_", " ")),
        "row_count": len(rows),
        "showing_count": showing_count,
        "display_text": display_text,
        "user_columns": [_column_view(column) for column in user_columns],
        "technical_columns": [_column_view(column) for column in all_columns],
        "user_rows": [_row_cells(row, user_columns) for row in rows[:_MAX_TABLE_ROWS]],
        "technical_rows": [_row_cells(row, all_columns) for row in rows[:_MAX_TABLE_ROWS]],
    }


def _column_view(column: str) -> dict[str, str]:
    return {
        "name": column,
        "label": _field_label(column),
        "help": _field_help(column),
    }


def _row_cells(row: dict[str, object], columns: list[str]) -> list[dict[str, str]]:
    return [
        {
            "name": column,
            "value": _display_cell(column, row.get(column)),
        }
        for column in columns
    ]


def _analysis_groups(result_views: list[dict[str, object]]) -> list[dict[str, object]]:
    views_by_task = {str(view["task_id"]): view for view in result_views}
    grouped: list[dict[str, object]] = []
    used: set[str] = set()
    for group in _ANALYSIS_GROUPS:
        views = [views_by_task[task_id] for task_id in group["tasks"] if task_id in views_by_task]
        if not views:
            continue
        used.update(str(view["task_id"]) for view in views)
        grouped.append(
            {
                "title": group["title"],
                "description": group["description"],
                "results": views,
            }
        )

    remaining = [view for view in result_views if str(view["task_id"]) not in used]
    if remaining:
        grouped.append(
            {
                "title": "其他分析",
                "description": "这些模块暂时没有归入固定经营问题，但仍保留结论和明细，方便继续扩展。",
                "results": remaining,
            }
        )
    return grouped


def _highlights(findings: list[Finding]) -> list[dict[str, str]]:
    highlighted = findings[:3]
    if not highlighted:
        return [
            {
                "title": "暂无可读结论",
                "body": "当前数据还不足以生成经营判断，请先完成数据导入。",
                "evidence": "不可判断",
                "evidence_class": "not_judgable",
                "help": _EVIDENCE_HELP["not_judgable"],
            }
        ]
    return [_finding_summary(finding) for finding in highlighted]


def _business_highlights(results: list[AnalysisResult]) -> list[dict[str, str]]:
    results_by_task = {result.task_id: result for result in results}
    highlights: list[dict[str, str]] = []
    for task_id in _BUSINESS_HIGHLIGHT_TASKS:
        result = results_by_task.get(task_id)
        if result is None:
            continue
        highlight = _highlight_for_result(result)
        if highlight is not None:
            highlights.append(highlight)

    if highlights:
        return highlights[:4]

    findings = [
        finding
        for result in results
        if result.task_id != "data_quality_check"
        for finding in result.findings
    ]
    if not findings:
        findings = [finding for result in results for finding in result.findings]
    return _highlights(findings)


def _highlight_for_result(result: AnalysisResult) -> dict[str, str] | None:
    if result.task_id == "product_opportunity_matrix":
        row = _first_row(result, "product_opportunities")
        if row:
            sku = str(row.get("sku_name") or "头部 SKU")
            return _highlight(
                result,
                f"商品机会：优先测试{sku}",
                (
                    f"当前销售件数 {_display_cell('units', row.get('units'))}，"
                    f"销售额 {_display_cell('gmv', row.get('gmv'))}，"
                    f"系统判断为{_display_cell('opportunity_type', row.get('opportunity_type'))}。"
                    "下周适合围绕这个商品做受控内容实验。"
                ),
            )
        return _highlight_from_primary_finding(result, "商品机会")

    if result.task_id in {"copy_angle_effect", "content_portfolio_optimization"}:
        table_name = "copy_effects" if result.task_id == "copy_angle_effect" else "portfolio_mix"
        row = _first_row(result, table_name)
        if row:
            angle = _display_cell("copy_angle", row.get("copy_angle"))
            reads = _display_cell("avg_reads", row.get("avg_reads"))
            collects = _display_cell("avg_collects", row.get("avg_collects"))
            return _highlight(
                result,
                f"内容角度：{angle}值得继续验证",
                (
                    f"这个角度已有 {_display_cell('notes', row.get('notes'))} 篇样本，"
                    f"平均阅读数 {reads}，平均收藏数 {collects}。"
                    "它适合进入下周实验，而不是直接当作长期定论。"
                ),
            )
        return _highlight_from_primary_finding(result, "内容角度")

    if result.task_id == "comment_demand_mining":
        row = _first_row(result, "comment_demands")
        if row:
            group = _display_cell("demand_group", row.get("demand_group"))
            return _highlight(
                result,
                f"用户需求：优先回应{group}",
                (
                    f"该需求出现 {_display_cell('comments', row.get('comments'))} 次，"
                    f"占评论 {_display_cell('comment_share', row.get('comment_share'))}。"
                    "可以把它写进标题、正文、评论区回复和商品详情。"
                ),
            )
        return _highlight_from_primary_finding(result, "用户需求")

    if result.task_id == "reshoot_repost_candidates":
        row = _first_row(result, "reshoot_candidates")
        if row:
            title = str(row.get("title") or row.get("note_id") or "队首候选")
            return _highlight(
                result,
                f"重拍机会：先复用「{title}」",
                (
                    f"这篇笔记收藏率 {_display_cell('collect_rate', row.get('collect_rate'))}，"
                    f"入选原因是{_display_cell('reason', row.get('reason'))}。"
                    "建议保留核心商品和角度，只改开场画面或封面做对照。"
                ),
            )
        return _highlight_from_primary_finding(result, "重拍机会")

    if result.task_id == "weekly_experiment_matrix":
        row_count = len(result.tables.get("experiment_plan", []))
        return _highlight(
            result,
            "实验计划：用一周排期验证结论",
            (
                f"报告已生成 {_display_cell('planned_rows', row_count)} 个发布档期。"
                "执行时一次只改一个变量，才看得出是商品、封面还是文案在起作用。"
            ),
        )

    return _highlight_from_primary_finding(result, result.title)


def _highlight(result: AnalysisResult, title: str, body: str) -> dict[str, str]:
    evidence_value = _primary_evidence_value(result)
    return {
        "title": title,
        "body": body,
        "evidence": _EVIDENCE_LABELS.get(evidence_value, evidence_value),
        "evidence_class": evidence_value,
        "help": _EVIDENCE_HELP.get(evidence_value, "请结合数据限制一起阅读。"),
    }


def _highlight_from_primary_finding(result: AnalysisResult, prefix: str) -> dict[str, str] | None:
    if not result.findings:
        return None
    summary = _finding_summary(result.findings[0])
    return {
        **summary,
        "title": f"{prefix}：{summary['title']}",
    }


def _recommended_actions(findings: list[Finding]) -> list[dict[str, str]]:
    actions = [
        {
            "title": finding.title,
            "body": finding.recommended_action,
            "evidence": _EVIDENCE_LABELS.get(
                finding.evidence_strength.value, finding.evidence_strength.value
            ),
            "evidence_class": finding.evidence_strength.value,
        }
        for finding in findings
        if finding.recommended_action
    ]
    if actions:
        return actions[:5]
    return [
        {
            "title": "先补齐关键数据",
            "body": "当前报告没有足够的建议动作。优先补齐笔记、SKU、订单和评论数据后再重新生成。",
            "evidence": "不可判断",
            "evidence_class": "not_judgable",
        }
    ]


def _business_actions(
    results: list[AnalysisResult], findings: list[Finding]
) -> list[dict[str, str]]:
    results_by_task = {result.task_id: result for result in results}
    actions: list[dict[str, str]] = []

    product = results_by_task.get("product_opportunity_matrix")
    product_row = _first_row(product, "product_opportunities") if product else None
    if product_row:
        sku = str(product_row.get("sku_name") or "头部 SKU")
        actions.append(
            _action(
                product,
                "商品实验",
                sku,
                (
                    f"它当前销售件数 {_display_cell('units', product_row.get('units'))}，"
                    f"销售额 {_display_cell('gmv', product_row.get('gmv'))}，"
                    f"机会类型是{_display_cell('opportunity_type', product_row.get('opportunity_type'))}。"
                ),
                "围绕同一个 SKU 连续发 2 到 3 条内容，只改变文案角度或封面构图中的一个变量。",
                "收藏率、阅读率、评论里的购买意向，以及后续 SKU 销量。",
                "如果连续 3 条内容收藏率都低于账号平均值，暂停放量，先换卖点或封面。",
            )
        )

    copy_result = results_by_task.get("copy_angle_effect") or results_by_task.get(
        "content_portfolio_optimization"
    )
    copy_row = None
    if copy_result is not None:
        copy_row = _first_row(copy_result, "copy_effects") or _first_row(
            copy_result, "portfolio_mix"
        )
    if copy_row:
        angle = _display_cell("copy_angle", copy_row.get("copy_angle"))
        actions.append(
            _action(
                copy_result,
                "内容角度",
                str(angle),
                (
                    f"该角度已有 {_display_cell('notes', copy_row.get('notes'))} 篇样本，"
                    f"平均阅读数 {_display_cell('avg_reads', copy_row.get('avg_reads'))}。"
                ),
                "选择同一 SKU、相近发布时间，分别测试这个角度和一个对照角度。",
                "收藏率、评论问题类型、阅读到收藏的转化。",
                "如果阅读不错但收藏弱，保留角度，重写首段和购买理由。",
            )
        )

    demand = results_by_task.get("comment_demand_mining")
    demand_row = _first_row(demand, "comment_demands") if demand else None
    if demand_row:
        group = _display_cell("demand_group", demand_row.get("demand_group"))
        actions.append(
            _action(
                demand,
                "用户需求",
                str(group),
                (
                    f"这个需求占评论 {_display_cell('comment_share', demand_row.get('comment_share'))}，"
                    f"代表问题包括：{_display_cell('example_comments', demand_row.get('example_comments'))}。"
                ),
                "把这个问题写进标题、正文 FAQ、置顶评论回复和商品详情页说明。",
                "同类问题是否减少、购买入口评论是否增加、收藏率是否改善。",
                "如果问题重复出现，说明内容没有解释清楚，需要把答案提前到封面或标题。",
            )
        )

    reshoot = results_by_task.get("reshoot_repost_candidates")
    reshoot_row = _first_row(reshoot, "reshoot_candidates") if reshoot else None
    if reshoot_row:
        title = str(reshoot_row.get("title") or reshoot_row.get("note_id") or "队首候选")
        actions.append(
            _action(
                reshoot,
                "重拍重发",
                title,
                (
                    f"这篇笔记收藏率 {_display_cell('collect_rate', reshoot_row.get('collect_rate'))}，"
                    f"但仍有 {_display_cell('read_gap_to_max', reshoot_row.get('read_gap_to_max'))} 的阅读差距。"
                ),
                "保留原主题和商品，重新拍一个更清晰的开场画面，并把标题卖点前置。",
                "阅读率、3 秒内停留表现、收藏率是否同时提升。",
                "如果阅读提升但收藏下降，说明新封面吸引了泛流量，需要收窄卖点。",
            )
        )

    experiment = results_by_task.get("weekly_experiment_matrix")
    experiment_rows = experiment.tables.get("experiment_plan", []) if experiment else []
    if experiment_rows:
        first = experiment_rows[0]
        actions.append(
            _action(
                experiment,
                "发布排期",
                "执行 7 天实验矩阵",
                (
                    f"第一条建议在 {_display_cell('date', first.get('date'))} "
                    f"{_display_cell('slot_time', first.get('slot_time'))} 发布，"
                    f"测试 {_display_cell('sku_name', first.get('sku_name'))} 和"
                    f"{_display_cell('copy_angle', first.get('copy_angle'))}。"
                ),
                "按矩阵发布，记录每条的 SKU、封面、文案角度和发布时间，不要临时混改多个变量。",
                "每条内容的收藏率、阅读率、评论需求和对应 SKU 销量。",
                "如果中途爆款出现，仍保留至少一个对照档期，避免只看单条内容。",
            )
        )

    if actions:
        return actions[:5]

    fallback = _recommended_actions(findings)
    return [
        {
            "task": "先补数据",
            "target": action["title"],
            "why": action["body"],
            "how": "补齐笔记、SKU、订单、内容特征和评论后重新生成报告。",
            "metric": "下一次报告中可判断的模块数量。",
            "stop_rule": "如果核心表仍为空，先不要解读趋势。",
            "evidence": action["evidence"],
            "evidence_class": action.get("evidence_class", "not_judgable"),
        }
        for action in fallback
    ]


def _action(
    result: AnalysisResult | None,
    task: str,
    target: str,
    why: str,
    how: str,
    metric: str,
    stop_rule: str,
) -> dict[str, str]:
    evidence_value = _primary_evidence_value(result) if result else "not_judgable"
    return {
        "task": task,
        "target": target,
        "why": why,
        "how": how,
        "metric": metric,
        "stop_rule": stop_rule,
        "evidence": _EVIDENCE_LABELS.get(evidence_value, evidence_value),
        "evidence_class": evidence_value,
    }


def _evidence_counts(findings: list[Finding]) -> list[dict[str, object]]:
    counts = {key: 0 for key in _EVIDENCE_LABELS}
    for finding in findings:
        counts[finding.evidence_strength.value] = counts.get(finding.evidence_strength.value, 0) + 1
    return [
        {
            "value": value,
            "label": _EVIDENCE_LABELS[value],
            "count": counts[value],
            "help": _EVIDENCE_HELP[value],
        }
        for value in ("strong", "medium", "weak", "not_judgable")
    ]


def _finding_summary(finding: Finding) -> dict[str, str]:
    evidence_value = finding.evidence_strength.value
    return {
        "title": finding.title,
        "body": finding.conclusion,
        "evidence": _EVIDENCE_LABELS.get(evidence_value, evidence_value),
        "evidence_class": evidence_value,
        "help": _EVIDENCE_HELP.get(evidence_value, "请结合数据限制一起阅读。"),
    }


def _evidence_label(value: str) -> str:
    return _EVIDENCE_LABELS.get(value, value)


def _field_label(field_name: str) -> str:
    label = _FIELD_LABELS.get(field_name)
    if label is not None:
        return label[0]
    return field_name.replace("_", " ")


def _field_help(field_name: str) -> str:
    label = _FIELD_LABELS.get(field_name)
    if label is not None:
        return label[1]
    return "原始数据字段，保留用于查数和追溯。"


def _display_value(value: object) -> str:
    return _display_cell("", value)


def _display_cell_filter(value: object, field_name: str) -> str:
    return _display_cell(field_name, value)


def _display_cell(field_name: str, value: object) -> str:
    if isinstance(value, list):
        return "、".join(str(_display_cell(field_name, item)) for item in value)
    if isinstance(value, tuple):
        return "、".join(str(_display_cell(field_name, item)) for item in value)
    if value is None:
        return "暂无数据"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, str):
        return _VALUE_LABELS.get(value, value)
    if isinstance(value, Number):
        numeric = float(value)
        if field_name == "relative_lift":
            if numeric > 0:
                return f"提升 {_format_percent(numeric)}"
            if numeric < 0:
                return f"下降 {_format_percent(abs(numeric))}"
            return "持平 0%"
        if _is_percent_field(field_name):
            return _format_percent(numeric)
        if field_name in _MONEY_FIELDS:
            return _format_number(numeric)
        return _format_number(numeric)
    return str(value)


def _is_percent_field(field_name: str) -> bool:
    return field_name in _PERCENT_FIELDS or field_name.endswith("_rate")


def _primary_evidence_value(result: AnalysisResult | None) -> str:
    if result is None or not result.findings:
        return "not_judgable"
    return result.findings[0].evidence_strength.value


def _first_row(result: AnalysisResult | None, table_name: str) -> dict[str, object] | None:
    if result is None:
        return None
    rows = result.tables.get(table_name, [])
    return rows[0] if rows else None


def _result_label(task_id: str, title: str) -> str:
    for group in _ANALYSIS_GROUPS:
        if task_id in group["tasks"]:
            return str(group["title"]).split("：", maxsplit=1)[0]
    return title


def _codex_questions(results: list[AnalysisResult]) -> list[str]:
    questions: list[str] = []
    sku = _top_cell(results, "product_opportunity_matrix", "product_opportunities", "sku_name")
    if sku:
        questions.append(f"为什么「{sku}」应该优先测试？")

    angle = _top_cell(results, "copy_angle_effect", "copy_effects", "copy_angle")
    if angle is None:
        angle = _top_cell(
            results,
            "content_portfolio_optimization",
            "portfolio_mix",
            "copy_angle",
        )
    if angle:
        questions.append(f"「{_display_cell('copy_angle', angle)}」文案角度下周应该怎么测？")

    candidate = _top_cell(results, "reshoot_repost_candidates", "reshoot_candidates", "title")
    if candidate:
        questions.append(f"为什么「{candidate}」适合重拍，而不是直接重发？")

    questions.extend(
        [
            "这份报告里最应该先执行哪三件事？",
            "哪些结论只是实验线索，还不能直接当成因果？",
            "为了让下次报告更准，我需要补哪些数据？",
        ]
    )
    return _dedupe(questions)[:6]


def _top_cell(
    results: list[AnalysisResult],
    task_id: str,
    table_name: str,
    field_name: str,
) -> object | None:
    for result in results:
        if result.task_id != task_id:
            continue
        row = _first_row(result, table_name)
        if row is None:
            return None
        return row.get(field_name)
    return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
