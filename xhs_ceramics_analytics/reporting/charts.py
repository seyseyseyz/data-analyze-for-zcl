"""Hand-built inline-SVG charts for the single-file HTML report.

No plotly, no JavaScript, no runtime charting dependency. Each builder reads the
RAW AnalysisResult.tables rows and returns an HTML string (SVG plus an evidence
badge). The public entry points wrap the result in markupsafe.Markup so the
autoescaped template renders it verbatim; therefore every interpolated text node
MUST be escaped with markupsafe.escape (_esc) inside the builders.
"""
from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from markupsafe import Markup, escape

from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting import labels

logger = logging.getLogger(__name__)

_VIEW_W = 640
_STRENGTH_LABEL = {
    EvidenceStrength.STRONG: "强",
    EvidenceStrength.MEDIUM: "中",
    EvidenceStrength.WEAK: "弱",
}

_HATCH = (
    '<defs>'
    '<pattern id="ca-hatch" width="6" height="6" patternUnits="userSpaceOnUse" '
    'patternTransform="rotate(45)">'
    '<rect width="6" height="6" fill="var(--surface)"/>'
    '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--muted)" stroke-width="1.4"/>'
    '</pattern>'
    '</defs>'
)


def _esc(text: object) -> str:
    return str(escape("" if text is None else text))


def _num(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _frame(body: str, width: int, height: int) -> str:
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" '
        f'preserveAspectRatio="xMidYMid meet">{_HATCH}{body}</svg>'
    )


def _title(text: str) -> str:
    return f'<text x="0" y="18" class="ca-title">{_esc(text)}</text>'


def _empty_state(width: int, height: int) -> str:
    return (
        f'<text x="{_num(width / 2)}" y="{_num(height / 2)}" text-anchor="middle" '
        f'class="ca-empty">数据不足，无法判断</text>'
    )


def _chart_badge(strength: EvidenceStrength, n: int) -> str:
    """Evidence badge as an HTML tag span, reusing the report's tag CSS mapping."""
    if strength == EvidenceStrength.WEAK:
        cls, text = "weak", f"样本不足 · n={n}"
    elif strength == EvidenceStrength.MEDIUM:
        cls, text = "medium", f"可信度 中 · n={n}"
    else:
        cls, text = "strong", f"可信度 强 · n={n}"
    return f'<span class="tag {cls} chart-badge">{_esc(text)}</span>'


# Builder registry — populated in later tasks. Each builder:
#   (result: AnalysisResult, strength: EvidenceStrength) -> str   ("" when not chartable)
_BUILDERS: dict[str, Callable[[AnalysisResult, EvidenceStrength], str]] = {}


def for_result(result: AnalysisResult) -> Markup:
    builder = _BUILDERS.get(result.task_id)
    if builder is None:
        return Markup("")
    strength = (
        result.findings[0].evidence_strength
        if result.findings
        else EvidenceStrength.NOT_JUDGABLE
    )
    if strength == EvidenceStrength.NOT_JUDGABLE:
        return Markup("")
    try:
        html = builder(result, strength)
    except Exception:  # per-chart isolation: never blank a section, never abort render
        logger.exception("chart build failed for task_id=%s", result.task_id)
        return Markup("")
    return Markup(html) if html else Markup("")


def evidence_distribution(evidence_counts: Sequence[dict]) -> Markup:
    return Markup("")  # implemented in Task 3
