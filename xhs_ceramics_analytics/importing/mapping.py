import re

from rapidfuzz import fuzz

from xhs_ceramics_analytics.importing.profile import FileProfile


MIN_TABLE_CONFIDENCE = 0.25
MIN_FIELD_CONFIDENCE = 80

TABLE_SIGNATURES: dict[str, set[str]] = {
    "notes": {"note_id", "publish_time", "title", "reads", "likes", "collects"},
    "products": {"product_id", "product_name", "vessel_type", "series"},
    "skus": {"sku_id", "product_id", "sku_name", "price"},
    "orders": {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"},
    "comments": {"note_id", "comment_time", "comment_text"},
    "content_features": {"note_id", "composition_type", "scene_hint", "copy_angle"},
    "calendar_events": {"date", "event_type", "event_name", "severity"},
}


def _normalize_column_name(column: str) -> str:
    normalized = re.sub(r"[\s-]+", "_", column.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")


def guess_table_type(profile: FileProfile) -> str:
    observed = {_normalize_column_name(column) for column in profile.columns}
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
    targets = TABLE_SIGNATURES[table_type]
    source_columns = [
        (column, _normalize_column_name(column))
        for column in profile.columns
    ]
    used_sources: set[str] = set()
    mapping: dict[str, str] = {}
    for target in sorted(targets):
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
            mapping[target] = source_column
            used_sources.add(source_column)
    return mapping
