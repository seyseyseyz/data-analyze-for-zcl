from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.reporting.formatting import (
    field_label,
    format_scalar,
    should_render_table,
)
from xhs_ceramics_analytics.reporting.section_order import order_results


_TITLE_LABELS = {
    "Data Quality Check": "数据质量检查",
    "Account Baseline": "账号基线",
    "Note Funnel": "笔记漏斗",
    "SKU Counterfactual Lift": "SKU 销量响应",
    "Content Response Curve": "内容响应曲线",
    "Cover Style Effect": "封面风格效果",
    "Copy Angle Effect": "文案角度效果",
    "Product and Content Interaction": "商品与内容交互",
    "Product Opportunity Matrix": "商品机会矩阵",
    "Comment Demand Mining": "评论需求挖掘",
    "Content Portfolio Optimization": "内容组合优化",
    "Weekly Experiment Matrix": "每周实验矩阵",
    "Reshoot Repost Candidates": "重拍与重发候选",
    "Hypothesis Knowledge Base": "假设知识库",
    "Weekly Business Review": "每周经营复盘",
}

_EVIDENCE_LABELS = {
    "strong": "强",
    "medium": "中",
    "weak": "弱",
    "not_judgable": "不可判断",
}

_RELIABILITY_LABELS = {
    "high": "高",
    "medium": "中",
    "low": "低",
    "not_applicable": "不适用",
}


_DEFAULT_REPORT_TITLE = "小红书账号分析报告"


def render_markdown(results: list[AnalysisResult], title: str | None = None) -> str:
    lines = [f"# {title or _DEFAULT_REPORT_TITLE}", ""]
    for result in order_results(results):
        lines.extend([f"## {_display_title(result.title)}", ""])
        if result.limitations:
            lines.append("限制：")
            for limitation in result.limitations:
                lines.append(f"- {_display_limitation(limitation)}")
            lines.append("")
        for finding in result.findings:
            lines.extend(_render_finding(finding))
        for subsection in result.subsections:
            lines.extend(_render_subsection(subsection))
        if result.named_examples:
            lines.extend(_render_named_examples(result.named_examples))
        for table_name, rows in result.tables.items():
            lines.extend(_render_table_preview(table_name, rows))
    return "\n".join(lines).rstrip() + "\n"


def _render_finding(finding, heading_level: str = "###") -> list[str]:
    lines = [
        f"{heading_level} {finding.title}",
        "",
        finding.conclusion,
        "",
        f"证据强度：{_evidence_label(finding.evidence_strength.value)}",
    ]
    # Orthogonal axis: how precisely the numbers describe the period. Rendered
    # only when a module scored it, so causal strength never reads as the whole story.
    if finding.descriptive_reliability is not None:
        lines.append(f"描述可靠性：{_reliability_label(finding.descriptive_reliability.value)}")
    lines.append("")
    if finding.key_numbers:
        lines.append("关键数字：")
        for key, value in finding.key_numbers.items():
            lines.append(f"- {field_label(key)}（`{key}`）：{format_scalar(key, value)}")
        lines.append("")
    if finding.caveats:
        lines.append("注意事项：")
        for caveat in finding.caveats:
            lines.append(f"- {caveat}")
        lines.append("")
    if finding.confounders:
        lines.append("可能的混淆因素：")
        for confounder in finding.confounders:
            lines.append(f"- {confounder}")
        lines.append("")
    if finding.recommended_action:
        lines.extend(["建议动作：", "", finding.recommended_action, ""])
    if finding.next_test:
        lines.extend(["下一步验证：", "", finding.next_test, ""])
    if finding.appendix:
        lines.extend(["方法与附录：", "", finding.appendix, ""])
    return lines


def _render_subsection(subsection) -> list[str]:
    lines = [f"#### {subsection.title}", ""]
    if subsection.body:
        lines.extend([subsection.body, ""])
    for finding in subsection.findings:
        lines.extend(_render_finding(finding, heading_level="#####"))
    return lines


def _render_named_examples(examples: list[dict]) -> list[str]:
    lines = ["命名示例：", ""]
    for example in examples:
        label = example.get("label") or example.get("name") or ""
        detail = example.get("detail") or example.get("note") or ""
        lines.append(f"- **{label}**：{detail}" if detail else f"- **{label}**")
    lines.append("")
    return lines


def _render_table_preview(table_name: str, rows: list[dict[str, object]]) -> list[str]:
    if not should_render_table(rows):
        return []
    preview_rows = rows[:5]
    columns = list(preview_rows[0].keys())
    # Machine column names stay in the markdown preview — it is the traceable data
    # appendix (查数用); reader-facing labels live on the key-numbers above and in
    # the HTML user-view. Only the *values* get reader formatting.
    lines = [f"表格 `{table_name}`：共 {len(rows)} 行，当前展示 {len(preview_rows)} 行", ""]
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in preview_rows:
        values = [_markdown_cell(column, row.get(column)) for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return lines


def _markdown_cell(field_name: str, value: object) -> str:
    text = format_scalar(field_name, value)
    return text.replace("|", "\\|").replace("\n", " ")


def _display_title(title: str) -> str:
    return _TITLE_LABELS.get(title, title)


def _evidence_label(value: str) -> str:
    return _EVIDENCE_LABELS.get(value, value)


def _reliability_label(value: str) -> str:
    return _RELIABILITY_LABELS.get(value, value)


def _display_limitation(limitation: str) -> str:
    prefix = "notes columns missing for funnel rates: "
    if limitation.startswith(prefix):
        fields = limitation.removeprefix(prefix).rstrip(".")
        return f"笔记表缺少漏斗指标字段：{fields}。"
    return limitation
