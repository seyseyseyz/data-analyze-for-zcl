"""Shared reader-facing labels and number formatters for the HTML report.

Extracted from html.py so reporting.charts can reuse them without importing
html.py (which imports charts -> would be circular).
"""
from __future__ import annotations

VALUE_LABELS = {
    "active": "进行中",
    "candidate_first_sku": "候选首个 SKU 关联",
    "capacity": "容量/尺寸需求",
    "collect_rate": "收藏率",
    "copy_angle": "文案角度",
    "avg_collect_rate": "平均收藏率",
    "avg_comment_rate": "平均评论率",
    "avg_like_rate": "平均点赞率",
    "avg_read_rate": "平均阅读率",
    "account_baseline": "账号基线",
    "ad_data_quality_check": "投放数据可用性检查",
    "ad_performance_daily": "投放效果表",
    "baseline": "账号基线",
    "calendar_events": "日历事件表",
    "campaign": "计划粒度",
    "comment_demand_mining": "评论需求挖掘",
    "comment_demand": "评论需求假设",
    "comments": "评论表",
    "content_portfolio_optimization": "内容组合优化",
    "content_response_curve": "内容响应窗口",
    "content_features": "内容特征表",
    "copy_angle_effect": "文案角度效果",
    "cover_style_effect": "封面风格效果",
    "creative": "创意粒度",
    "data_quality": "数据质量",
    "data_quality_check": "数据质量检查",
    "d0_1": "发布后 0-1 天",
    "d1_3": "发布后 1-3 天",
    "d4_7": "发布后 4-7 天",
    "d8_14": "发布后 8-14 天",
    "daily_sku_sales": "SKU 每日销售表",
    "funnel": "内容漏斗",
    "gift": "送礼角度",
    "gift_box": "礼盒场景",
    "high_collect_rate_low_read_ceiling": "收藏率高，但阅读还有提升空间",
    "hold": "保持预算",
    "hypothesis_knowledge_base": "经营假设库",
    "increase": "增加预算",
    "link": "购买入口需求",
    "lifestyle": "生活方式角度",
    "missing": "缺少数据",
    "needs_data": "需要补数据",
    "needs_more_content_or_data": "需要更多内容或数据验证",
    "needs_sales_data": "需要销售数据",
    "note_metrics": "笔记指标表",
    "notes": "笔记表",
    "orders": "订单表",
    "other": "其他需求",
    "paid_traffic_efficiency": "投放效率分析",
    "price": "价格需求",
    "product": "商品粒度",
    "product_opportunity": "商品机会",
    "product_content_interaction": "商品与内容交互",
    "product_opportunity_matrix": "商品机会矩阵",
    "products": "商品表",
    "promising_but_needs_more_reads": "有潜力，但阅读样本不足",
    "ready": "可用",
    "reduce": "减少预算",
    "reshoot_repost_candidates": "重拍与重发候选",
    "sales_response_present": "已有销售反馈",
    "single_product": "单品特写",
    "skus": "SKU 表",
    "sku_counterfactual_lift": "SKU 销量响应",
    "table_setting": "餐桌场景",
    "tables_loaded": "已加载数据表",
    "top_sku_units": "头部 SKU 销量",
    "unknown": "未知",
    "unit": "单元粒度",
    "weekly_business_review": "每周经营复盘",
    "weekly_experiment_matrix": "每周实验矩阵",
    # --- 载体 / 漏斗环节 / 口径来源枚举 ---
    "card": "商品卡",
    "note": "笔记",
    "visit_click": "访问→点击",
    "visit_pay": "访问→支付",
    "click_pay": "点击→支付",
    "pre_ship": "发货前",
    "post_ship": "发货后",
    "real": "真实计数",
    "count": "真实计数",
    "derived": "由率推算",
    # --- 搜索词分类 / 漏损类型 / 异常类型 ---
    "opportunity": "高机会词",
    "leak": "高流失词",
    "average": "中等词",
    "small_sample": "小样本词",
    "click_leak": "点击漏损",
    "conversion_leak": "转化漏损",
    "high_traffic_low_conv": "高流量低转化",
    "top_converter": "高转化标杆",
    # --- 退款结构口径轴与层级 ---
    "ship_stage": "发货阶段",
    "return_type": "退款类型",
    "return": "退货",
    # --- 证据强度枚举（与 _EVIDENCE_LABELS 对齐）---
    "not_judgable": "不可判断",
    # --- 数据源 / 数据表名（数据质量与复盘来源列）---
    "posts": "发布笔记数",
    "note_funnel": "笔记漏斗",
    "build_manifest": "构建清单",
    "mapping_diagnostics": "字段映射诊断",
    "business_overview": "经营数据总览",
    "business_overview_daily": "经营数据总览（按天）",
    "business_overview_monthly": "经营数据总览（按月）",
    "refund_overview": "退款总览",
    "search_overview": "搜索总览",
    "search_terms": "搜索词表",
    "shop_page_funnel": "店铺页漏斗",
    "shop_page_source": "店铺页来源",
    "sku_performance": "商品表现表",
    "traffic_source": "流量来源表",
}


def value_label(value: str) -> str:
    return VALUE_LABELS.get(value, value)


def format_percent(value: float) -> str:
    percent = value * 100
    decimals = 2 if abs(percent) < 10 else 1
    text = f"{percent:.{decimals}f}"
    if float(text) == 0:  # a tiny negative rounded to 0 → drop the stray minus sign
        text = text.replace("-", "")
    text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def format_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def format_money(value: float) -> str:
    """Grouped whole-yuan amount: ``1302239.01`` -> ``1,302,239``.

    The single reader-facing money rule, shared by the chart path (charts.py) and,
    via reporting.formatting.format_scalar, the table/key-number path — mirroring
    analysis.prose.money for prose. Summed GMV/spend carry spurious cents from
    ``paid_amount``; they are export noise, not signal, so every surface drops them.
    """
    return format_number(float(round(value)))


def format_cn_date(value: object) -> str | None:
    """Normalize a date-ish value to ISO ``YYYY-MM-DD``; ``None`` when not a date.

    Real exports carry dates as integer ``YYYYMMDD``, ISO strings, or datetime.
    Kept dependency-free here so both the table path (reporting.formatting) and
    the prose path (analysis.prose) can share one date normalizer.
    """
    text = str(value).strip()
    if "-" in text or "/" in text:
        return text[:10].replace("/", "-")
    digits = text.split(".", maxsplit=1)[0]  # 20260401.0 -> 20260401
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None
