import hashlib
from pathlib import Path

from xhs_ceramics_analytics.analysis.prose import qty
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import score_evidence


_DEMAND_KEYWORDS: dict[str, tuple[str, ...]] = {
    "capacity": ("容量", "毫升", "ml", "多大", "尺寸", "装多少", "几毫升"),
    "price": ("价格", "多少钱", "多少元", "几元", "贵", "预算", "price"),
    "link": ("链接", "link", "购买", "下单", "店铺", "橱窗", "怎么买", "哪里买"),
    "gift": ("送", "礼物", "礼盒", "朋友", "生日", "新婚", "gift"),
}


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows = _build_hypotheses(con)
    finally:
        con.close()

    evidence_count = sum(int(row["evidence_count"]) for row in rows)

    return AnalysisResult(
        task_id="hypothesis_knowledge_base",
        title="假设知识库",
        findings=[
            Finding(
                title="持久化假设种子已生成",
                conclusion=(
                    f"已基于当前证据生成 {len(rows)} 条可持续跟踪的假设种子。"
                ),
                evidence_strength=score_evidence(
                    evidence_count, has_controls=False, confounder_count=1
                ),
                key_numbers={
                    "hypotheses": len(rows),
                    "evidence_items": evidence_count,
                },
                caveats=["这些假设只是有证据支撑的起点，不是已验证的因果结论。"],
                recommended_action=(
                    "将这些稳定假设带入每周实验，并在每次测量后更新状态。"
                ),
            )
        ],
        tables={"hypotheses": rows},
        limitations=[] if evidence_count else ["没有可用于生成假设种子的证据行。"],
    )


def _build_hypotheses(con) -> list[dict[str, object]]:
    seeds = [_angle_seed(con), _demand_seed(con), _sku_seed(con)]
    return [_hypothesis_row(seed) for seed in seeds]


def _angle_seed(con) -> dict[str, object]:
    if not _table_exists(con, "content_features"):
        return {
            "seed": "angle:unknown:collect_rate",
            "theme": "copy_angle",
            "label": "unknown",
            "evidence_count": 0,
            "metric": None,
            "evidence_summary": "没有可用的 content_features 数据。",
        }

    content_columns = _table_columns(con, "content_features")
    if "copy_angle" not in content_columns:
        return {
            "seed": "angle:unknown:collect_rate",
            "theme": "copy_angle",
            "label": "unknown",
            "evidence_count": 0,
            "metric": None,
            "evidence_summary": "content_features 表缺少 copy_angle。",
        }

    note_columns = _table_columns(con, "notes") if _table_exists(con, "notes") else set()
    can_join_notes = (
        "note_id" in content_columns
        and {"note_id", "reads", "collects"}.issubset(note_columns)
    )
    if can_join_notes:
        result = con.sql(
            """
            SELECT
              COALESCE(NULLIF(TRIM(CAST(cf.copy_angle AS VARCHAR)), ''), 'unknown')
                AS copy_angle,
              COUNT(*) AS notes,
              AVG(CASE WHEN n.reads > 0 THEN n.collects * 1.0 / n.reads END)
                AS avg_collect_rate
            FROM content_features AS cf
            LEFT JOIN notes AS n ON CAST(cf.note_id AS VARCHAR) = CAST(n.note_id AS VARCHAR)
            GROUP BY 1
            ORDER BY avg_collect_rate DESC NULLS LAST, notes DESC, copy_angle
            LIMIT 1
            """
        )
        row = result.fetchone()
        if row is not None:
            angle, notes, avg_collect_rate = row
            metric = round(float(avg_collect_rate), 4) if avg_collect_rate is not None else None
            return {
                "seed": f"angle:{angle}:collect_rate",
                "theme": "copy_angle",
                "label": angle,
                "evidence_count": int(notes),
                "metric": metric,
                "evidence_summary": (
                    f"{angle} 有 {int(notes)} 篇笔记"
                    + (f"，平均收藏率为 {metric}。" if metric is not None else "。")
                ),
            }

    result = con.sql(
        """
        SELECT
          COALESCE(NULLIF(TRIM(CAST(copy_angle AS VARCHAR)), ''), 'unknown') AS copy_angle,
          COUNT(*) AS notes
        FROM content_features
        GROUP BY 1
        ORDER BY notes DESC, copy_angle
        LIMIT 1
        """
    )
    row = result.fetchone()
    if row is None:
        return {
            "seed": "angle:unknown:collect_rate",
            "theme": "copy_angle",
            "label": "unknown",
            "evidence_count": 0,
            "metric": None,
            "evidence_summary": "没有可用的 copy_angle 数据。",
        }
    angle, notes = row
    return {
        "seed": f"angle:{angle}:collect_rate",
        "theme": "copy_angle",
        "label": angle,
        "evidence_count": int(notes),
        "metric": None,
        "evidence_summary": f"{angle} 是出现最多的文案角度，共 {int(notes)} 篇笔记。",
    }


def _demand_seed(con) -> dict[str, object]:
    counts = {group: 0 for group in ("capacity", "price", "link", "gift", "other")}
    if _table_exists(con, "comments") and "comment_text" in _table_columns(con, "comments"):
        result = con.sql(
            """
            SELECT CAST(comment_text AS VARCHAR) AS comment_text
            FROM comments
            WHERE comment_text IS NOT NULL
              AND TRIM(CAST(comment_text AS VARCHAR)) <> ''
            ORDER BY comment_text
            """
        )
        for (text,) in result.fetchall():
            counts[_classify_comment(text)] += 1

    if max(counts.values(), default=0) == 0:
        return {
            "seed": "demand:unknown:comment_reply",
            "theme": "comment_demand",
            "label": "unknown",
            "evidence_count": 0,
            "metric": None,
            "evidence_summary": "没有可用的评论需求证据；请先收集并标注评论。",
        }

    group, count = max(counts.items(), key=lambda item: (item[1], item[0]))
    return {
        "seed": f"demand:{group}:comment_reply",
        "theme": "comment_demand",
        "label": group,
        "evidence_count": count,
        "metric": count,
        "evidence_summary": f"{qty(count)} 条评论被归入 {group} 需求。",
    }


