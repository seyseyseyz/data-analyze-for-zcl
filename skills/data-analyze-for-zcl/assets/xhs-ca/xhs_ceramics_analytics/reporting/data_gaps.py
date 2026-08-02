"""Merchant-facing data requests derived from blocked analysis modules.

The coverage layer speaks in internal task slugs and table names. This module turns
that audit state into a compact operator contract: what data to provide, the minimum
useful fields, and which analysis becomes available afterward. It never infers a gap
from prose and never exposes machine task identifiers to the report reader.
"""

from __future__ import annotations


_DATA_PACKAGES: tuple[
    tuple[str, str, tuple[tuple[str, str], ...]],
    ...,
] = (
    (
        "平台原始导出文件",
        "平台导出的原始 CSV 或 Excel 文件；保留原表头、店铺账号和日期，并说明每一行代表什么，不要先手工合并汇总",
        (("data_quality_check", "检查文件能否完整导入、哪些表为空、缺哪些关键内容，以及哪些指标可以使用"),),
    ),
    (
        "笔记从曝光到成交的数据",
        "笔记编号、标题、发布时间、曝光次数、阅读次数、点赞评论收藏、商品点击次数；如导出中有订单、成交额（GMV）和退款信息，也一起提供",
        (
            ("account_baseline", "账号平时发布多少笔记、通常有多少阅读"),
            ("note_funnel", "从看到笔记、阅读、点击商品到成交，每一步表现如何"),
            ("note_commercial_diagnosis", "哪些笔记贡献成交额，哪些笔记转化或退款异常"),
            ("reshoot_repost_candidates", "哪些笔记值得重新拍摄或再次发布"),
            ("weekly_business_review", "包含内容、商品和下一步动作的完整周复盘"),
        ),
    ),
    (
        "广告投放明细",
        "日期、投放平台、广告计划/单元/创意、花费、曝光、点击、订单、成交额（GMV）、平台记录的投入产出，以及对应的笔记、商品或规格编号（SKU）",
        (
            ("ad_data_quality_check", "检查广告数据是否齐全，能否和笔记或商品对应"),
            (
                "paid_traffic_efficiency",
                "看清广告从曝光、点击到成交的每一步，并计算千次曝光成本、单次点击成本、投入产出效率，判断哪些广告该加预算或减少预算",
            ),
        ),
    ),
    (
        "商品与规格（SKU）资料及每日销售明细",
        "日期、规格编号（SKU）/名称、商品编号、商品类别、价格、销量、成交额（GMV）、库存；如需分析退款，再提供支付时间和退款时间",
        (
            ("sku_counterfactual_lift", "比较笔记发布前后，相关商品规格的销量变化（只表示相关，不代表因果）"),
            ("content_response_curve", "查看笔记发布后不同天数内，相关商品的销量变化"),
            ("product_opportunity_matrix", "商品卖得快不快、是否有库存风险、哪些商品应优先经营"),
            ("sku_structure_diagnosis", "每个商品规格扣除退款后的价值、购买意向承接、退款异常和适合的价格区间"),
            ("refund_root_cause_diagnosis", "按是否发货、商品类别和价格区间，找到退款集中在哪里"),
        ),
    ),
    (
        "笔记内容标签（封面、场景、文案）",
        "笔记编号、封面构图、画面场景、文案表达角度，以及明确对应的商品或规格编号（SKU）",
        (
            ("cover_style_effect", "比较不同封面风格的表现"),
            ("copy_angle_effect", "比较不同文案表达角度的表现"),
            ("product_content_interaction", "找出哪些商品、封面和文案组合表现更好"),
            ("content_portfolio_optimization", "判断哪些类型的内容该多做、少做或继续保留"),
        ),
    ),
    (
        "评论明细",
        "评论编号、笔记编号、评论时间、评论正文；如能对应到商品或规格编号（SKU），也一起提供",
        (("comment_demand_mining", "了解用户想买什么、担心什么，以及后续内容可以回答哪些问题"),),
    ),
    (
        "安排一周测试所需的资料",
        "真实在售的商品规格（SKU）、准备测试的内容角度、可发布时间、主要观察指标、不能恶化的保护指标，以及何时停止测试",
        (("weekly_experiment_matrix", "制定一份基于真实商品和内容角度的七天测试计划"),),
    ),
    (
        "以往的测试记录",
        "测试编号、每次只改变了什么、原方案和新方案、测试日期、参与数量、主要结果、是否伤害其他重要指标，以及最终结论",
        (("hypothesis_knowledge_base", "汇总每周测试是否有效，沉淀以后可以重复使用的经验"),),
    ),
    (
        "店铺每日经营汇总",
        "日期、访客人数、商品点击、加入购物车、收藏商品、支付人数/订单数/件数、成交额（GMV）、退款金额和是否已发货",
        (
            ("core_business_diagnosis", "成交额、扣除退款后的收入、访客浏览深度，以及和店铺过去表现的对比"),
            ("demand_funnel_diagnosis", "从浏览商品、加入购物车到支付的每一步变化，以及商品收藏趋势"),
            ("channel_structure_diagnosis", "不同流量来源带来多少访客和成交，退款是否异常，哪类内容更有效"),
        ),
    ),
    (
        "搜索概览与搜索词明细",
        "日期范围、搜索词、搜索入口、曝光次数、点击次数/人数、支付人数/订单数、成交额（GMV）",
        (("search_efficiency_diagnosis", "比较不同搜索入口的效果，发现正在增长的搜索词，以及用户在哪一步流失"),),
    ),
    (
        "店铺人群与来源明细",
        "人群类型或进入店铺的页面、访客人数、点击人数、支付人数、成交额（GMV）；同时保留平台对人群的说明和统计日期范围",
        (("audience_structure_diagnosis", "看清不同人群从进店到成交的表现，以及哪些入口带来的顾客更有价值"),),
    ),
    (
        "退款明细与退款原因",
        "退款时间、支付时间、订单号、规格编号（SKU）、金额、是否已发货、退款类型、退款原因、商品类别和价格区间",
        (("refund_structure_diagnosis", "查看退款何时变多、集中在哪个环节和哪些商品，以及主要退款原因"),),
    ),
)

