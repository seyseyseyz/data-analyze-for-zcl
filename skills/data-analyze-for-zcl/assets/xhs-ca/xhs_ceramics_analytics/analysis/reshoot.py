from pathlib import Path

from xhs_ceramics_analytics.analytics.timeseries import iso_date
from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence
from xhs_ceramics_analytics.evidence import score_reliability


_MIN_CONFIDENT_READS = 50.0


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        metrics = _fetch_note_metrics(con) if _table_exists(con, "notes") else []
    finally:
        con.close()

    rows = _rank_candidates(metrics)
    # Surface the human-readable note TITLE (never the opaque 24-hex note_id, which
    # would render as a meaningless <strong>{id}</strong> stat card). Falls back to the
    # id only if a note has no title.
    top_candidate = (rows[0].get("title") or rows[0]["note_id"]) if rows else None

    return AnalysisResult(
        task_id="reshoot_repost_candidates",
        title="重拍与重发候选",
        findings=[
            Finding(
                title="高收藏笔记重拍候选已排序",
                conclusion=(
                    f"已完成 {qty(len(rows))} 篇笔记的重拍排序。排序综合收藏意向、"
                    "曝光阅读、商品点击、支付、内容年龄和退款风险。"
                ),
                evidence_strength=score_evidence(
                    len(metrics), has_controls=False, confounder_count=1
                ),
                descriptive_reliability=score_reliability(len(metrics)),
                key_numbers={
                    "candidate_notes": len(rows),
                    "top_candidate": top_candidate,
                },
                caveats=[
                    "重拍优先级仍需要创意复核：高收藏率可能代表小众强意图。",
                    "样本太少的笔记会被自动降权，想让它挤进队首，得先多攒些阅读数据再看。",
                    "商业指标缺失时不记为 0；退款仅用于风险降权，不证明内容造成退款。",
                ],
                recommended_action=(
                    "先重拍队首候选，用更清晰的开场画面做对照。确认阅读率提升后，再扩大重发。"
                )
                if rows
                else "先把笔记的阅读、收藏数据补齐，等能读到有效指标了再回来挑重拍候选。",
            )
        ],
        tables={"reshoot_candidates": rows},
        limitations=[] if rows else ["没有可用的笔记阅读/收藏指标。"],
    )


