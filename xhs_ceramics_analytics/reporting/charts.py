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


def _hbar(
    rows: list[tuple[str, float, str, str]],
    *,
    value_max: float,
    de_emphasize: bool,
) -> str:
    """Horizontal bars sharing a zero baseline at the left edge.

    rows: (label, value, value_text, tone). value_max normalizes bar length.
    """
    width, height = _VIEW_W, 26 + 34 * len(rows)
    pad_l, pad_r = 132, 64
    track = width - pad_l - pad_r
    vmax = value_max or 1.0
    parts: list[str] = []
    for i, (label, value, value_text, tone) in enumerate(rows):
        y = 20 + i * 34
        bar_w = max(0.0, (value / vmax) * track) if value is not None else 0.0
        fill = "url(#ca-hatch)" if de_emphasize else tone
        opacity = "0.55" if de_emphasize else "1"
        parts.append(
            f'<text x="{pad_l - 10}" y="{y + 15}" text-anchor="end" class="ca-cat">'
            f'{_esc(label)}</text>'
        )
        parts.append(
            f'<rect x="{pad_l}" y="{y}" width="{_num(bar_w)}" height="20" rx="4" '
            f'fill="{fill}" fill-opacity="{opacity}">'
            f'<title>{_esc(label)}：{_esc(value_text)}</title></rect>'
        )
        parts.append(
            f'<text x="{_num(pad_l + bar_w + 8)}" y="{y + 15}" class="ca-num">'
            f'{_esc(value_text)}</text>'
        )
    parts.append(
        f'<line x1="{pad_l}" y1="12" x2="{pad_l}" y2="{height - 6}" class="ca-axis"/>'
    )
    return _frame("".join(parts), width, height)


_EVIDENCE_TONE = {
    "strong": "var(--green-bg)",
    "medium": "var(--green-bg)",
    "weak": "var(--yellow-bg)",
    "not_judgable": "var(--red-bg)",
}


def evidence_distribution(evidence_counts: Sequence[dict]) -> Markup:
    rows = [dict(item) for item in evidence_counts]
    total = sum(int(item["count"]) for item in rows)
    if total <= 0:
        return Markup("")
    present = [item for item in rows if int(item["count"]) > 0]
    width, height = _VIEW_W, 96
    pad_l, pad_r = 0, 0
    track = width - pad_l - pad_r
    parts: list[str] = [_title("结论可信度分布")]
    x = 0.0
    gap = 2.0  # 2px surface gap between adjacent segments (marks-and-anatomy)
    for item in present:
        count = int(item["count"])
        seg_w = max(0.0, (count / total) * track - gap)
        tone = _EVIDENCE_TONE.get(str(item["value"]), "var(--surface-soft)")
        label = f'{item["label"]} {count}'
        parts.append(
            f'<rect x="{_num(x)}" y="34" width="{_num(seg_w)}" height="30" rx="4" '
            f'fill="{tone}"><title>{_esc(label)}</title></rect>'
        )
        parts.append(
            f'<text x="{_num(x + 8)}" y="54" class="ca-num">{_esc(label)}</text>'
        )
        x += seg_w + gap
    return Markup(_frame("".join(parts), width, height))


_MEASURE_TITLE = {"avg_reads": "平均阅读数", "avg_collects": "平均收藏数"}


def _vbar(
    cats: list[str],
    values: list[float | None],
    value_texts: list[str],
    *,
    title: str,
    de_emphasize: bool,
) -> str:
    width, height = 308, 300
    pad_t, pad_b, pad_x = 56, 64, 20
    plot_h = height - pad_t - pad_b
    baseline_y = pad_t + plot_h
    plotted = [
        (c, v, t) for c, v, t in zip(cats, values, value_texts) if v is not None
    ]
    body = [_title(title)]
    if not plotted:
        return _frame(_title(title) + _empty_state(width, height), width, height)
    vmax = max(v for _, v, _ in plotted) or 1.0
    slot = (width - 2 * pad_x) / len(plotted)
    bw = min(slot * 0.6, 64)
    fill = "url(#ca-hatch)" if de_emphasize else "var(--ink-strong)"
    opacity = "0.55" if de_emphasize else "1"
    body.append(
        f'<line x1="{pad_x}" y1="{_num(baseline_y)}" x2="{width - pad_x}" '
        f'y2="{_num(baseline_y)}" class="ca-axis"/>'
    )
    for i, (cat, value, text) in enumerate(plotted):
        cx = pad_x + slot * (i + 0.5)
        bh = (value / vmax) * plot_h
        body.append(
            f'<rect x="{_num(cx - bw / 2)}" y="{_num(baseline_y - bh)}" '
            f'width="{_num(bw)}" height="{_num(bh)}" rx="4" fill="{fill}" '
            f'fill-opacity="{opacity}"><title>{_esc(cat)}：{_esc(text)}</title></rect>'
        )
        body.append(
            f'<text x="{_num(cx)}" y="{_num(baseline_y - bh - 8)}" text-anchor="middle" '
            f'class="ca-num">{_esc(text)}</text>'
        )
        body.append(
            f'<text x="{_num(cx)}" y="{_num(baseline_y + 20)}" text-anchor="middle" '
            f'class="ca-cat">{_esc(cat)}</text>'
        )
    return _frame("".join(body), width, height)


def _measure_panel(cats, rows, key, de_emphasize) -> str:
    values = [row.get(key) for row in rows]
    texts = [
        labels.format_number(float(v)) if v is not None else "暂无数据" for v in values
    ]
    return _vbar(cats, values, texts, title=_MEASURE_TITLE[key], de_emphasize=de_emphasize)


def _build_effect_pair(rows, category_key, strength) -> str:
    if not rows:
        return ""
    cats = [labels.value_label(str(row.get(category_key))) for row in rows]
    has_any = any(
        row.get("avg_reads") is not None or row.get("avg_collects") is not None
        for row in rows
    )
    if not has_any:
        return ""
    de = strength == EvidenceStrength.WEAK
    reads = _measure_panel(cats, rows, "avg_reads", de)
    collects = _measure_panel(cats, rows, "avg_collects", de)
    badge = _chart_badge(strength, len(rows))
    return f'{badge}<div class="chart-multiples">{reads}{collects}</div>'


def _build_cover(result: AnalysisResult, strength: EvidenceStrength) -> str:
    return _build_effect_pair(
        result.tables.get("cover_effects", []), "composition_type", strength
    )


def _build_copy(result: AnalysisResult, strength: EvidenceStrength) -> str:
    return _build_effect_pair(
        result.tables.get("copy_effects", []), "copy_angle", strength
    )


_BUILDERS["cover_style_effect"] = _build_cover
_BUILDERS["copy_angle_effect"] = _build_copy


def _build_comment_demand(result: AnalysisResult, strength: EvidenceStrength) -> str:
    rows = [r for r in result.tables.get("comment_demands", []) if int(r.get("comments") or 0) > 0]
    if not rows:
        return ""
    total = sum(int(r["comments"]) for r in rows)
    bar_rows = [
        (
            labels.value_label(str(r["demand_group"])),
            float(r.get("comment_share") or 0.0),
            labels.format_percent(float(r.get("comment_share") or 0.0)),
            "var(--ink-strong)",
        )
        for r in rows
    ]
    de = strength == EvidenceStrength.WEAK
    body = _hbar(bar_rows, value_max=max(v for _, v, _, _ in bar_rows), de_emphasize=de)
    return f'{_chart_badge(strength, total)}{body}'


_BUILDERS["comment_demand_mining"] = _build_comment_demand
