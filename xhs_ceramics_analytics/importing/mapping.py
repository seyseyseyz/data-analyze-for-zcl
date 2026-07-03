import re

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
        "refund_order_share_refundtime": {"退款订单占比（退款时间）"},
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
    hits = {
        table: _table_scoped_hits(profile.columns, table) for table in TABLE_SIGNATURES
    }
    scores = {
        table: hits[table] / len(signature)
        for table, signature in TABLE_SIGNATURES.items()
    }
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
    return sum(
        1
        for target in signature
        if _alias_source_column(source_columns, table_type, target, set()) is not None
    )


def guess_field_mapping(profile: FileProfile, table_type: str) -> dict[str, str]:
    targets = TABLE_SIGNATURES[table_type] | set(FIELD_ALIASES.get(table_type, {}).keys())
    source_columns = [
        (column, _normalize_column_name(column))
        for column in profile.columns
    ]
    used_sources: set[str] = set()
    mapping: dict[str, str] = {}
    for target in sorted(targets):
        normalized_target = _normalize_column_name(target)
        alias_match = _alias_source_column(source_columns, table_type, target, used_sources)
        if alias_match:
            mapping[target] = alias_match
            used_sources.add(alias_match)
            continue
        candidates = [
            (fuzz.WRatio(normalized_target, normalized_source), source_column)
            for source_column, normalized_source in source_columns
            if source_column not in used_sources
        ]
        if not candidates:
            continue

        score, source_column = max(candidates, key=lambda candidate: candidate[0])
        if score >= MIN_FIELD_CONFIDENCE:
            mapping[target] = source_column
            used_sources.add(source_column)
    return mapping


def _alias_source_column(
    source_columns: list[tuple[str, str]],
    table_type: str,
    target: str,
    used_sources: set[str],
) -> str | None:
    aliases = FIELD_ALIASES.get(table_type, {}).get(target, set())
    normalized_aliases = {_normalize_column_name(alias) for alias in aliases}
    normalized_aliases.add(_normalize_column_name(target))
    for source_column, normalized_source in source_columns:
        if source_column not in used_sources and normalized_source in normalized_aliases:
            return source_column
    return None
