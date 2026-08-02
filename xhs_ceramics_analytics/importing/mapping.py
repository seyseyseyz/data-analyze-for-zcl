import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from xhs_ceramics_analytics.importing.profile import FileProfile


MIN_TABLE_CONFIDENCE = 0.25
MIN_FIELD_CONFIDENCE = 80
MARGIN = 0.15


class AmbiguousTableTypeError(ValueError):
    """Raised when two table types score within ``MARGIN`` of each other."""


TABLE_SIGNATURES: dict[str, set[str]] = {
    "notes": {"note_id", "publish_time", "title", "reads", "likes", "collects"},
    "products": {"product_id", "product_name", "vessel_type", "series"},
    "skus": {"sku_id", "product_id", "sku_name", "price"},
    "orders": {
        "order_id",
        "paid_time",
        "sku_id",
        "quantity",
        "paid_amount",
        "refund_status_optional",
    },
    "comments": {"note_id", "comment_time", "comment_text"},
    "content_features": {"note_id", "composition_type", "scene_hint", "copy_angle"},
    "note_sku_links": {"note_id", "sku_id"},
    "refund_reasons": {"refund_reason", "refund_amount", "refund_orders"},
    "calendar_events": {"date", "event_type", "event_name", "severity"},
    "ad_performance_daily": {
        "date",
        "spend",
        "impressions",
        "clicks",
        "campaign_name_optional",
    },
    "business_overview_daily": {"date", "gmv", "paid_orders", "paid_buyers", "aov"},
    "sku_performance": {"sku_id", "net_gmv_pay", "refund_rate_pay", "add_to_cart_users"},
    "search_overview": {
        "date",
        "carrier",
        "card_impression_users",
        "product_click_rate",
        "pay_conversion",
    },
    "search_terms": {
        "search_term",
        "card_impression_users",
        "product_click_rate",
        "pay_conversion",
    },
    "shop_page_funnel": {"shop_visitors", "shop_payers", "first_purchase_cycle"},
    "shop_page_source": {"source_page", "shop_visitors", "enter_pay_rate"},
    "refund_overview": {
        "carrier",
        "pre_ship_refund_amount",
        "return_refund_amount",
        "refund_users",
    },
    "traffic_source": {"xhs_id", "channel", "product_clicks", "product_click_users"},
}