def _fetch_note_metrics(con) -> list[dict[str, object]]:
    columns = _table_columns(con, "notes")
    required = {"note_id", "reads", "collects"}
    if not required.issubset(columns):
        return []

    title_expr = "CAST(title AS VARCHAR)" if "title" in columns else "CAST(note_id AS VARCHAR)"
    optional = {
        name: f"CAST({name} AS DOUBLE)" if name in columns else "NULL"
        for name in (
            "impressions",
            "product_clicks",
            "note_paid_orders",
            "note_gmv",
            "note_refund_amount_pay",
        )
    }
    publish_time = "CAST(publish_time AS VARCHAR)" if "publish_time" in columns else "NULL"
    result = con.sql(
        f"""
        SELECT
          CAST(note_id AS VARCHAR) AS note_id,
          {title_expr} AS title,
          {publish_time} AS publish_time,
          {optional["impressions"]} AS impressions,
          CAST(reads AS DOUBLE) AS reads,
          CAST(collects AS DOUBLE) AS collects,
          {optional["product_clicks"]} AS product_clicks,
          {optional["note_paid_orders"]} AS note_paid_orders,
          {optional["note_gmv"]} AS note_gmv,
          {optional["note_refund_amount_pay"]} AS note_refund_amount_pay
        FROM notes
        WHERE reads IS NOT NULL
          AND collects IS NOT NULL
          AND reads > 0
        ORDER BY note_id
        """
    )
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _rank_candidates(metrics: list[dict[str, object]]) -> list[dict[str, object]]:
    if not metrics:
        return []

    max_reads = max(float(row["reads"]) for row in metrics)
    publish_dates = [iso_date(row.get("publish_time")) for row in metrics]
    publish_dates = [value for value in publish_dates if value is not None]
    latest_publish = max(publish_dates) if publish_dates else None
    ranked = []
    for row in metrics:
        reads = float(row["reads"])
        collects = float(row["collects"])
        collect_rate = collects / reads if reads else 0.0
        confidence_weight = reads / (reads + _MIN_CONFIDENT_READS)
        conservative_collect_rate = collect_rate * confidence_weight
        read_gap_to_max = (max_reads - reads) / max_reads if max_reads else 0.0
        needs_more_data = reads < _MIN_CONFIDENT_READS
        impressions = _optional_float(row.get("impressions"))
        product_clicks = _optional_float(row.get("product_clicks"))
        paid_orders = _optional_float(row.get("note_paid_orders"))
        note_gmv = _optional_float(row.get("note_gmv"))
        refund_amount = _optional_float(row.get("note_refund_amount_pay"))
        read_rate = reads / impressions if impressions else None
        read_to_product_click = product_clicks / reads if product_clicks is not None else None
        product_click_to_order = (
            paid_orders / product_clicks if product_clicks and paid_orders is not None else None
        )
        gmv_per_1k_impressions = (
            note_gmv * 1000 / impressions if impressions and note_gmv is not None else None
        )
        net_note_gmv = (
            note_gmv - refund_amount if note_gmv is not None and refund_amount is not None else None
        )
        refund_penalty = (
            max(0.0, min(refund_amount / note_gmv, 1.0))
            if note_gmv and refund_amount is not None
            else 0.0
        )
        published = iso_date(row.get("publish_time"))
        content_age_days = (
            (_as_date(latest_publish) - _as_date(published)).days
            if latest_publish and published
            else None
        )
        intent_bonus = min(read_to_product_click or 0.0, 1.0) * 0.5
        order_bonus = min(product_click_to_order or 0.0, 1.0) * 0.5
        age_bonus = min((content_age_days or 0) / 365, 1.0) * 0.1
        opportunity_score = (
            conservative_collect_rate * 100
            + read_gap_to_max * 0.25
            + intent_bonus
            + order_bonus
            + age_bonus
            - refund_penalty
        )
        ranked.append(
            {
                "note_id": row["note_id"],
                "title": row["title"],
                "reads": int(reads),
                "collects": int(collects),
                "collect_rate": round(collect_rate, 4),
                "impressions": impressions,
                "read_rate": _round_optional(read_rate),
                "product_clicks": product_clicks,
                "paid_orders": paid_orders,
                "read_to_product_click": _round_optional(read_to_product_click),
                "product_click_to_order": _round_optional(product_click_to_order),
                "note_gmv": note_gmv,
                "note_refund_amount_pay": refund_amount,
                "gmv_per_1k_impressions": _round_optional(gmv_per_1k_impressions),
                "net_note_gmv": net_note_gmv,
                "content_age_days": content_age_days,
                "refund_penalty": round(refund_penalty, 4),
                "conservative_collect_rate": round(conservative_collect_rate, 4),
                "confidence_weight": round(confidence_weight, 4),
                "read_gap_to_max": round(read_gap_to_max, 4),
                "opportunity_score": round(opportunity_score, 4),
                "needs_more_data": needs_more_data,
                "reason": (
                    "high_collect_rate_low_read_ceiling"
                    if not needs_more_data
                    else "promising_but_needs_more_reads"
                ),
            }
        )

    ranked.sort(
        key=lambda row: (
            bool(row["needs_more_data"]),
            -float(row["opportunity_score"]),
            -float(row["conservative_collect_rate"]),
            -float(row["collect_rate"]),
            -int(row["reads"]),
            str(row["note_id"]),
        )
    )
    return [{"rank": index, **row} for index, row in enumerate(ranked[:10], start=1)]


def _optional_float(value: object) -> float | None:
    return float(value) if value is not None else None


def _round_optional(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _as_date(value: str):
    from datetime import date

    return date.fromisoformat(value)


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
