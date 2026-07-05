from xhs_ceramics_analytics.analysis.methodology import combined_methodology
from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.reporting.formatting import (
    field_help,
    field_label,
    format_scalar,
    should_render_table,
)
from xhs_ceramics_analytics.reporting.confidence import reader_confidence
from xhs_ceramics_analytics.reporting.domains import (
    APPENDIX_DOMAIN_INTRO,
    APPENDIX_DOMAIN_TITLE,
    group_by_domain,
)
from xhs_ceramics_analytics.reporting.priority import build_priority_table
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS, order_results


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

_DEFAULT_REPORT_TITLE = "小红书账号分析报告"


def render_markdown(results: list[AnalysisResult], title: str | None = None) -> str:
    lines = [f"# {title or _DEFAULT_REPORT_TITLE}", ""]
    lines.extend(_render_priority_table(results))

    # Domain grouping is shared with the HTML compositor (reporting.domains): each
    # business domain is a level-2 heading, its modules drop to level-3. The
    # data-quality appendix is not a business domain — it closes the report under
    # its own heading, matching section_order's "conclusions first, caveats last".
    for domain in group_by_domain(results):
        lines.extend([f"## {domain.title}", "", domain.intro, ""])
        for result in domain.results:
            lines.extend(_render_result(result))

    appendix = order_results([r for r in results if r.task_id in APPENDIX_TASKS])
    if appendix:
        lines.extend([f"## {APPENDIX_DOMAIN_TITLE}", "", APPENDIX_DOMAIN_INTRO, ""])
        for result in appendix:
            lines.extend(_render_result(result))

    return "\n".join(lines).rstrip() + "\n"


def _render_result(result: AnalysisResult) -> list[str]:
    """Render one module under a domain heading: module=###, finding=####, etc."""
    lines = [f"### {_display_title(result.title)}", ""]
    if result.limitations:
        lines.append("限制：")
        for limitation in result.limitations:
            lines.append(f"- {_display_limitation(limitation)}")
        lines.append("")
    for finding in result.findings:
        lines.extend(_render_finding(finding, heading_level="####"))
    for subsection in result.subsections:
        lines.extend(_render_subsection(subsection))
    if result.named_examples:
        lines.extend(_render_named_examples(result.named_examples))
    for table_name, rows in result.tables.items():
        lines.extend(_render_table_preview(table_name, rows))
    return lines


def _render_priority_table(results: list[AnalysisResult]) -> list[str]:
    """Cross-module priority table at the top of the report, in 4 plain-language columns.

    Renders one ranked table so the reader sees, before any module detail, what to do
    first. The statistical scoring (预期影响 × 可行性) still orders the rows internally,
    but the reader only meets 4 human columns — 先动顺序 / 哪个环节 / 具体先做什么 /
    置信度. The last column is a genuine per-row rating, NOT a band-composed
    "为什么值得先做" reason (which read verbatim-identical down every row on real data —
    the priority rationale is the rank order itself, said once in the intro). Omitted
    entirely when no module carries an actionable finding.
    """
    rows = build_priority_table(results)
    if not rows:
        return []
    lines = [
        "## 优先级导读：先动哪里",
        "",
        "下面这张表把各模块的结论收成一份先后清单，从上到下就是本周先后顺序，越靠前越该先动。",
        "",
        "| 先动顺序 | 哪个环节 | 具体先做什么 | 置信度 |",
        "| --- | --- | --- | --- |",
    ]
    for index, row in enumerate(rows, start=1):
        lever = _cell(row.get("lever"))
        weak_link = _cell(row.get("weak_link"))
        confidence = _cell(row.get("confidence_label"))
        lines.append(f"| {index} | {weak_link} | {lever} | {confidence} |")
    lines.append("")
    return lines


def _cell(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def _render_finding(finding, heading_level: str = "###") -> list[str]:
    # Single reader-facing 置信度 (描述可靠性为主, 因果强度降为脚注) — the two
    # statistical axes are folded here so the reader never sees "证据强度 弱 /
    # 描述可靠性 高" side by side and reads the whole thing as "低".
    rc = reader_confidence(finding)
    lines = [
        f"{heading_level} {finding.title}",
        "",
        finding.conclusion,
        "",
        f"置信度：{rc.label}",
        "",
    ]
    if finding.key_numbers:
        lines.append("关键数字：")
        for key, value in finding.key_numbers.items():
            help_text = field_help(key)
            suffix = f"（{help_text}）" if help_text else ""
            lines.append(f"- {field_label(key)}：{format_scalar(key, value)}{suffix}")
        lines.append("")
    if finding.caveats or rc.causal_caveat:
        lines.append("注意事项：")
        for caveat in finding.caveats:
            lines.append(f"- {caveat}")
        if rc.causal_caveat:
            lines.append(f"- {rc.causal_caveat}")
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
    appendix = combined_methodology(finding)
    if appendix:
        lines.extend(["方法与附录：", "", appendix, ""])
    return lines


def _render_subsection(subsection) -> list[str]:
    # Modules sit at ### under a ## domain heading, so a subsection is ##### and its
    # findings ######.
    lines = [f"##### {subsection.title}", ""]
    if subsection.body:
        lines.extend([subsection.body, ""])
    for finding in subsection.findings:
        lines.extend(_render_finding(finding, heading_level="######"))
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


def _display_limitation(limitation: str) -> str:
    prefix = "notes columns missing for funnel rates: "
    if limitation.startswith(prefix):
        fields = limitation.removeprefix(prefix).rstrip(".")
        return f"笔记表缺少漏斗指标字段：{fields}。"
    return limitation
