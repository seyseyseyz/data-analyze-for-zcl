from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_GROUPS = ("price", "link", "capacity", "gift", "other")
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "capacity": ("容量", "毫升", "ml", "多大", "尺寸", "装多少", "几毫升"),
    "price": ("价格", "多少钱", "多少元", "几元", "贵", "预算", "price"),
    "link": ("链接", "link", "购买", "下单", "店铺", "橱窗", "怎么买", "哪里买"),
    "gift": ("送", "礼物", "礼盒", "朋友", "生日", "新婚", "gift"),
}


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        comments = _fetch_comments(con) if _table_exists(con, "comments") else []
    finally:
        con.close()

    rows = _summarize_comments(comments)
    total_comments = sum(int(row["comments"]) for row in rows)
    detected_groups = [row["demand_group"] for row in rows if row["comments"]]
    top_group = detected_groups[0] if detected_groups else None

    limitations = [] if comments else ["No comment rows were available for demand mining."]
    caveats = [
        "Comment intent is keyword grouped and should be reviewed before changing product copy."
    ]
    if total_comments < 10:
        caveats.append("Small comment volume makes demand proportions directional only.")

    return AnalysisResult(
        task_id="comment_demand_mining",
        title="Comment Demand Mining",
        findings=[
            Finding(
                title="Comment demand groups extracted",
                conclusion=(
                    f"Grouped {total_comments} comments into "
                    f"{len(detected_groups)} observed demand buckets."
                ),
                evidence_strength=score_evidence(
                    total_comments, has_controls=False, confounder_count=1
                ),
                key_numbers={
                    "comments": total_comments,
                    "observed_groups": len(detected_groups),
                    "top_group": top_group,
                },
                caveats=caveats,
                recommended_action=(
                    "Use the top demand buckets to update note replies, product detail copy, "
                    "and next-week FAQ content."
                )
                if total_comments
                else "Collect more comments before changing demand assumptions.",
            )
        ],
        tables={"comment_demands": rows},
        limitations=limitations,
    )


def _fetch_comments(con) -> list[dict[str, str | None]]:
    columns = _table_columns(con, "comments")
    if "comment_text" not in columns:
        return []

    note_expr = "CAST(note_id AS VARCHAR)" if "note_id" in columns else "NULL"
    order_columns = [
        _quote_identifier(column)
        for column in ("comment_time", "note_id", "comment_text")
        if column in columns
    ]
    order_clause = f"ORDER BY {', '.join(order_columns)}" if order_columns else ""
    result = con.sql(
        f"""
        SELECT
          {note_expr} AS note_id,
          CAST(comment_text AS VARCHAR) AS comment_text
        FROM comments
        WHERE comment_text IS NOT NULL
        {order_clause}
        """
    )
    return [
        {"note_id": note_id, "comment_text": comment_text}
        for note_id, comment_text in result.fetchall()
    ]


def _summarize_comments(comments: list[dict[str, str | None]]) -> list[dict[str, object]]:
    grouped = {
        group: {"comments": 0, "note_ids": set(), "examples": []}
        for group in _GROUPS
    }
    for comment in comments:
        text = comment["comment_text"] or ""
        group = _classify_comment(text)
        bucket = grouped[group]
        bucket["comments"] += 1
        if comment["note_id"] is not None:
            bucket["note_ids"].add(comment["note_id"])
        if len(bucket["examples"]) < 3:
            bucket["examples"].append(text)

    total = len(comments)
    rows = []
    for group in _GROUPS:
        bucket = grouped[group]
        rows.append(
            {
                "demand_group": group,
                "comments": bucket["comments"],
                "notes": len(bucket["note_ids"]),
                "comment_share": round(bucket["comments"] / total, 4) if total else 0.0,
                "example_comments": list(bucket["examples"]),
            }
        )
    return sorted(rows, key=lambda row: (-int(row["comments"]), str(row["demand_group"])))


def _classify_comment(text: str) -> str:
    normalized = text.lower()
    for group in ("capacity", "price", "link", "gift"):
        if any(keyword in normalized for keyword in _KEYWORDS[group]):
            return group
    return "other"


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