FIELD_ALIASES: dict[str, dict[str, set[str]]] = {
    "note_sku_links": {
        "note_id": {"笔记ID", "笔记id"},
        "sku_id": {"规格ID", "规格id", "SKU ID", "sku_id"},
    },
    "refund_reasons": {
        "refund_reason": {"退款原因", "售后原因"},
        "refund_amount": {"退款金额"},
        "refund_orders": {"退款订单数", "退款单数"},
    },
    "calendar_events": {
        "date": {"日期", "事件日期"},
        "event_type": {"事件类型", "活动类型"},
        "event_name": {"事件名称", "活动名称"},
        "severity": {"影响等级", "严重程度", "事件等级"},
        "affected_product_id_optional": {"关联商品ID", "影响商品ID"},
        "affected_sku_id_optional": {"关联规格ID", "关联SKU ID", "影响规格ID"},
        "notes": {"备注", "事件备注"},
    },
    "comments": {
        "note_id": {"笔记ID", "笔记id"},
        "comment_time": {"评论时间", "留言时间"},
        "comment_text": {"评论内容", "评论文本", "留言内容"},
        "comment_id": {"评论ID", "评论id"},
        "parent_comment_id": {"父评论ID", "上级评论ID"},
        "comment_like_count": {"评论点赞数", "点赞数"},
        "author_id_hash": {"评论用户哈希", "用户ID哈希"},
    },
    "content_features": {
        "note_id": {"笔记ID", "笔记id"},
        "vessel_type_visible": {"可见器型", "封面器型"},
        "composition_type": {"封面构图", "构图类型"},
        "product_area_ratio_band": {"商品面积占比", "商品面积档位"},
        "shooting_angle": {"拍摄角度"},
        "background_material": {"背景材质"},
        "lighting_style": {"光线风格", "布光风格"},
        "color_temperature": {"色温"},
        "saturation_band": {"饱和度档位"},
        "contrast_band": {"对比度档位"},
        "scene_hint": {"场景提示", "场景线索"},
        "human_hand_visible": {"是否露手", "手部是否可见"},
        "food_drink_visible": {"是否有食物饮品", "食物饮品是否可见"},
        "text_overlay_present": {"是否有封面字", "封面文字"},
        "text_overlay_length_band": {"封面字数档位"},
        "aesthetic_semantics": {"审美语义", "视觉风格"},
        "copy_angle": {"文案角度", "内容角度"},
        "purchase_motive": {"购买动机"},
        "craft_terms_present": {"是否包含工艺词"},
        "scene_terms_present": {"是否包含场景词"},
        "gift_terms_present": {"是否包含送礼词"},
        "scarcity_terms_present": {"是否包含稀缺词"},
        "price_explanation_present": {"是否解释价格"},
        "title_length_band": {"标题长度档位"},
        "specific_noun_density_band": {"具体名词密度档位"},
        "emotional_intensity_band": {"情绪强度档位"},
        "call_to_action_type": {"行动引导类型", "CTA类型"},
    },
    "orders": {
        "order_id": {"订单号", "订单编号", "订单id"},
        "paid_time": {"支付时间", "付款时间", "成交时间"},
        "sku_id": {"规格id", "sku id", "skuid"},
        "quantity": {"商品数量", "购买数量", "数量"},
        "paid_amount": {"支付金额", "实付金额", "成交金额", "订单金额"},
        "refund_status_optional": {"退款状态", "售后状态"},
    },
    "notes": {
        "note_id": {"笔记id", "笔记ID"},
        "publish_time": {"发布时间", "笔记发布时间", "笔记创建时间", "创建时间"},
        "title": {"笔记标题", "标题"},
        "reads": {"阅读次数", "笔记阅读数", "阅读数"},
        "likes": {"点赞数", "点赞次数"},
        "collects": {"收藏数", "收藏次数"},
        "comments": {"评论数", "评论次数"},
        "shares": {"分享数", "分享次数"},
        "impressions": {"曝光数", "曝光次数", "展现数"},
        "note_type": {"笔记类型"},
        "related_product_id": {"关联商品ID"},
        "related_product_name": {"关联商品名称"},
        "video_seconds": {"视频时长"},
        "note_gmv": {"笔记支付金额"},
        "note_paid_orders": {"笔记支付订单数"},
        "note_paid_buyers": {"笔记支付人数"},
        "product_clicks": {"笔记商品点击次数"},
        "product_click_rate_pv": {"笔记商品点击率（PV）"},
        "product_click_users": {"笔记商品点击人数"},
        "pay_conversion_pv": {"支付转化率（PV）"},
        "pay_conversion_uv": {"支付转化率（UV）"},
        "note_refund_amount_pay": {"笔记退款金额（支付时间）"},
        "note_refund_rate_pay": {"笔记退款率（支付时间）"},
        "note_refund_orders_pay": {"笔记退款订单数（支付时间）"},
        "add_to_cart_units": {"加购件数"},
        "to_shop_home_count": {"进店次数"},
        "to_shop_home_gmv": {"进店支付金额"},
        "to_live_count": {"进直播间次数"},
        "to_live_gmv": {"直播间支付金额"},
        "follow_clicks": {"关注按钮点击次数"},
        "danmu_count": {"弹幕数"},
        "avg_read_seconds": {"人均阅读时长"},
        "completion_rate_pv": {"完播率（PV）"},
    },
    "skus": {
        "sku_id": {"规格id", "规格ID", "skuid"},
        "product_id": {"商品id", "商品ID"},
        "sku_name": {"规格名称", "sku名称"},
        "price": {"价格", "售价", "销售价格", "规格价格"},
        "inventory_optional": {"库存", "可售库存"},
    },
    "products": {
        "product_id": {"商品id", "商品ID"},
        "product_name": {"商品名称", "商品名"},
        "category": {"商品类目", "类目", "分类"},
        "vessel_type": {"器型", "品类"},
        "series": {"系列", "商品系列"},
        "status": {"商品状态", "状态"},
    },
    "ad_performance_daily": {
        "date": {"日期", "时间", "投放日期", "数据日期"},
        "platform_source": {"平台", "来源", "投放平台"},
        "campaign_id_optional": {"计划ID", "计划id", "推广计划ID"},
        "campaign_name_optional": {"计划名称", "推广计划", "投放计划"},
        "unit_id_optional": {"单元ID", "广告单元ID"},
        "unit_name_optional": {"单元名称", "广告单元"},
        "creative_id_optional": {"创意ID", "素材ID"},
        "creative_name_optional": {"创意名称", "素材名称", "笔记标题"},
        "note_id_optional": {"笔记ID", "笔记id"},
        "note_url_optional": {"笔记链接", "推广链接", "落地页链接"},
        "product_id_optional": {"商品ID", "商品id"},
        "sku_id_optional": {"SKU ID", "sku_id", "规格ID"},
        "spend": {"消耗", "花费", "广告消耗", "投放消耗"},
        "impressions": {"曝光", "展现", "展现量", "曝光量"},
        "clicks": {"点击", "点击量"},
        "ctr": {"点击率", "CTR"},
        "cpc": {"平均点击成本", "CPC"},
        "cpm": {"千次曝光成本", "CPM"},
        "conversions_optional": {"转化数", "成交人数", "转化人数"},
        "orders_optional": {"成交订单数", "订单数", "支付订单数"},
        # 成交金额/支付金额 also alias orders.paid_amount; _table_scoped_hits only counts
        # matches within this table's own signature, so guess_table_type relies on the
        # other ad-signature columns to disambiguate.
        "gmv_optional": {"成交金额", "GMV", "支付金额"},
        "roi_optional": {"ROI", "投产比"},
        "roas_optional": {"ROAS", "广告投产比"},
    },
    "business_overview_daily": {
        "date": {"时间", "日期"},
        "gmv": {"支付金额"},
        "note_gmv": {"笔记支付金额"},
        "card_gmv": {"商卡支付金额"},
        "paid_orders": {"支付订单数"},
        "note_paid_orders": {"笔记支付订单数"},
        "card_paid_orders": {"商卡支付订单数"},
        "paid_buyers": {"支付买家数"},
        "product_visitors": {"商品访客数", "商品访问人数"},
        "aov": {"客单价"},
        "paid_units": {"支付件数"},
        "pay_conversion": {"支付转化率"},
        "pay_conversion_pv": {"支付转化率（PV）"},
        "pay_conversion_uv": {"支付转化率（UV）"},
        "add_to_cart_users": {"加购人数"},
        "add_to_cart_units": {"加购件数"},
        "refund_amount_pay": {"退款金额（支付时间）"},
        "refund_rate_pay": {"退款率（支付时间）"},
        "refund_orders_pay": {"退款订单数（支付时间）"},
        "pre_ship_refund_rate_pay": {"发货前退款率（支付时间）"},
        "post_ship_refund_rate_pay": {"发货后退款率（支付时间）"},
        "net_gmv_pay": {"退款后支付金额（支付时间）"},
        "refund_amount_refundtime": {"退款金额（退款时间）"},
        "total_visitors": {"总访客数"},
        "total_pv": {"总浏览量"},
        "product_click_rate_pv": {"商品点击率（PV）"},
        "new_add_to_cart_users": {"新增加购人数"},
        "new_wishlist_users": {"新增加入心愿单人数"},
        "refund_order_share_refundtime": {"退款订单占比（退款时间）"},
        "note_paid_buyers": {"笔记支付买家数"},
        "card_paid_buyers": {"商卡支付买家数"},
        "note_product_visitors": {"笔记商品访客数"},
        "card_product_visitors": {"商卡商品访客数"},
        "note_pay_conversion": {"笔记支付转化率"},
        "card_pay_conversion": {"商卡支付转化率"},
        "note_aov": {"笔记客单价"},
        "card_aov": {"商卡客单价"},
        "note_net_gmv_pay": {"笔记退款后支付金额（支付时间）"},
        "card_net_gmv_pay": {"商卡退款后支付金额（支付时间）"},
        "note_refund_orders_pay": {"笔记退款订单数（支付时间）"},
        "card_refund_orders_pay": {"商卡退款订单数（支付时间）"},
        "note_refund_rate_pay": {"笔记退款率（支付时间）"},
        "card_refund_rate_pay": {"商卡退款率（支付时间）"},
        "note_pre_ship_refund_rate_pay": {"笔记发货前退款率（支付时间）"},
        "card_pre_ship_refund_rate_pay": {"商卡发货前退款率（支付时间）"},
        "note_post_ship_refund_rate_pay": {"笔记发货后退款率（支付时间）"},
        "card_post_ship_refund_rate_pay": {"商卡发货后退款率（支付时间）"},
    },
    "sku_performance": {
        "sku_id": {"规格ID", "规格id"},
        "sku_name": {"规格名称"},
        "product_id": {"商品ID", "商品id"},
        "product_name": {"商品名称"},
        "is_channel_product": {"是否渠道商品"},
        "barcode": {"条形码", "商品条码"},
        "category_l1": {"一级品类"},
        "category_l2": {"二级品类"},
        "brand": {"品牌"},
        "add_to_cart_users": {"加购人数", "新增加购人数"},
        "add_to_cart_units": {"加购件数"},
        "wishlist_users": {"想要人数", "收藏人数"},
        "gmv": {"支付金额"},
        "paid_buyers": {"支付买家数"},
        "paid_orders": {"支付订单数"},
        "paid_units": {"支付件数"},
        "aov": {"客单价"},
        "refund_amount_pay": {"退款金额（支付时间）"},
        "refund_rate_pay": {"退款率（支付时间）"},
        "refund_orders_pay": {"退款订单数（支付时间）"},
        "pre_ship_refund_rate_pay": {"发货前退款率（支付时间）"},
        "post_ship_refund_rate_pay": {"发货后退款率（支付时间）"},
        "net_gmv_pay": {"退款后支付金额（支付时间）"},
        "refund_amount_refundtime": {"退款金额（退款时间）"},
        "refund_rate_refundtime": {"退款率（退款时间）"},
    },
    "search_overview": {
        "date": {"日期", "时间"},
        "carrier": {"载体"},
        "gmv": {"支付金额"},
        "paid_orders": {"支付订单数"},
        "paid_buyers": {"支付买家数"},
        "card_impression_users": {"商卡曝光人数"},
        "product_click_users": {"商品点击人数"},
        "product_click_rate": {"商品点击率"},
        "pay_conversion": {"支付转化率"},
    },
    "search_terms": {
        "search_term": {"搜索词"},
        "gmv": {"支付金额"},
        "paid_orders": {"支付订单数"},
        "paid_buyers": {"支付买家数"},
        "card_impression_users": {"商卡曝光人数"},
        "product_click_users": {"商品点击人数"},
        "product_click_rate": {"商品点击率"},
        "pay_conversion": {"支付转化率"},
    },
    "shop_page_funnel": {
        "date": {"时间", "日期"},
        "audience_type": {"人群类型"},
        "first_purchase_cycle": {"首购周期"},
        "shop_visitors": {"店铺页访问人数"},
        "product_click_users": {"商品点击人数"},
        "shop_payers": {"店铺页支付人数"},
        "visit_click_rate": {"访问点击转化率"},
        "click_pay_rate": {"点击支付率"},
        "visit_pay_rate": {"访问支付率"},
    },
    "shop_page_source": {
        "date": {"时间", "日期"},
        "audience_type": {"人群类型"},
        "first_purchase_cycle": {"首购周期"},
        "source_page": {"来源页面"},
        "shop_gmv": {"店铺页支付金额"},
        "shop_visitors": {"店铺页访问人数"},
        "enter_pay_rate": {"进店支付转化率"},
        "gmv_per_user": {"人均支付金额"},
    },
    "refund_overview": {
        "stat_period": {"统计时间"},
        "account_type": {"账号类型"},
        "account_name": {"账号名称"},
        "carrier": {"载体"},
        "refund_amount_pay": {"退款金额（支付时间）"},
        "post_ship_refund_amount": {"发货后退款金额（支付时间）"},
        "shipped_refundonly_amount": {"发货后仅退款金额（支付时间）"},
        "pre_ship_refund_amount": {"发货前退款金额（支付时间）"},
        "return_refund_amount": {"退货退款金额（支付时间）"},
        "refund_orders_pay": {"退款订单数（支付时间）"},
        "post_ship_refund_orders": {"发货后退款订单数（支付时间）"},
        "shipped_refundonly_orders": {"发货后仅退款订单数（支付时间）"},
        "pre_ship_refund_orders": {"发货前退款订单数（支付时间）"},
        "return_refund_orders": {"退货退款订单数（支付时间）"},
        "refund_rate_pay": {"退款率（支付时间）"},
        "post_ship_refund_rate_pay": {"发货后退款率（支付时间）"},
        "pre_ship_refund_rate_pay": {"发货前退款率（支付时间）"},
        "return_refund_rate_pay": {"退货退款率（支付时间）"},
        "refund_users": {"退款人数（支付时间）", "退款人数"},
    },
    "traffic_source": {
        "xhs_id": {"小红书号"},
        "account_name": {"账号名称"},
        "channel": {"渠道"},
        "note_type": {"笔记类型"},
        "gmv": {"支付金额"},
        "paid_orders": {"支付订单数"},
        "paid_buyers": {"支付人数"},
        "product_clicks": {"商品点击次数"},
        "product_click_users": {"商品点击人数"},
        "pay_conversion_pv": {"支付转化率（PV）"},
        "pay_conversion_uv": {"支付转化率（UV）"},
    },
}