def _sku_seed(con) -> dict[str, object]:
    if _table_exists(con, "daily_sku_sales"):
        sales_columns = _table_columns(con, "daily_sku_sales")
        if "sku_id" not in sales_columns:
            return {
                "seed": "sku:unknown:allocation",
                "theme": "product_opportunity",
                "label": "unknown",
                "evidence_count": 0,
                "metric": None,
                "evidence_summary": "daily_sku_sales 表缺少 sku_id。",
            }
        if "units" not in sales_columns:
            return {
                "seed": "sku:unknown:allocation",
                "theme": "product_opportunity",
                "label": "unknown",
                "evidence_count": 0,
                "metric": None,
                "evidence_summary": "daily_sku_sales 表缺少 units。",
            }
        has_skus = _table_exists(con, "skus")
        sku_columns = _table_columns(con, "skus") if has_skus else set()
        join_clause = (
            "LEFT JOIN skus AS s ON CAST(d.sku_id AS VARCHAR) = CAST(s.sku_id AS VARCHAR)"
            if has_skus and {"sku_id", "sku_name"}.issubset(sku_columns)
            else ""
        )
        name_expr = (
            "COALESCE(MAX(CAST(s.sku_name AS VARCHAR)), CAST(d.sku_id AS VARCHAR))"
            if join_clause
            else "CAST(d.sku_id AS VARCHAR)"
        )
        result = con.sql(
            f"""
            SELECT
              CAST(d.sku_id AS VARCHAR) AS sku_id,
              {name_expr} AS sku_name,
              SUM(CAST(d.units AS DOUBLE)) AS units,
              COUNT(*) AS sales_days
            FROM daily_sku_sales AS d
            {join_clause}
            WHERE d.sku_id IS NOT NULL
              AND d.units IS NOT NULL
            GROUP BY 1
            ORDER BY units DESC NULLS LAST, sales_days DESC, sku_id
            LIMIT 1
            """
        )
        row = result.fetchone()
        if row is not None:
            sku_id, sku_name, units, sales_days = row
            units_value = round(float(units), 4) if units is not None else None
            return {
                "seed": f"sku:{sku_id}:allocation",
                "theme": "product_opportunity",
                "label": sku_name,
                "evidence_count": int(sales_days),
                "metric": units_value,
                "evidence_summary": (
                    f"{sku_name} 在 SKU 销量中领先，{int(sales_days)} 天内售出 "
                    f"{_display_metric(units_value)} 件。"
                ),
            }
        return {
            "seed": "sku:unknown:allocation",
            "theme": "product_opportunity",
            "label": "unknown",
            "evidence_count": 0,
            "metric": None,
            "evidence_summary": "daily_sku_sales 表没有可用的 SKU 销量记录。",
        }

    return {
        "seed": "sku:unknown:allocation",
        "theme": "product_opportunity",
        "label": "unknown",
        "evidence_count": 0,
        "metric": None,
        "evidence_summary": "没有可用的 daily_sku_sales 数据。",
    }


def _hypothesis_row(seed: dict[str, object]) -> dict[str, object]:
    seed_text = str(seed["seed"])
    theme = str(seed["theme"])
    label = str(seed["label"])
    evidence_count = int(seed["evidence_count"])
    return {
        "hypothesis_id": _stable_id(seed_text),
        "seed": seed_text,
        "theme": theme,
        "label": label,
        "status": "active" if evidence_count else "needs_data",
        "hypothesis": _hypothesis_text(theme, label, evidence_count),
        "evidence_count": evidence_count,
        "metric": seed["metric"],
        "evidence_strength": score_evidence(
            evidence_count, has_controls=False, confounder_count=1
        ).value,
        "evidence_summary": seed["evidence_summary"],
        "next_test": _next_test(theme, label, evidence_count),
    }


def _hypothesis_text(theme: str, label: str, evidence_count: int) -> str:
    if theme == "comment_demand" and evidence_count == 0:
        return "在收集并标注更多评论前，评论需求仍不可判断。"
    if theme == "copy_angle":
        return f"{label} 文案与头部 SKU 搭配时，可能形成可复用的收藏意图。"
    if theme == "comment_demand":
        return f"{label} 类评论需求可通过在内容中显性回答来转化。"
    return f"{label} 相比当前基线内容组合，值得分配更多受控内容档期。"


def _next_test(theme: str, label: str, evidence_count: int) -> str:
    if theme == "comment_demand" and evidence_count == 0:
        return "先收集并标注更多评论，再测试显性回复模式。"
    if theme == "copy_angle":
        return f"发布两篇 {label} 角度笔记，并用一个替代角度做对照，比较收藏率。"
    if theme == "comment_demand":
        return f"在封面叠字和首条回复中加入 {label} 回答，并跟踪匹配评论。"
    return f"给 {label} 分配两个实验档期，并比较销售辅助互动表现。"


def _classify_comment(text: str) -> str:
    normalized = text.lower()
    for group in ("capacity", "price", "link", "gift"):
        if any(keyword in normalized for keyword in _DEMAND_KEYWORDS[group]):
            return group
    return "other"


def _display_metric(value: object | None) -> str:
    return "未知" if value is None else str(value)


def _stable_id(seed: str) -> str:
    return f"h_{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:10]}"


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
