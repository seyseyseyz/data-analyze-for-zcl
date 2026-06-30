from xhs_ceramics_analytics.analysis.result import AnalysisResult


def render_markdown(results: list[AnalysisResult]) -> str:
    lines = ["# Xiaohongshu Ceramics Analytics Report", ""]
    for result in results:
        lines.extend([f"## {result.title}", ""])
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
    return "\n".join(lines).rstrip() + "\n"