# Types listed here coalesce on their grain key (one row per key, first-non-null
# per column). Types NOT listed (orders, products, skus, comments, calendar_events,
# content_features, ad_performance_daily) plain-union across files.
GRAIN_KEYS: dict[str, tuple[str, ...]] = {
    "notes": ("note_id",),
    "business_overview_daily": ("date",),
    "sku_performance": ("sku_id",),
    "search_overview": ("date", "carrier"),
    "search_terms": ("search_term",),
    "shop_page_funnel": ("date", "audience_type", "first_purchase_cycle"),
    "shop_page_source": ("date", "audience_type", "first_purchase_cycle", "source_page"),
    "refund_overview": ("stat_period", "account_name", "carrier"),
    "traffic_source": ("xhs_id", "channel", "note_type"),
    "note_sku_links": ("note_id", "sku_id"),
    "refund_reasons": ("refund_reason",),
}


# Downstream hard-dependencies by canonical name: grain keys (a missing grain key
# corrupts the coalesce in _combine_frames) plus every column a built mart/task SELECTs.
# Made explicit — NOT derived from the classification signature (chosen for discrimination,
# omits mart-consumed columns like net_gmv_pay) nor the `_optional` convention (the new
# §2/§5/§6/§7 tables do not use it). Enforced by test_required_columns_invariants.
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "notes": {
        "note_id",
        "publish_time",
        "title",
        "reads",
        "impressions",
        "likes",
        "collects",
        "comments",
    },
    "products": {"product_id", "product_name", "vessel_type", "series"},
    "skus": {"sku_id", "product_id", "sku_name", "price"},
    "orders": {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"},
    "comments": {"note_id", "comment_time", "comment_text"},
    "content_features": {"note_id", "composition_type", "scene_hint", "copy_angle"},
    "note_sku_links": {"note_id", "sku_id"},
    "refund_reasons": {"refund_reason", "refund_amount", "refund_orders"},
    "calendar_events": {"date", "event_type", "event_name", "severity"},
    "ad_performance_daily": {"date", "spend", "impressions", "clicks"},
    "business_overview_daily": {
        "date",
        "gmv",
        "paid_orders",
        "paid_buyers",
        "aov",
        "paid_units",
        "refund_amount_pay",
        "net_gmv_pay",  # mart-SUM deps, NOT in signature
    },
    "sku_performance": {"sku_id", "net_gmv_pay", "refund_rate_pay", "add_to_cart_users"},
    "search_overview": {
        "date",
        "carrier",
        "gmv",
        "paid_orders",
        "card_impression_users",
        "product_click_rate",
        "pay_conversion",
    },
    "search_terms": {
        "search_term",
        "gmv",
        "card_impression_users",
        "product_click_rate",
        "pay_conversion",
    },
    "shop_page_funnel": {
        "date",
        "audience_type",
        "first_purchase_cycle",
        "shop_visitors",
        "shop_payers",
    },
    "shop_page_source": {
        "date",
        "audience_type",
        "first_purchase_cycle",
        "source_page",
        "shop_visitors",
        "enter_pay_rate",
    },
    "refund_overview": {
        "stat_period",
        "account_name",
        "carrier",
        "refund_amount_pay",
        "refund_users",
        "refund_rate_pay",
        "pre_ship_refund_amount",
        "post_ship_refund_amount",
        "return_refund_amount",
    },
    "traffic_source": {
        "xhs_id",
        "channel",
        "note_type",
        "gmv",
        "paid_orders",
        "product_clicks",
        "product_click_users",
    },
}


