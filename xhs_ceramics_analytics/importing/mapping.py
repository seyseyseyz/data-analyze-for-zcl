from rapidfuzz import fuzz, process

from xhs_ceramics_analytics.importing.profile import FileProfile


TABLE_SIGNATURES: dict[str, set[str]] = {
    "notes": {"note_id", "publish_time", "title", "reads", "likes", "collects"},
    "products": {"product_id", "product_name", "vessel_type", "series"},
    "skus": {"sku_id", "product_id", "sku_name", "price"},
    "orders": {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"},
    "comments": {"note_id", "comment_time", "comment_text"},
    "content_features": {"note_id", "composition_type", "scene_hint", "copy_angle"},
    "calendar_events": {"date", "event_type", "event_name", "severity"},
}


def guess_table_type(profile: FileProfile) -> str:
    observed = {column.lower() for column in profile.columns}
    scores = {
        table: len(signature & observed) / len(signature)
        for table, signature in TABLE_SIGNATURES.items()
    }
    return max(scores, key=scores.get)


def guess_field_mapping(profile: FileProfile, table_type: str) -> dict[str, str]:
    targets = TABLE_SIGNATURES[table_type]
    mapping: dict[str, str] = {}
    for target in targets:
        match = process.extractOne(target, profile.columns, scorer=fuzz.WRatio)
        if match and match[1] >= 80:
            mapping[target] = str(match[0])
    return mapping
