from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.text_mining import (
    emergent_themes,
    objection_to_hook,
    polarity,
    theme_period_series,
)
from xhs_ceramics_analytics.analytics.timeseries import iso_week
from xhs_ceramics_analytics.analytics.trends import direction_from_summary, trend_summary
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence
from xhs_ceramics_analytics.evidence import score_reliability


_GROUPS = ("price", "link", "capacity", "gift", "other")
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "capacity": ("容量", "毫升", "ml", "多大", "尺寸", "装多少", "几毫升"),
    "price": ("价格", "多少钱", "多少元", "几元", "贵", "预算", "price"),
    "link": ("链接", "link", "购买", "下单", "店铺", "橱窗", "怎么买", "哪里买"),
    "gift": ("送", "礼物", "礼盒", "朋友", "生日", "新婚", "gift"),
}

# Ceramics-scene sentiment seeds — polarity aggregates comment tone per theme so a
# high-volume theme that is mostly complaints (色差/磕碰) reads differently from a
# high-volume demand (容量/链接). Deliberately small, high-precision seed tables.
_POS_LEXICON = (
    "好", "喜欢", "精致", "超值", "满意", "好看", "质量好", "回购", "推荐",
    "惊艳", "值得", "细腻", "有质感", "实用",
)
_NEG_LEXICON = (
    "色差", "磕碰", "破损", "失望", "划痕", "瑕疵", "掉色", "太小", "有裂",
    "开裂", "难看", "翻车", "退货", "货不对板", "味道",
)


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

    limitations = [] if comments else ["没有可用于需求挖掘的评论数据。"]
    caveats = [
        "评论意图基于关键词分组，调整商品文案前需要人工复核。"
    ]
    if total_comments < 10:
        caveats.append("评论量较小，需求占比只能作为方向性参考。")

    findings = [
        Finding(
            title="评论需求分组已提取",
            conclusion=(
                f"已将 {total_comments} 条评论归入 "
                f"{len(detected_groups)} 个有观测数据的需求分组。"
            ),
            evidence_strength=score_evidence(
                total_comments, has_controls=False, confounder_count=1
            ),
            descriptive_reliability=score_reliability(total_comments),
            key_numbers={
                "comments": total_comments,
                "observed_groups": len(detected_groups),
                "top_group": top_group,
            },
            caveats=caveats,
            recommended_action=(
                "用排名靠前的需求分组更新笔记回复、商品详情文案和下周 FAQ 内容。"
            )
            if total_comments
            else "先收集更多评论，再调整需求假设。",
        )
    ]
    tables: dict[str, list] = {"comment_demands": rows}

    theme_finding, theme_rows = _emergent_theme_finding(comments)
    if theme_finding is not None:
        findings.append(theme_finding)
        tables["comment_emergent_themes"] = theme_rows

    return AnalysisResult(
        task_id="comment_demand_mining",
        title="评论需求挖掘",
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _emergent_theme_finding(comments):
    """Emergent n-gram themes + per-theme polarity + objection→content-hook.

    Observational: themes are surfaced from what commenters actually wrote (not a
    fixed keyword list), scored for tone, and — when they name a known
    objection — mapped to the content hook that pre-empts it. Returns
    ``(None, [])`` when there are no comment texts to mine.
    """
    texts = [c["comment_text"] for c in comments if c.get("comment_text")]
    if not texts:
        return None, []

    themes = emergent_themes(texts, top_k=12, min_df=2, seed_lexicon=_KEYWORDS)
    if not themes:
        return None, []

    # (period, text) pairs drive per-theme frequency trend; period is the ISO week
    # of comment_time so a theme that surges or fades over the window is visible.
    dated_texts = [
        (iso_week(c.get("comment_time")), c["comment_text"])
        for c in comments
        if c.get("comment_text")
    ]

    theme_rows = []
    for t in themes:
        term = t["term"]
        # Aggregate tone across the docs that mention this theme.
        hits = [txt for txt in texts if term in txt] if t["source"] == "mined" else texts
        pol = round(_mean_polarity(hits), 3)
        hook = objection_to_hook(term)
        # Significance-gated frequency trend (shared analytics.trends primitive):
        # flat-but-noisy weekly counts read as "趋势不明", not a spurious move.
        trend = direction_from_summary(trend_summary(theme_period_series(dated_texts, term)))
        theme_rows.append(
            {
                "term": term,
                "comments": t["count"],
                "coverage": t["coverage"],
                "polarity": pol,
                "trend": trend,
                "content_hook": hook or "",
                "source": t["source"],
            }
        )

    objection_rows = [r for r in theme_rows if r["content_hook"]]
    rising_objections = [r for r in objection_rows if r["trend"] == "上升"]
    top_theme = theme_rows[0]["term"]
    conclusion = (
        f"从评论中涌现 {len(theme_rows)} 个高频主题，最突出的是「{top_theme}」；"
        f"其中 {len(objection_rows)} 个为可优化异议点，已映射到对应内容钩子。"
    )
    if rising_objections:
        # A rising complaint is the most actionable signal — surface it first.
        conclusion += f" 频次上升中的异议需优先处理：{rising_objections[0]['term']}。"
    elif objection_rows:
        conclusion += f" 优先补齐：{objection_rows[0]['term']}。"

    n = len(texts)
    return (
        Finding(
            title="涌现需求主题与异议",
            conclusion=conclusion,
            evidence_strength=score_evidence(n, has_controls=False, confounder_count=1),
            descriptive_reliability=score_reliability(n),
            key_numbers={
                "theme_count": len(theme_rows),
                "objection_theme_count": len(objection_rows),
                "rising_objection_count": len(rising_objections),
                "top_theme": top_theme,
            },
            caveats=[
                "观察性诊断，非因果——主题由字符 n-gram 共现与词典极性提取，非人工标注。",
                "极性基于陶瓷场景种子词典，反话/长句可能误判，改文案前需人工复核代表评论。",
                "频次趋势按 comment_time 的 ISO 周聚合并做显著性门控；周数不足或缺时间时记为「趋势不明」。",
            ],
            recommended_action=(
                "把异议主题的内容钩子排进下周选题：详情页/笔记正面回应色差、磕碰、尺寸等顾虑。"
            ),
            evidence_reason=(
                "主题来自评论文本的 2–4 gram 频次×文档覆盖排序（analytics.text_mining），"
                "极性用种子词典聚合，异议→钩子为固定映射；均为观察性描述。"
            ),
            confounders=["评论自选择偏差", "口径与反话", "热销期评论激增"],
        ),
        theme_rows,
    )


def _mean_polarity(texts) -> float:
    scored = [polarity(t, _POS_LEXICON, _NEG_LEXICON) for t in texts]
    nonzero = [s for s in scored if s != 0.0]
    if not nonzero:
        return 0.0
    return sum(nonzero) / len(nonzero)


def _fetch_comments(con) -> list[dict[str, str | None]]:
    columns = _table_columns(con, "comments")
    if "comment_text" not in columns:
        return []

    note_expr = "CAST(note_id AS VARCHAR)" if "note_id" in columns else "NULL"
    time_expr = "CAST(comment_time AS VARCHAR)" if "comment_time" in columns else "NULL"
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
          {time_expr} AS comment_time,
          CAST(comment_text AS VARCHAR) AS comment_text
        FROM comments
        WHERE comment_text IS NOT NULL
          AND TRIM(CAST(comment_text AS VARCHAR)) <> ''
        {order_clause}
        """
    )
    return [
        {"note_id": note_id, "comment_time": comment_time, "comment_text": comment_text}
        for note_id, comment_time, comment_text in result.fetchall()
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
