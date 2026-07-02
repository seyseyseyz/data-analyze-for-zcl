import re

from rapidfuzz import fuzz

from xhs_ceramics_analytics.importing.profile import FileProfile


MIN_TABLE_CONFIDENCE = 0.25
MIN_FIELD_CONFIDENCE = 80

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
        "gmv_optional": {"成交金额", "GMV", "支付金额"},
        "roi_optional": {"ROI", "投产比"},
        "roas_optional": {"ROAS", "广告投产比"},
    },
}


def _normalize_column_name(column: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", column.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")


def guess_table_type(profile: FileProfile) -> str:
    observed = {_canonical_column_name(column) for column in profile.columns}
    scores = {
        table: len(signature & observed) / len(signature)
        for table, signature in TABLE_SIGNATURES.items()
    }
    table_type, score = max(scores.items(), key=lambda item: item[1])
    if score < MIN_TABLE_CONFIDENCE:
        raise ValueError(
            f"Could not guess table type for {profile.table_name!r}; "
            f"best match {table_type!r} scored {score:.2f}."
        )
    return table_type


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


def _canonical_column_name(column: str) -> str:
    normalized = _normalize_column_name(column)
    for table_aliases in FIELD_ALIASES.values():
        for target, aliases in table_aliases.items():
            normalized_aliases = {_normalize_column_name(alias) for alias in aliases}
            if normalized in normalized_aliases:
                return target
    return normalized


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
