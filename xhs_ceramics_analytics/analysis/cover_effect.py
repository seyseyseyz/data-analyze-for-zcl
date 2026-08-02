from pathlib import Path

from xhs_ceramics_analytics.analysis.content_group_metrics import (
    fetch_group_effects,
    has_metric_evidence,
)
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.evidence import score_evidence
from xhs_ceramics_analytics.evidence import score_reliability


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows, limitations = _fetch_cover_effects(con)
    finally:
        con.close()

    sample_size = sum(int(row.get("notes") or 0) for row in rows)
    evidence_strength = (
        score_evidence(sample_size, has_controls=False, confounder_count=2)
        if rows and has_metric_evidence(rows)
        else EvidenceStrength.NOT_JUDGABLE
    )
    descriptive_reliability = score_reliability(sample_size)
    return AnalysisResult(
        task_id="cover_style_effect",
        title="封面风格效果",
        findings=[
            Finding(
                title="封面类型已排序",
                conclusion="已按曝光、阅读、商品点击、支付和净成交效率对封面构图类型进行排序。",
                evidence_strength=evidence_strength,
                descriptive_reliability=descriptive_reliability,
                key_numbers={"cover_groups": len(rows), "notes": sample_size},
                caveats=[
                    "在加入 SKU、发布时间和流量来源控制前，这个排序仍是描述性结果。",
                    "商业指标只在 notes 存在对应字段时输出，缺失不记为 0。",
                ],
            )
        ],
        tables={"cover_effects": rows},
        limitations=limitations,
    )


def _fetch_cover_effects(con) -> tuple[list[dict[str, object]], list[str]]:
    if not _table_exists(con, "content_features"):
        return [], ["缺少 content_features 表。"]

    content_columns = _table_columns(con, "content_features")
    if "composition_type" not in content_columns:
        return [], ["content_features 表缺少 composition_type 字段。"]
    rows, limitations = fetch_group_effects(con, "composition_type")
    limitations = [
        item.replace("内容排序", "封面排序").replace("内容效果", "封面效果") for item in limitations
    ]
    return rows, limitations


def _rows(result) -> list[dict[str, object]]:
    columns = result.columns
    return [dict(zip(columns, row, strict=True)) for row in result.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}