_FULLWIDTH_PUNCT = str.maketrans(
    {
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "，": ",",
        "、": ",",
        "：": ":",
        # NB: U+3000 ideographic space is NOT listed — the existing `\s` below is
        # Unicode-aware and already collapses it.
    }
)


def _normalize_column_name(column: str) -> str:
    folded = column.translate(_FULLWIDTH_PUNCT)
    normalized = re.sub(r"[\s\-]+", "_", folded.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")


def guess_table_type(profile: FileProfile) -> str:
    hits = {table: _table_scoped_hits(profile.columns, table) for table in TABLE_SIGNATURES}
    scores = {table: hits[table] / len(signature) for table, signature in TABLE_SIGNATURES.items()}
    if hits.get("note_sku_links", 0) < 2:
        scores["note_sku_links"] = 0.0
    refund_reason_mapping = _resolve_mapping(
        profile,
        "refund_reasons",
        FIELD_ALIASES.get("refund_reasons", {}),
    )
    if "refund_reason" not in refund_reason_mapping:
        scores["refund_reasons"] = 0.0
    # Rank by normalized coverage, breaking ties by raw hit count: a type that
    # matches MORE of the file's actual columns is the better fit even when a
    # smaller signature ties it on coverage. Without this, a column-sparse notes
    # file [note_id, publish_time] scores notes 2/6 == comments 1/3 (comments'
    # note_id self-matches its target name) and is wrongly called ambiguous.
    ranked = sorted(
        scores.items(),
        key=lambda item: (item[1], hits[item[0]]),
        reverse=True,
    )
    table_type, score = ranked[0]
    runner_up_type, runner_up = (ranked[1][0], ranked[1][1]) if len(ranked) > 1 else ("", 0.0)
    if score < MIN_TABLE_CONFIDENCE:
        raise ValueError(
            f"Could not guess table type for {profile.table_name!r}; "
            f"best match {table_type!r} scored {score:.2f}."
        )
    # Only a genuine collision — within MARGIN AND matching no more real columns
    # than the runner-up — is ambiguous. A strictly higher raw-hit count resolves
    # the normalization artifact above.
    if score - runner_up < MARGIN and hits[table_type] <= hits.get(runner_up_type, 0):
        raise AmbiguousTableTypeError(
            f"Ambiguous table type for {profile.table_name!r}: "
            f"{table_type!r} ({score:.2f}, {hits[table_type]} hits) vs "
            f"{runner_up_type!r} ({runner_up:.2f}, {hits.get(runner_up_type, 0)} hits)."
        )
    return table_type


def _table_scoped_hits(columns: list[str], table_type: str) -> int:
    source_columns = [(column, _normalize_column_name(column)) for column in columns]
    signature = TABLE_SIGNATURES[table_type]
    table_aliases = FIELD_ALIASES.get(table_type, {})
    return sum(
        1
        for target in signature
        if _alias_source_column(source_columns, target, table_aliases.get(target, set()), set())
        is not None
    )


@dataclass(frozen=True)
class ColumnDiagnostic:
    table_type: str
    required_column: str
    status: str  # "missing" | "ambiguous"
    candidate_sources: tuple[str, ...]  # unmapped source headers (agent candidate pool)
    reason: str  # Chinese, operator-facing
    action: str  # Chinese, what to do
    source_column: str | None = None
    match_method: str | None = None
    match_score: float | None = None
    platform_metric_ids: tuple[int, ...] = ()
    semantic_status: str | None = None


@dataclass(frozen=True)
class ColumnDecision:
    table_type: str
    canonical_column: str
    source_column: str
    match_method: str
    match_score: float | None
    semantic_status: str
    platform_metric_ids: tuple[int, ...]
    applied: bool
    reason: str


@dataclass(frozen=True)
class _ResolvedColumn:
    canonical_column: str
    source_column: str
    match_method: str
    match_score: float | None


@dataclass(frozen=True)
class ColumnMapping:
    mapping: dict[str, str]  # canonical -> source, exactly as guess_field_mapping returned
    diagnostics: tuple[ColumnDiagnostic, ...]
    decisions: tuple[ColumnDecision, ...] = ()


def _effective_aliases(
    table_type: str,
    overrides: dict[str, dict[str, set[str]]],
) -> dict[str, set[str]]:
    """Shipped FIELD_ALIASES unioned with learned overrides. Overrides only ADD."""
    merged: dict[str, set[str]] = {
        target: set(aliases) for target, aliases in FIELD_ALIASES.get(table_type, {}).items()
    }
    for target, aliases in overrides.get(table_type, {}).items():
        merged.setdefault(target, set()).update(aliases)
    return merged


def _resolve_mapping(
    profile: FileProfile,
    table_type: str,
    aliases: dict[str, set[str]],
) -> dict[str, str]:
    return {
        resolved.canonical_column: resolved.source_column
        for resolved in _resolve_mapping_candidates(profile, table_type, aliases, {})
    }


def _resolve_mapping_candidates(
    profile: FileProfile,
    table_type: str,
    shipped_aliases: dict[str, set[str]],
    override_aliases: dict[str, set[str]],
) -> list[_ResolvedColumn]:
    targets = (
        TABLE_SIGNATURES[table_type]
        | set(shipped_aliases.keys())
        | set(override_aliases.keys())
    )
    source_columns = [(column, _normalize_column_name(column)) for column in profile.columns]
    used_sources: set[str] = set()
    resolved_targets: set[str] = set()
    resolved_columns: list[_ResolvedColumn] = []
    for target in sorted(targets):
        override_match = _alias_source_column(
            source_columns,
            target,
            override_aliases.get(target, set()),
            used_sources,
            include_target=False,
        )
        if override_match:
            resolved_columns.append(
                _ResolvedColumn(target, override_match, "operator_override", None)
            )
            used_sources.add(override_match)
            resolved_targets.add(target)
    for target in sorted(targets - resolved_targets):
        alias_match = _alias_source_column(
            source_columns,
            target,
            shipped_aliases.get(target, set()),
            used_sources,
        )
        if alias_match:
            resolved_columns.append(
                _ResolvedColumn(target, alias_match, "shipped_alias", None)
            )
            used_sources.add(alias_match)
            resolved_targets.add(target)
    for target in sorted(targets - resolved_targets):
        normalized_target = _normalize_column_name(target)
        candidates = [
            (fuzz.WRatio(normalized_target, normalized_source), source_column)
            for source_column, normalized_source in source_columns
            if source_column not in used_sources
        ]
        if not candidates:
            continue
        score, source_column = max(candidates, key=lambda candidate: candidate[0])
        if score >= MIN_FIELD_CONFIDENCE:
            resolved_columns.append(
                _ResolvedColumn(target, source_column, "fuzzy", float(score))
            )
            used_sources.add(source_column)
    return resolved_columns


def map_columns(
    profile: FileProfile,
    table_type: str,
    *,
    overrides: dict[str, dict[str, set[str]]] | None = None,
) -> ColumnMapping:
    supplied_overrides = overrides or {}
    resolved_columns = _resolve_mapping_candidates(
        profile,
        table_type,
        FIELD_ALIASES.get(table_type, {}),
        supplied_overrides.get(table_type, {}),
    )
    semantic_context = _platform_semantic_context()
    mapping: dict[str, str] = {}
    diagnostics: list[ColumnDiagnostic] = []
    decisions: list[ColumnDecision] = []
    blocked_targets: set[str] = set()
    for resolved in resolved_columns:
        semantic_status, platform_metric_ids, applied, reason = _assess_mapping_semantics(
            table_type,
            resolved,
            semantic_context,
        )
        decisions.append(
            ColumnDecision(
                table_type=table_type,
                canonical_column=resolved.canonical_column,
                source_column=resolved.source_column,
                match_method=resolved.match_method,
                match_score=resolved.match_score,
                semantic_status=semantic_status,
                platform_metric_ids=platform_metric_ids,
                applied=applied,
                reason=reason,
            )
        )
        if applied:
            mapping[resolved.canonical_column] = resolved.source_column
            continue
        blocked_targets.add(resolved.canonical_column)
        diagnostics.append(
            ColumnDiagnostic(
                table_type=table_type,
                required_column=resolved.canonical_column,
                status=semantic_status,
                candidate_sources=(resolved.source_column,),
                reason=reason,
                action="确认平台口径后写入 mapping_overrides.yaml，再重新构建",
                source_column=resolved.source_column,
                match_method=resolved.match_method,
                match_score=resolved.match_score,
                platform_metric_ids=platform_metric_ids,
                semantic_status=semantic_status,
            )
        )
    mapped_sources = set(mapping.values())
    leftover = tuple(column for column in profile.columns if column not in mapped_sources)
    for column in sorted(REQUIRED_COLUMNS.get(table_type, set())):
        if column in mapping or column in blocked_targets:
            continue
        # Status is computed purely from the leftover pool — no semantic guess here.
        # Non-empty pool: some header is present but unmatched (a drift the agent can
        # adjudicate). Empty pool: the column is genuinely absent, nothing to adjudicate.
        status = "ambiguous" if leftover else "missing"
        diagnostics.append(
            ColumnDiagnostic(
                table_type=table_type,
                required_column=column,
                status=status,
                candidate_sources=leftover,
                reason=f"必填列 {column} 未匹配到任何表头",
                action="确认口径后在 mapping_overrides.yaml 补别名",
            )
        )
    return ColumnMapping(
        mapping=mapping,
        diagnostics=tuple(diagnostics),
        decisions=tuple(decisions),
    )


def _platform_semantic_context() -> dict[str, object]:
    from xhs_ceramics_analytics.contracts.platform_catalog import (
        build_platform_semantic_context,
    )

    return build_platform_semantic_context()


def _reference_targets(reference: dict[str, object]) -> set[tuple[object, object]]:
    direct = {
        (reference.get("canonical_table"), reference.get("canonical_field"))
    }
    possible = {
        (item.get("canonical_table"), item.get("canonical_field"))
        for item in reference.get("possible_targets", [])
        if isinstance(item, dict)
    }
    return {target for target in direct | possible if all(target)}


def _reference_table_scope(reference: dict[str, object]) -> set[str]:
    from xhs_ceramics_analytics.contracts.platform_catalog import PLATFORM_MODULE_TABLES

    return {
        table
        for module in reference.get("modules", [])
        for table in PLATFORM_MODULE_TABLES.get(str(module), ())
    }


def _is_platform_table(table_type: str) -> bool:
    from xhs_ceramics_analytics.contracts.platform_catalog import PLATFORM_MODULE_TABLES

    return any(table_type in tables for tables in PLATFORM_MODULE_TABLES.values())


def _assess_mapping_semantics(
    table_type: str,
    resolved: _ResolvedColumn,
    context: dict[str, object],
) -> tuple[str, tuple[int, ...], bool, str]:
    accepted = [
        reference
        for reference in context.get("accepted_references", [])
        if isinstance(reference, dict)
    ]
    candidates = [
        reference
        for reference in context.get("reference_only_candidates", [])
        if isinstance(reference, dict)
    ]
    target = (table_type, resolved.canonical_column)
    accepted_for_target = [
        reference for reference in accepted if target in _reference_targets(reference)
    ]
    candidates_for_target = [
        reference for reference in candidates if target in _reference_targets(reference)
    ]
    normalized_source = _normalize_column_name(resolved.source_column)
    source_references = [
        reference
        for reference in [*accepted, *candidates]
        if _normalize_column_name(str(reference.get("display_name", "")))
        == normalized_source
    ]
    accepted_source_targets = [
        reference for reference in accepted_for_target if reference in source_references
    ]
    candidate_source_targets = [
        reference for reference in candidates_for_target if reference in source_references
    ]
    source_allows_target = any(
        target in _reference_targets(reference) for reference in source_references
    )
    source_conflicts_with_target = any(
        table_type in _reference_table_scope(reference)
        and target not in _reference_targets(reference)
        for reference in source_references
    )
    metric_ids = tuple(
        sorted(
            {
                int(reference["platform_metric_id"])
                for reference in [
                    *accepted_source_targets,
                    *candidate_source_targets,
                    *source_references,
                ]
                if reference.get("platform_metric_id") is not None
            }
        )
    )
    if resolved.match_method == "operator_override":
        return (
            "operator_confirmed",
            metric_ids,
            True,
            "mapping_overrides.yaml 已显式确认该字段映射",
        )
    if source_conflicts_with_target and not source_allows_target:
        return (
            "conflict",
            metric_ids,
            False,
            "源表头命中平台指标，但官方语义与目标 canonical 字段冲突",
        )
    if resolved.match_method == "fuzzy" and not _is_platform_table(table_type):
        return (
            "legacy_fuzzy",
            metric_ids,
            True,
            f"非平台目录表保留兼容性模糊匹配（score={resolved.match_score:.1f}）",
        )
    if resolved.match_method == "fuzzy":
        return (
            "review_required",
            metric_ids,
            False,
            f"仅字段名模糊匹配（score={resolved.match_score:.1f}），未获语义批准",
        )
    if accepted_source_targets:
        return "verified", metric_ids, True, "已命中审核通过的平台字段绑定"
    if candidate_source_targets:
        review_reasons = sorted(
            {
                str(review_reason)
                for reference in candidate_source_targets
                for review_reason in reference.get("review_reasons", [])
            }
        )
        return (
            "reference_only",
            metric_ids,
            True,
            "平台定义与目标字段一致，但绑定尚未审核：" + ", ".join(review_reasons),
        )
    if context.get("status") == "unavailable":
        return (
            "catalog_unavailable",
            (),
            True,
            "平台语义目录不可用，保留已发布的精确别名映射",
        )
    return (
        "no_platform_reference",
        metric_ids,
        True,
        "未找到平台指标引用，保留已发布的精确别名映射",
    )


def guess_field_mapping(profile: FileProfile, table_type: str) -> dict[str, str]:
    return map_columns(profile, table_type).mapping


def _alias_source_column(
    source_columns: list[tuple[str, str]],
    target: str,
    aliases: set[str],
    used_sources: set[str],
    *,
    include_target: bool = True,
) -> str | None:
    normalized_aliases = {_normalize_column_name(alias) for alias in aliases}
    if include_target:
        normalized_aliases.add(_normalize_column_name(target))
    for source_column, normalized_source in source_columns:
        if source_column not in used_sources and normalized_source in normalized_aliases:
            return source_column
    return None
