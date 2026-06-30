from xhs_ceramics_analytics.analysis.result import AnalysisResult


def render_markdown(results: list[AnalysisResult]) -> str:
    lines = ["# Xiaohongshu Ceramics Analytics Report", ""]
    for result in results:
        lines.extend([f"## {result.title}", ""])
        if result.limitations:
            lines.append("Limitations:")
            for limitation in result.limitations:
                lines.append(f"- {limitation}")
            lines.append("")
        for finding in result.findings:
            lines.extend(
                [
                    f"### {finding.title}",
                    "",
                    finding.conclusion,
                    "",
                    f"Evidence: {finding.evidence_strength.value}",
                    "",
                ]
            )
            if finding.key_numbers:
                lines.append("Key numbers:")
                for key, value in finding.key_numbers.items():
                    lines.append(f"- `{key}`: {value}")
                lines.append("")
            if finding.caveats:
                lines.append("Caveats:")
                for caveat in finding.caveats:
                    lines.append(f"- {caveat}")
                lines.append("")
            if finding.recommended_action:
                lines.extend(["Recommended action:", "", finding.recommended_action, ""])
        for table_name, rows in result.tables.items():
            lines.extend(_render_table_preview(table_name, rows))
    return "\n".join(lines).rstrip() + "\n"


def _render_table_preview(table_name: str, rows: list[dict[str, object]]) -> list[str]:
    lines = [f"Table `{table_name}`: {len(rows)} rows", ""]
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
