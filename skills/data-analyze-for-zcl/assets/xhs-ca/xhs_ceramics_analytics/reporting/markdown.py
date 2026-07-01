from xhs_ceramics_analytics.analysis.result import AnalysisResult


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


def render_markdown(results: list[AnalysisResult]) -> str:
    lines = ["# 小红书账号分析报告", ""]
    for result in results:
        lines.extend([f"## {_display_title(result.title)}", ""])
        if result.limitations:
            lines.append("限制：")
            for limitation in result.limitations:
                lines.append(f"- {_display_limitation(limitation)}")
            lines.append("")
        for finding in result.findings:
            lines.extend(
                [
                    f"### {finding.title}",
                    "",
                    finding.conclusion,
                    "",
                    f"证据强度：{_evidence_label(finding.evidence_strength.value)}",
                    "",
                ]
            )
            if finding.key_numbers:
                lines.append("关键数字：")
                for key, value in finding.key_numbers.items():
                    lines.append(f"- `{key}`: {value}")
                lines.append("")
            if finding.caveats:
                lines.append("注意事项：")
                for caveat in finding.caveats:
                    lines.append(f"- {caveat}")
                lines.append("")
            if finding.recommended_action:
                lines.extend(["建议动作：", "", finding.recommended_action, ""])
        for table_name, rows in result.tables.items():
            lines.extend(_render_table_preview(table_name, rows))
    return "\n".join(lines).rstrip() + "\n"


def _render_table_preview(table_name: str, rows: list[dict[str, object]]) -> list[str]:
    lines = [f"表格 `{table_name}`：{len(rows)} 行", ""]
    if not rows:
        return lines

    preview_rows = rows[:5]
    columns = list(preview_rows[0].keys())
    lines.append("| " + " | ".join(columns) + " |")
    lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in preview_rows:
        values = [_markdown_cell(row.get(column)) for column in columns]
        lines.append("| " + " | ".join(values) + " |")
    lines.append("")
    return lines


def _markdown_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _display_title(title: str) -> str:
    return _TITLE_LABELS.get(title, title)


def _evidence_label(value: str) -> str:
    return _EVIDENCE_LABELS.get(value, value)


def _display_limitation(limitation: str) -> str:
    prefix = "notes columns missing for funnel rates: "
    if limitation.startswith(prefix):
        fields = limitation.removeprefix(prefix).rstrip(".")
        return f"笔记表缺少漏斗指标字段：{fields}。"
    return limitation