_KNOWN_TASKS = {
    task_id
    for _label, _fields, analyses in _DATA_PACKAGES
    for task_id, _analysis in analyses
}

_OPTIONAL_FIELD_PACKAGES: tuple[
    tuple[str, str, str, str, tuple[str, ...]],
    ...,
] = (
    (
        "笔记曝光数据",
        "每篇笔记的曝光次数",
        "计算从曝光到阅读的比例和每千次曝光带来的成交额，区分是曝光不足还是内容承接不足",
        "note_funnel",
        ("impressions",),
    ),
    (
        "笔记引流到直播间的数据",
        "笔记编号、进直播间次数、直播间支付金额",
        "看清哪些笔记为直播间带来访问和成交，以及不同笔记的直播引流效率",
        "note_funnel",
        ("to_live_count_optional", "to_live_gmv_optional"),
    ),
    (
        "笔记引流到店铺主页的数据",
        "笔记编号、进入店铺主页次数、进入店铺后产生的支付金额",
        "看清哪些笔记把用户带进店铺，以及这些访问最终带来多少成交",
        "note_funnel",
        ("to_shop_home_count_optional", "to_shop_home_gmv_optional"),
    ),
    (
        "视频观看质量数据",
        "视频时长、平均观看时长、完整观看比例",
        "比较哪些视频更能留住用户，并判断问题出在开头、内容长度还是后半段流失",
        "note_funnel",
        ("video_seconds_optional", "avg_read_seconds_optional", "completion_rate_pv_optional"),
    ),
    (
        "关注与弹幕互动数据",
        "每篇笔记带来的关注点击次数、弹幕数量",
        "识别哪些内容不仅有点赞收藏，还能带来关注和更深的即时互动",
        "note_funnel",
        ("follow_clicks_optional", "danmu_count_optional"),
    ),
    (
        "加入购物车数据",
        "每篇笔记带来的加购件数或加购人数，并保留平台原有统计口径",
        "补全从阅读、点击商品、加入购物车到支付的过程，找到用户主要流失在哪一步",
        "note_funnel",
        ("add_to_cart_units_optional",),
    ),
)

_OPTIONAL_SOURCE_PACKAGES: tuple[tuple[str, str, str, str], ...] = (
    (
        "活动日历",
        "日期、活动名称、活动类型、开始/结束时间，以及大促、上新、断货等说明",
        "把大促、上新、断货与经营波动对照，减少把活动影响误判成内容或商品效果",
        "calendar_events",
    ),
    (
        "笔记与商品规格的明确对应关系",
        "笔记编号、商品编号、规格编号（SKU），以及关系生效时间",
        "更可靠地比较笔记发布前后相关商品的销量变化，并分析商品与内容组合",
        "note_sku_links",
    ),
    (
        "退款原因明细",
        "订单号、规格编号（SKU）、退款时间、退款金额、退款原因和是否已发货",
        "从退款集中在哪里进一步看到为什么退款，区分物流、商品描述、价格和质量问题",
        "refund_reasons",
    ),
)


