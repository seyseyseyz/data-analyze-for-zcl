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
}


def value_label(value: str) -> str:
    return VALUE_LABELS.get(value, value)


def format_percent(value: float) -> str:
    percent = value * 100
    decimals = 2 if abs(percent) < 10 else 1
    text = f"{percent:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{text}%"


def format_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")
