"""Human, merchant-facing names for every ``result.tables`` key — the single source
of truth both layers read.

The fact-layer HTML and the narrative provenance stamp used to name tables from two
different places, so the same table could read one way in the appendix and another
in a narrative footer. This module is the one map both import, so a table's name can
never diverge between layers (the recurring "narrative diverged from the fact layer"
meta-bug, applied to provenance). Pure, never raises: an unknown or non-string key
degrades to a readable form of the key itself so provenance always renders something.
"""
from __future__ import annotations

# key == the bare table name as the analysis engine keys result.tables.
TABLE_LABELS: dict[str, str] = {
    "table_row_counts": "导入数据检查",
    "daily_posts": "账号日发布与互动",
    "posting_windows": "最优发布窗口",
    "note_funnel": "笔记漏斗明细",
    "cover_effects": "封面效果对比",
    "copy_effects": "文案角度对比",
    "product_opportunities": "商品机会明细",
    "sku_lift": "SKU 销量响应",
    "response_windows": "内容响应窗口",
    "product_interactions": "商品与内容组合",
    "portfolio_mix": "内容组合占比",
    "comment_demands": "评论需求分组",
    "comment_emergent_themes": "涌现需求主题与异议",
    "experiment_plan": "下周实验排期",
    "reshoot_candidates": "重拍候选笔记",
    "hypotheses": "经营假设库",
    "weekly_sections": "周复盘模块",
    "ad_data_quality": "投放数据可用性",
    "paid_traffic_efficiency": "投放效率明细",
    "paid_spend_response": "投放弹性（花费→成交响应）",
    # --- 经营/搜索/人群/退款/渠道 深度诊断模块 ---
    "business_snapshot": "整体经营快照",
    "business_trend": "GMV 趋势与结构性变化",
    "business_self_benchmark": "自身历史基准分位",
    "event_activity_lift": "活动期抬升对比",
    "gmv_bridge": "增长归因（GMV 桥）",
    "demand_funnel_trend": "加购→成交漏斗趋势",
    "wishlist_demand_trend": "心愿单需求趋势",
    "carrier_structure": "载体 GMV 结构",
    "traffic_channel_structure": "流量渠道结构",
    "carrier_search_efficiency": "载体搜索效率",
    "search_conversion_trend": "搜索转化趋势",
    "search_term_opportunities": "高机会/高流失搜索词",
    "audience_composition": "人群构成",
    "audience_conversion": "人群转化",
    "audience_conversion_comparison": "新老客转化对比",
    "first_purchase_cycle_funnel": "首购周期漏斗",
    "audience_gmv_contribution": "人群 GMV 贡献",
    "sku_gmv_pareto": "SKU GMV 帕累托",
    "sku_category_mix": "SKU 类目结构",
    "sku_category_l2_mix": "二级品类营收与退款",
    "sku_refund_outliers": "高退款 SKU",
    "sku_conversion_and_aov": "SKU 加购转化与客单价",
    "sku_price_band_distribution": "价格带分布（SKU × GMV）",
    "sku_price_sweet_spot": "价格甜点（价格带 × 转化 × 退款）",
    "note_gmv_pareto": "笔记 GMV 帕累托",
    "note_conversion_outliers": "高流量低转化笔记",
    "note_refund_outliers": "高退款笔记",
    "note_referral_attribution": "笔记站外引流成交",
    "high_refund_notes": "高退款笔记",
    "refund_layer_breakdown": "退款分层拆解",
    "refund_trend": "退款趋势",
    "carrier_refund_comparison": "载体退款对比",
    "shop_source_structure": "店铺来源结构",
    "product_refund_concentration": "商品退款集中度",
    "channel_scale": "渠道规模结构",
    "channel_conversion": "渠道转化对比",
    "channel_refund": "渠道退款对比",
    "refund_by_category": "分品类退款",
    "refund_by_price_band": "分价格带退款",
    "refund_by_ship_stage": "分发货环节退款",
}


def table_label(name: object) -> str:
    """Human label for a table key, degrading an unknown key to a readable form of
    itself (underscores → spaces) exactly as the fact-layer table renderer does.
    Never raises: a non-string key is stringified first, so garbage yields a
    best-effort string rather than an exception."""
    key = str(name) if name is not None else ""
    return TABLE_LABELS.get(key, key.replace("_", " "))