def _normalize_blocked(blocked_modules: object) -> list[tuple[str, str]]:
    if not isinstance(blocked_modules, (list, tuple)):
        return []
    output: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in blocked_modules:
        if isinstance(item, dict):
            slug = str(item.get("slug") or "").strip()
            reason = str(item.get("reason") or "").strip()
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            slug = str(item[0] or "").strip()
            reason = str(item[1] or "").strip()
        else:
            slug = str(item or "").strip()
            reason = ""
        if slug and slug not in seen:
            output.append((slug, reason))
            seen.add(slug)
    return output


def _cell(value: object) -> str:
    return " ".join(str(value or "").replace("|", "／").split())


def _has_value(rows: list[dict], field: str) -> bool:
    return any(field in row and row.get(field) is not None for row in rows)


def _optional_data_rows(result_tables: object) -> list[tuple[str, str, str]]:
    if not isinstance(result_tables, dict):
        return []

    output: list[tuple[str, str, str]] = []
    for label, fields, analysis, table_name, required_fields in _OPTIONAL_FIELD_PACKAGES:
        raw_rows = result_tables.get(table_name)
        rows = [row for row in (raw_rows or []) if isinstance(row, dict)]
        if rows and any(not _has_value(rows, field) for field in required_fields):
            output.append((label, fields, analysis))

    row_counts = result_tables.get("table_row_counts")
    count_rows = [row for row in (row_counts or []) if isinstance(row, dict)]
    if count_rows:
        available_tables = {
            str(row.get("table") or "").strip()
            for row in count_rows
            if (row.get("rows") or 0) > 0
        }
        output.extend(
            (label, fields, analysis)
            for label, fields, analysis, table_name in _OPTIONAL_SOURCE_PACKAGES
            if table_name not in available_tables
        )
    return output


def _markdown_table(rows: list[tuple[str, str, str]]) -> list[str]:
    lines = [
        "| 要补什么数据 | 至少要包含哪些内容 | 补齐后能看懂什么 |",
        "| --- | --- | --- |",
    ]
    lines.extend(
        f"| {_cell(label)} | {_cell(fields)} | {_cell(unlocked)} |"
        for label, fields, unlocked in rows
    )
    return lines


def data_gap_markdown(
    blocked_modules: object,
    *,
    result_tables: object = None,
) -> str:
    """Return required gaps plus supported optional analysis upgrades."""
    blocked = _normalize_blocked(blocked_modules)
    optional_rows = _optional_data_rows(result_tables)
    if not blocked and not optional_rows:
        return ""

    blocked_ids = {slug for slug, _reason in blocked}
    rows: list[tuple[str, str, str]] = []
    for label, fields, analyses in _DATA_PACKAGES:
        unlocked = [analysis for task_id, analysis in analyses if task_id in blocked_ids]
        if unlocked:
            rows.append((label, fields, "；".join(unlocked)))

    unknown_reasons = [
        reason
        for slug, reason in blocked
        if slug not in _KNOWN_TASKS and reason
    ]
    if any(slug not in _KNOWN_TASKS for slug, _reason in blocked):
        detail = "；".join(dict.fromkeys(unknown_reasons)) or "需确认原始输入表、字段和统计口径"
        rows.append(("其他待补数据", detail, "补齐阻断项后恢复对应分析模块"))

    lines: list[str] = [
        "## 缺哪些数据，补齐后能分析什么",
        "",
        "下面分成两类：第一类会直接影响当前分析，第二类不是必需项，但补充后可以看得更细。",
    ]
    if rows:
        lines.extend(
            [
                "",
                "### 当前缺失数据：补齐后才能完成对应分析",
                "",
                "补完后更新报告，就能得到右侧对应的分析。",
                "",
                *_markdown_table(rows),
            ]
        )
    if optional_rows:
        lines.extend(
            [
                "",
                "### 可选增强数据：补充后可以看得更细",
                "",
                "这些项目都在当前分析能力范围内；字段存在但数值确实为 0 时，不会被误报为缺失。",
                "",
                *_markdown_table(optional_rows),
            ]
        )
    return "\n".join(lines)
