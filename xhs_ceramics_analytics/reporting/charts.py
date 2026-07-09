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
from xhs_ceramics_analytics.reporting import labels
from xhs_ceramics_analytics.reporting.confidence import ReaderConfidence, reader_confidence
from xhs_ceramics_analytics.reporting.formatting import format_scalar

logger = logging.getLogger(__name__)

_VIEW_W = 640

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


def _frame(body: str, width: int, height: int, label: str = "数据图表，详见下方表格") -> str:
    # role="img" + aria-label gives screen readers a single accessible name; the
    # detailed numbers stay reachable in the accompanying data table below.
    # ``max-width`` caps the chart at its OWN viewBox width: the shared
    # ``.chart-svg { width:100% }`` rule would otherwise stretch a 640/308-wide
    # chart to the full content column (the "宽高太大" complaint). It still shrinks
    # responsively on a narrower column; it just never scales ABOVE its design size.
    return (
        f'<svg viewBox="0 0 {width} {height}" class="chart-svg" role="img" '
        f'aria-label="{_esc(label)}" preserveAspectRatio="xMidYMid meet" '
        f'style="max-width:{width}px">{_HATCH}{body}</svg>'
    )


# --- dense-axis form guards (a chart is a shape, not a data dump) -----------
# A curated line/bar can be fed 90–600 rows; drawing a label or dot for each
# produces an unreadable "wall" and a giant SVG. These mirror the already-correct
# _timeseries_line (ticks=min(6,n)) / _rank_bars (top_n) thinning, applied to the
# curated-template path (_line / _vbar / _waterfall) that previously had neither.
_MAX_AXIS_LABELS = 12   # most category / x-axis labels drawn; the rest are thinned
_MAX_LINE_MARKERS = 24  # above this a line drops per-point circles (keeps the path)
_MAX_BARS = 12          # curated bar templates cap to this many categories


def _axis_label_indices(n: int, max_labels: int = _MAX_AXIS_LABELS) -> set[int]:
    """Evenly-spaced label indices (always including first & last) to thin a dense
    axis to at most ``max_labels`` labels. For ``n <= max_labels`` every index is
    kept, so small charts are byte-identical to before."""
    if n <= 0:
        return set()
    if n <= max_labels:
        return set(range(n))
    step = (n - 1) / (max_labels - 1)
    return {round(step * t) for t in range(max_labels)}


# --- shared chart furniture: value-reference grid, trend smoothing, area fill ---
# These turn the bare axis+line/bar into a readable "shape": faint horizontal
# references, a soft area under a trend, and a smoothed trend over a faded raw
# series. All deterministic (fixed geometry / colours) so the byte-stable
# contract holds; colours use var(--token, #literal) so BOTH report roots render
# identically without adding a new :root token.
_GRID_LEVELS = 4


def _hgrid(x0: float, x1: float, y_top: float, y_base: float, levels: int = _GRID_LEVELS) -> str:
    """Evenly-spaced solid horizontal hairlines as value references, drawn behind
    the series. The baseline itself is the ca-axis, so grids fill the interior."""
    if levels < 1 or y_base <= y_top:
        return ""
    step = (y_base - y_top) / levels
    return "".join(
        f'<line x1="{_num(x0)}" y1="{_num(y_base - step * k)}" '
        f'x2="{_num(x1)}" y2="{_num(y_base - step * k)}" class="ca-grid"/>'
        for k in range(1, levels + 1)
    )


def _moving_avg(values: Sequence[float], k: int) -> list[float]:
    """Centered moving average, window ``2k+1``, edge-clamped. Pure; ``k<=0`` is
    identity. Used to lift a bold trend out of a noisy daily series."""
    if k <= 0:
        return list(values)
    n = len(values)
    out: list[float] = []
    for i in range(n):
        a = max(0, i - k)
        b = min(n, i + k + 1)
        window = values[a:b]
        out.append(sum(window) / len(window))
    return out


def _area_fill(
    xs: Sequence[float], ys: Sequence[float], baseline_y: float, *, opacity: str = "0.6"
) -> str:
    """Soft closed area between a line and the baseline so the series reads as a
    shape, not a wire. Pale green with a literal fallback (keeps both report roots
    identical without a new token)."""
    if len(xs) < 2:
        return ""
    pts = " ".join(f"L{_num(x)} {_num(y)}" for x, y in zip(xs, ys))
    d = f"M{_num(xs[0])} {_num(baseline_y)} {pts} L{_num(xs[-1])} {_num(baseline_y)} Z"
    return f'<path d="{d}" fill="var(--green-bg, #EDF3EC)" fill-opacity="{opacity}"/>'


def _title(text: str) -> str:
    return f'<text x="0" y="18" class="ca-title">{_esc(text)}</text>'


def _empty_state(width: int, height: int) -> str:
    return (
        f'<text x="{_num(width / 2)}" y="{_num(height / 2)}" text-anchor="middle" '
        f'class="ca-empty">数据不足，无法判断</text>'
    )


def _chart_badge(confidence: ReaderConfidence, n: int) -> str:
    """置信度徽章 —— 复用报告里同一个面向商家的「置信度」。

    与结论正文取同一个 :func:`reader_confidence`（折叠后的**描述可靠性**为主、因果强度
    降为脚注），所以图表不会在正文写「置信度 高」时，自己却显示原始因果档「可信度 弱」而
    自相矛盾。CSS 类沿用 high/medium/low 的 tag 映射；n 仍展示，让真正的小样本依然可见。
    """
    text = f"置信度 {confidence.label} · n={n}"
    return f'<span class="tag {confidence.level} chart-badge">{_esc(text)}</span>'


# Builder registry — populated in later tasks. Each builder:
#   (result: AnalysisResult, confidence: ReaderConfidence) -> str   ("" when not chartable)
_BUILDERS: dict[str, Callable[[AnalysisResult, ReaderConfidence], str]] = {}


def for_result(result: AnalysisResult) -> Markup:
    builder = _BUILDERS.get(result.task_id)
    if builder is None or not result.findings:
        return Markup("")
    # Single reader-facing 置信度, folded from the two evidence axes — the SAME
    # primitive the prose/priority table use, so a chart's badge never contradicts
    # its section. NOT_JUDGABLE (no actionable finding) suppresses the chart entirely.
    confidence = reader_confidence(result.findings[0])
    if confidence.level == "not_judgable":
        return Markup("")
    try:
        html = builder(result, confidence)
    except Exception:  # per-chart isolation: never blank a section, never abort render
        logger.exception("chart build failed for task_id=%s", result.task_id)
        return Markup("")
    return Markup(html) if html else Markup("")


def _de_emphasize(result: AnalysisResult) -> bool:
    """Whether a chart should render de-emphasised (hatch/dashed/faded).

    Driven by the reader-facing confidence (descriptive precision first), NOT by
    causal :class:`EvidenceStrength`. Single-window shop data is causally WEAK by
    construction, so keying greying off that would fade every large-sample chart
    into a "broken" look. Here a chart only de-emphasises when its number is
    genuinely thin (low reliability) or not judgable. Never raises.
    """
    if not result.findings:
        return False
    return reader_confidence(result.findings[0]).de_emphasize


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
    pad_l, gap = 132, 8
    # Size the right gutter to the widest value label so a full-length bar's
    # number never runs off the right edge (fit the layout to the content, don't
    # clip). Left labels wider than the gutter are truncated with an ellipsis;
    # the full text stays reachable in each bar's <title>.
    max_val_w = max((_legend_text_w(vt) for _, _, vt, _ in rows), default=0.0)
    pad_r = max(56.0, gap + max_val_w + 8.0)
    track = max(40.0, width - pad_l - pad_r)
    label_gutter = pad_l - 14
    vmax = value_max or 1.0
    parts: list[str] = []
    for i, (label, value, value_text, tone) in enumerate(rows):
        y = 20 + i * 34
        bar_w = max(0.0, (value / vmax) * track) if value is not None else 0.0
        # Track rail behind the bar so even a tiny value shows its share of the
        # whole. Drawn as a round-capped <line> (NOT a <rect x=>) so per-row
        # bar-rect counts in the template tests stay exact.
        cy = y + 10
        parts.append(
            f'<line x1="{_num(pad_l + 10)}" y1="{_num(cy)}" x2="{_num(pad_l + track - 10)}" '
            f'y2="{_num(cy)}" stroke="var(--track, #F1F0ED)" stroke-width="20" '
            f'stroke-linecap="round"/>'
        )
        if de_emphasize:
            fill, opacity = "url(#ca-hatch)", "0.55"
        else:
            # A slab of #111 reads as "loud". Charcoal plus a gentle per-rank fade
            # gives the ranking a calm hierarchy while the top bar stays saturated.
            fill = "var(--ink)" if tone == "var(--ink-strong)" else tone
            opacity = "1" if i == 0 else _num(max(0.5, 0.92 - 0.1 * i))
        parts.append(
            f'<text x="{pad_l - 10}" y="{y + 15}" text-anchor="end" class="ca-cat">'
            f'{_esc(_truncate(str(label), label_gutter))}<title>{_esc(label)}</title></text>'
        )
        parts.append(
            f'<rect x="{pad_l}" y="{y}" width="{_num(bar_w)}" height="20" rx="10" '
            f'fill="{fill}" fill-opacity="{opacity}">'
            f'<title>{_esc(label)}：{_esc(value_text)}</title></rect>'
        )
        parts.append(
            f'<text x="{_num(pad_l + bar_w + gap)}" y="{y + 15}" class="ca-num">'
            f'{_esc(value_text)}</text>'
        )
    parts.append(
        f'<line x1="{pad_l}" y1="12" x2="{pad_l}" y2="{height - 6}" class="ca-axis"/>'
    )
    return _frame("".join(parts), width, height)


# Weak reads neutral-grey (not warning-yellow) to match the report's tag palette:
# an observational finding is "directional", not "broken".
_EVIDENCE_TONE = {
    # Reader-facing 置信度 levels (高/中/低/暂不下定论) — matches reporting.confidence.
    "high": "var(--green-bg)",
    "medium": "var(--green-bg)",
    "low": "var(--neutral-bg)",
    "not_judgable": "var(--red-bg)",
    # Legacy causal keys kept as harmless fallbacks.
    "strong": "var(--green-bg)",
    "weak": "var(--neutral-bg)",
}


def _legend_text_w(text: str) -> float:
    """Rough advance width of a legend caption: CJK glyphs are ~15px wide, ASCII
    (digits/spaces) ~8px at the report's font size. Used to lay legend items out
    without overlap; exact metrics are unnecessary since the SVG scales to fit."""
    return sum(15.0 if ord(ch) > 0x2E80 else 8.0 for ch in text)


def _truncate(text: str, max_w: float) -> str:
    """Clip text to an advance-width budget, appending an ellipsis. Keeps a chart
    label inside its gutter instead of overrunning the plotting area; callers keep
    the full text reachable via a <title>."""
    if _legend_text_w(text) <= max_w:
        return text
    ellipsis = "…"
    budget = max_w - _legend_text_w(ellipsis)
    out, used = "", 0.0
    for ch in text:
        cw = 15.0 if ord(ch) > 0x2E80 else 8.0
        if used + cw > budget:
            break
        out += ch
        used += cw
    return out + ellipsis


def evidence_distribution(evidence_counts: Sequence[dict]) -> Markup:
    rows = [dict(item) for item in evidence_counts]
    total = sum(int(item["count"]) for item in rows)
    if total <= 0:
        return Markup("")
    present = [item for item in rows if int(item["count"]) > 0]
    width, height = _VIEW_W, 112
    track = width
    parts: list[str] = [_title("结论置信度分布")]
    # Proportional bar carries the visual share only — a segment for a rare tier
    # (e.g. 高 2 of 31) is far too narrow to hold its caption, so the count lives
    # in the legend below instead of overflowing into the neighbouring segment.
    x = 0.0
    gap = 2.0  # 2px surface gap between adjacent segments (marks-and-anatomy)
    for item in present:
        count = int(item["count"])
        seg_w = max(0.0, (count / total) * track - gap)
        tone = _EVIDENCE_TONE.get(str(item["value"]), "var(--surface-soft)")
        parts.append(
            f'<rect x="{_num(x)}" y="34" width="{_num(seg_w)}" height="22" rx="4" '
            f'fill="{tone}"><title>{_esc(item["label"])} {count}</title></rect>'
        )
        x += seg_w + gap
    # Legend row: a swatch + "<tier> <count>" per present tier, always legible.
    lx = 0.0
    for item in present:
        count = int(item["count"])
        tone = _EVIDENCE_TONE.get(str(item["value"]), "var(--surface-soft)")
        caption = f'{item["label"]} {count}'
        parts.append(
            f'<rect x="{_num(lx)}" y="79" width="14" height="14" rx="3" fill="{tone}"/>'
        )
        parts.append(
            f'<text x="{_num(lx + 20)}" y="91" class="ca-num">{_esc(caption)}</text>'
        )
        lx += 14 + 6 + _legend_text_w(caption) + 24
    return Markup(_frame("".join(parts), width, height, label="结论置信度分布图"))


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
    # Shared zero baseline with abs-extent normalisation. For all-positive data
    # (lo == 0) this reduces byte-for-byte to the historical bottom-anchored bars;
    # a negative value drops below the baseline instead of drawing a negative-height
    # rect that escapes the canvas (the old max-only scaling bug).
    vmax = max(v for _, v, _ in plotted) or 1.0
    vmin = min(v for _, v, _ in plotted)
    hi = max(0.0, vmax)
    lo = min(0.0, vmin)
    span = (hi - lo) or 1.0
    zero_y = pad_t + (hi / span) * plot_h  # == baseline_y when lo == 0
    slot = (width - 2 * pad_x) / len(plotted)
    bw = min(slot * 0.6, 64)
    fill = "url(#ca-hatch)" if de_emphasize else "var(--ink-strong)"
    opacity = "0.55" if de_emphasize else "1"
    body.append(
        f'<line x1="{pad_x}" y1="{_num(zero_y)}" x2="{width - pad_x}" '
        f'y2="{_num(zero_y)}" class="ca-axis"/>'
    )
    label_idx = _axis_label_indices(len(plotted))  # thin a dense category axis
    for i, (cat, value, text) in enumerate(plotted):
        cx = pad_x + slot * (i + 0.5)
        bh = abs(value) / span * plot_h
        y_top = zero_y - bh if value >= 0 else zero_y  # grow up (≥0) or down (<0)
        num_y = y_top - 8 if value >= 0 else y_top + bh + 16  # label clears the bar
        body.append(
            f'<rect x="{_num(cx - bw / 2)}" y="{_num(y_top)}" '
            f'width="{_num(bw)}" height="{_num(bh)}" rx="4" fill="{fill}" '
            f'fill-opacity="{opacity}"><title>{_esc(cat)}：{_esc(text)}</title></rect>'
        )
        body.append(
            f'<text x="{_num(cx)}" y="{_num(num_y)}" text-anchor="middle" '
            f'class="ca-num">{_esc(text)}</text>'
        )
        if i in label_idx:
            body.append(
                f'<text x="{_num(cx)}" y="{_num(baseline_y + 20)}" text-anchor="middle" '
                f'class="ca-cat">{_esc(cat)}</text>'
            )
    return _frame("".join(body), width, height)


def _waterfall(
    cats: list[str],
    values: list[float | None],
    value_texts: list[str],
    *,
    title: str,
    de_emphasize: bool,
) -> str:
    """Cumulative bridge: each bar floats between the running total before and after
    its value, so signed contributions read as ups/downs from a shared zero baseline.

    This is a true waterfall — the GMV bridge (流量 +/转化 -/客单价 +) and part-to-whole
    layers (发货前 + 发货后) both render correctly because the vertical scale spans the
    full cumulative extent, not the (possibly near-zero) sum of the components. The old
    sum-normalised version exploded a +17689 contribution to 977px when the net was only
    +3257. Only computable segments are drawn; ``None`` values are skipped. Never raises.
    """
    width, height = 308, 300
    pad_t, pad_b, pad_x = 56, 64, 20
    plot_h = height - pad_t - pad_b
    top_y = pad_t
    plotted = [
        (c, v, t) for c, v, t in zip(cats, values, value_texts) if v is not None
    ]
    if not plotted:
        return _frame(_title(title) + _empty_state(width, height), width, height)
    # Cumulative running totals: the plot band spans [min(0, …), max(0, …)] of the
    # path 0 → c₁ → c₁+c₂ → … so every floating bar stays inside the canvas.
    cumulative = [0.0]
    for _, v, _ in plotted:
        cumulative.append(cumulative[-1] + v)
    hi = max(cumulative)
    lo = min(cumulative)
    span = (hi - lo) or 1.0

    def _y_of(val: float) -> float:  # data value → pixel (hi at the top of the band)
        return top_y + (hi - val) / span * plot_h

    zero_y = _y_of(0.0)
    slot = (width - 2 * pad_x) / len(plotted)
    bw = min(slot * 0.6, 64)
    fill = "url(#ca-hatch)" if de_emphasize else "var(--ink-strong)"
    opacity = "0.55" if de_emphasize else "1"
    body = [_title(title)]
    body.append(
        f'<line x1="{pad_x}" y1="{_num(zero_y)}" x2="{width - pad_x}" '
        f'y2="{_num(zero_y)}" class="ca-axis"/>'
    )
    label_idx = _axis_label_indices(len(plotted))  # thin a dense category axis
    for i, (cat, value, text) in enumerate(plotted):
        cx = pad_x + slot * (i + 0.5)
        y_start, y_end = _y_of(cumulative[i]), _y_of(cumulative[i + 1])
        y_top = min(y_start, y_end)
        seg_h = abs(y_end - y_start)
        body.append(
            f'<rect x="{_num(cx - bw / 2)}" y="{_num(y_top)}" '
            f'width="{_num(bw)}" height="{_num(seg_h)}" rx="4" fill="{fill}" '
            f'fill-opacity="{opacity}"><title>{_esc(cat)}：{_esc(text)}</title></rect>'
        )
        body.append(
            f'<text x="{_num(cx)}" y="{_num(y_top + seg_h / 2)}" text-anchor="middle" '
            f'class="ca-num">{_esc(text)}</text>'
        )
        if i in label_idx:
            body.append(
                f'<text x="{_num(cx)}" y="{_num(top_y + plot_h + 20)}" text-anchor="middle" '
                f'class="ca-cat">{_esc(cat)}</text>'
            )
    return _frame("".join(body), width, height)


def _measure_panel(cats, rows, key, de_emphasize) -> str:
    values = [row.get(key) for row in rows]
    texts = [
        labels.format_number(float(v)) if v is not None else "暂无数据" for v in values
    ]
    return _vbar(cats, values, texts, title=_MEASURE_TITLE[key], de_emphasize=de_emphasize)


def _build_effect_pair(rows, category_key, confidence, de_emphasize) -> str:
    if not rows:
        return ""
    cats = [labels.value_label(str(row.get(category_key))) for row in rows]
    has_any = any(
        row.get("avg_reads") is not None or row.get("avg_collects") is not None
        for row in rows
    )
    if not has_any:
        return ""
    reads = _measure_panel(cats, rows, "avg_reads", de_emphasize)
    collects = _measure_panel(cats, rows, "avg_collects", de_emphasize)
    badge = _chart_badge(confidence, len(rows))
    return f'{badge}<div class="chart-multiples">{reads}{collects}</div>'


def _build_cover(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    return _build_effect_pair(
        result.tables.get("cover_effects", []), "composition_type",
        confidence, _de_emphasize(result),
    )


def _build_copy(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    return _build_effect_pair(
        result.tables.get("copy_effects", []), "copy_angle",
        confidence, _de_emphasize(result),
    )


_BUILDERS["cover_style_effect"] = _build_cover
_BUILDERS["copy_angle_effect"] = _build_copy


def _build_comment_demand(result: AnalysisResult, confidence: ReaderConfidence) -> str:
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
    de = _de_emphasize(result)
    body = _hbar(bar_rows, value_max=max(v for _, v, _, _ in bar_rows), de_emphasize=de)
    return f'{_chart_badge(confidence, total)}{body}'


_BUILDERS["comment_demand_mining"] = _build_comment_demand


_RESPONSE_WINDOWS = (
    ("d0_1_units", "d0_1"),
    ("d1_3_units", "d1_3"),
    ("d4_7_units", "d4_7"),
    ("d8_14_units", "d8_14"),
)


def _line(
    series: list[tuple[str, list[float | None]]],
    x_labels: list[str],
    *,
    de_emphasize: bool,
    suppress_aggregate: bool = False,
) -> str:
    width, height = _VIEW_W, 320
    pad_l, pad_r, pad_t, pad_b = 48, 24, 40, 56
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    baseline_y = pad_t + plot_h
    n_x = len(x_labels)
    xs = [pad_l + (plot_w * i / (n_x - 1) if n_x > 1 else plot_w / 2) for i in range(n_x)]
    all_vals = [v for _, ys in series for v in ys if v is not None]
    if not all_vals:
        return _frame(_empty_state(width, height), width, height)
    vmax = max(all_vals) or 1.0

    def y_of(v: float) -> float:
        return baseline_y - (v / vmax) * plot_h

    body: list[str] = [
        _hgrid(pad_l, width - pad_r, pad_t, baseline_y),
        f'<line x1="{pad_l}" y1="{_num(baseline_y)}" x2="{width - pad_r}" '
        f'y2="{_num(baseline_y)}" class="ca-axis"/>',
    ]
    label_idx = _axis_label_indices(n_x)  # thin a dense x-axis to a readable handful
    for i, label in enumerate(x_labels):
        if i not in label_idx:
            continue
        # Trim ISO dates to MM-DD (mirrors _timeseries_line): a full 'YYYY-MM-DD'
        # tick is ~70px and collides at the ~50px spacing of a dense axis, while
        # MM-DD does not. Non-date labels pass through _short_date untouched.
        body.append(
            f'<text x="{_num(xs[i])}" y="{_num(baseline_y + 20)}" text-anchor="middle" '
            f'class="ca-cat">{_esc(_short_date(label))}</text>'
        )
    # A long series is a shape, not a scatter of dots: keep the connecting path but
    # drop the per-point circles (600 dots is noise + a huge SVG). A short series
    # keeps its markers (also the only glyph for a 1-point series).
    draw_markers = n_x <= _MAX_LINE_MARKERS

    def draw(ys, *, color, opacity, dash):
        pts = [(xs[i], y_of(v)) for i, v in enumerate(ys) if v is not None]
        if len(pts) >= 2:
            d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in pts)
            body.append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-opacity="{opacity}"{dash}/>'
            )
        if draw_markers:
            for x, y in pts:
                body.append(
                    f'<circle cx="{_num(x)}" cy="{_num(y)}" r="4" fill="{color}" '
                    f'fill-opacity="{opacity}"/>'
                )

    has_agg = len(series) > 1 and not suppress_aggregate
    agg: list[float | None] = []
    if has_agg:  # bold aggregate = mean at each x
        for i in range(n_x):
            col = [ys[i] for _, ys in series if ys[i] is not None]
            agg.append(sum(col) / len(col) if col else None)
    # A soft area under the primary line (the aggregate, or the sole series) reads
    # as a shape rather than a wire. Skipped for de-emphasised (thin) data so a
    # low-reliability chart is never dressed up as a confident filled trend.
    primary = agg if has_agg else (series[0][1] if len(series) == 1 else None)
    if primary is not None and not de_emphasize:
        area_pts = [(xs[i], y_of(v)) for i, v in enumerate(primary) if v is not None]
        if len(area_pts) >= 2:
            axp, ayp = zip(*area_pts)
            body.append(_area_fill(axp, ayp, baseline_y, opacity="0.55"))

    line_opacity = "0.35"
    dash = ' stroke-dasharray="4 3"' if de_emphasize else ""
    for name, ys in series:
        draw(ys, color="var(--muted)", opacity=line_opacity, dash=dash)
    if has_agg:
        draw(agg, color="var(--ink-strong)", opacity="0.55" if de_emphasize else "1", dash=dash)
    return _frame("".join(body), width, height)


def _build_response_curve(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    rows = result.tables.get("response_windows", [])
    if not rows:
        return ""
    x_labels = [labels.value_label(key) for _, key in _RESPONSE_WINDOWS]
    series = [
        (
            f'{row.get("note_title") or row.get("note_id")}·{row.get("sku_id")}',
            [row.get(col) for col, _ in _RESPONSE_WINDOWS],
        )
        for row in rows
    ]
    de = _de_emphasize(result)
    body = _line(series, x_labels, de_emphasize=de)
    return f'{_chart_badge(confidence, len(rows))}{body}'


_BUILDERS["content_response_curve"] = _build_response_curve


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _scatter(
    points: list[dict],
    *,
    x_label: str,
    y_label: str,
    median_lines: bool,
) -> str:
    width, height = _VIEW_W, 340
    pad_l, pad_r, pad_t, pad_b = 56, 24, 28, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    if not points:
        return _frame(_empty_state(width, height), width, height)
    xmax = max(p["x"] for p in points) or 1.0
    ymax = max(p["y"] for p in points) or 1.0

    def px(x: float) -> float:
        return pad_l + (x / xmax) * plot_w

    def py(y: float) -> float:
        return pad_t + plot_h - (y / ymax) * plot_h

    body: list[str] = [
        f'<line x1="{pad_l}" y1="{pad_t + plot_h}" x2="{width - pad_r}" '
        f'y2="{pad_t + plot_h}" class="ca-axis"/>',
        f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t + plot_h}" class="ca-axis"/>',
        f'<text x="{width - pad_r}" y="{pad_t + plot_h + 20}" text-anchor="end" '
        f'class="ca-cat">{_esc(x_label)}</text>',
        f'<text x="{pad_l}" y="{pad_t - 12}" class="ca-cat">{_esc(y_label)}</text>',
    ]
    if median_lines and len(points) >= 2:
        mx, my = _median([p["x"] for p in points]), _median([p["y"] for p in points])
        body.append(
            f'<line x1="{_num(px(mx))}" y1="{pad_t}" x2="{_num(px(mx))}" '
            f'y2="{pad_t + plot_h}" class="ca-grid" stroke-dasharray="4 3"/>'
        )
        body.append(
            f'<line x1="{pad_l}" y1="{_num(py(my))}" x2="{width - pad_r}" '
            f'y2="{_num(py(my))}" class="ca-grid" stroke-dasharray="4 3"/>'
        )
    for p in points:
        cx, cy = px(p["x"]), py(p["y"])
        de = p.get("de_emphasize")
        opacity = "0.55" if de else "1"
        if p["shape"] == "hollow":
            fill = "var(--surface)"
            stroke = "var(--muted)" if de else p["tone"]
        else:
            # 2px surface ring separates overlapping marks; a gray ring signals a weak sample
            fill = p["tone"]
            stroke = "var(--muted)" if de else "var(--surface)"
        body.append(
            f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="6" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="2" fill-opacity="{opacity}">'
            f'<title>{_esc(p["label"])}</title></circle>'
        )
        if cx > width / 2:
            tx, anchor = cx - 9, "end"
        else:
            tx, anchor = cx + 9, "start"
        body.append(
            f'<text x="{_num(tx)}" y="{_num(cy + 4)}" text-anchor="{anchor}" class="ca-cat">'
            f'{_esc(p["label"])}</text>'
        )
    return _frame("".join(body), width, height)


def _build_opportunity(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    rows = [
        r for r in result.tables.get("product_opportunities", [])
        if r.get("units") is not None and r.get("gmv") is not None
    ]
    if not rows:
        return ""
    de = _de_emphasize(result)
    points = [
        {
            "x": float(r["units"]),
            "y": float(r["gmv"]),
            "label": str(r.get("sku_name") or r.get("sku_id")),
            "shape": "filled" if r.get("opportunity_type") == "sales_response_present" else "hollow",
            "tone": "var(--ink-strong)",
            "de_emphasize": de,
        }
        for r in rows
    ]
    body = _scatter(points, x_label="销量", y_label="成交金额", median_lines=True)
    return f'{_chart_badge(confidence, len(points))}{body}'


_BUDGET_TONE = {
    "increase": "var(--green-text)",
    "reduce": "var(--red-text)",
    "hold": "var(--muted)",
    "needs_data": "var(--muted)",
}


def _build_paid(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    rows = result.tables.get("paid_traffic_efficiency", [])
    total_spend = sum(float(r.get("spend") or 0) for r in rows)
    plotted = [
        r for r in rows
        if (r.get("spend") or 0) > 0 and r.get("roas_calc") is not None
    ]
    if total_spend <= 0 or not plotted:
        return ""  # honest: no spend / no return -> no efficiency chart
    de = _de_emphasize(result)
    dims = ("campaign_name_optional", "creative_name_optional",
            "note_id_optional", "sku_id_optional", "platform_source")

    def name_of(row: dict) -> str:
        for key in dims:
            if row.get(key):
                return str(row[key])
        return "投放对象"

    points = []
    for r in plotted:
        action = str(r.get("budget_action"))
        points.append(
            {
                "x": float(r["spend"]),
                "y": float(r["roas_calc"]),
                "label": f'{name_of(r)}·{labels.value_label(action)}',
                "shape": "hollow" if action == "needs_data" else "filled",
                "tone": _BUDGET_TONE.get(action, "var(--muted)"),
                "de_emphasize": de,
            }
        )
    body = _scatter(points, x_label="消耗", y_label="投产比 ROAS", median_lines=True)
    return f'{_chart_badge(confidence, len(points))}{body}'


_BUILDERS["product_opportunity_matrix"] = _build_opportunity
_BUILDERS["paid_traffic_efficiency"] = _build_paid


def _short_date(value: object) -> str:
    """Trim an ISO date to MM-DD for a compact axis; pass anything else through.

    Analysis modules normalize dates to canonical ISO ('YYYY-MM-DD') at the source
    (see core_business._gmv_trend / demand_funnel), so this only strips the year for
    a narrow edge tick — it does not re-derive any date format.
    """
    text = str(value)
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        return text[5:]
    return text


def _timeseries_line(
    rows: list[dict],
    *,
    date_key: str,
    value_key: str,
    value_fmt: Callable[[float], str],
    de_emphasize: bool,
    title: str,
    changepoint_dates: frozenset[str] | set[str] = frozenset(),
) -> str:
    """A single metric over a (possibly long) date series.

    Unlike _line, x-tick labels are THINNED to ~6 evenly-spaced dates so a 90-day
    series stays legible. Rows missing value_key are skipped; an all-null series
    degrades to the honest empty state rather than an empty axis.
    """
    width, height = _VIEW_W, 300
    pad_l, pad_r, pad_t, pad_b = 56, 24, 44, 52
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b
    baseline_y = pad_t + plot_h
    pts = [
        (str(r.get(date_key)), float(r[value_key]))
        for r in rows
        if r.get(value_key) is not None
    ]
    if not pts:
        return _frame(_title(title) + _empty_state(width, height), width, height, label=title)
    n = len(pts)
    vmax = max(v for _, v in pts) or 1.0
    xs = [pad_l + (plot_w * i / (n - 1) if n > 1 else plot_w / 2) for i in range(n)]

    def y_of(v: float) -> float:
        return baseline_y - (v / vmax) * plot_h

    body: list[str] = [
        _title(title),
        _hgrid(pad_l, width - pad_r, pad_t, baseline_y),
        f'<line x1="{pad_l}" y1="{_num(baseline_y)}" x2="{width - pad_r}" '
        f'y2="{_num(baseline_y)}" class="ca-axis"/>',
    ]
    # changepoint verticals sit behind the line so the trend stays readable. The
    # label anchor flips near either edge so "结构转折" never clips the plot bounds.
    for i, (d, _) in enumerate(pts):
        if d in changepoint_dates:
            body.append(
                f'<line x1="{_num(xs[i])}" y1="{pad_t}" x2="{_num(xs[i])}" '
                f'y2="{_num(baseline_y)}" class="ca-grid" stroke-dasharray="4 3"/>'
            )
            if xs[i] > width - pad_r - 32:
                anchor = "end"
            elif xs[i] < pad_l + 32:
                anchor = "start"
            else:
                anchor = "middle"
            body.append(
                f'<text x="{_num(xs[i])}" y="{pad_t - 6}" text-anchor="{anchor}" '
                f'class="ca-cat">结构转折</text>'
            )
    color = "var(--ink-strong)"
    opacity = "0.55" if de_emphasize else "1"
    dash = ' stroke-dasharray="4 3"' if de_emphasize else ""
    raw_px = [y_of(v) for _, v in pts]
    # A long daily series drawn point-for-point is a "seismograph". Lift a bold
    # moving-average trend out of it and fade the raw series to a hairline behind;
    # short series stay exact (no smoothing). The endpoint dot + value sit on the
    # bold line so the reader anchors to the trend, not a single noisy last day.
    smooth = n >= _MAX_LINE_MARKERS
    k = max(1, round(n / 18)) if smooth else 0
    trend_px = [y_of(v) for v in _moving_avg([v for _, v in pts], k)] if smooth else raw_px
    if n >= 2:
        if not de_emphasize:  # a soft area only under trustworthy (non-thin) data
            body.append(_area_fill(xs, trend_px, baseline_y, opacity="0.6"))
        if smooth:  # faded raw daily series behind the bold trend
            raw = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in zip(xs, raw_px))
            body.append(
                f'<path d="{raw}" fill="none" stroke="var(--muted)" stroke-width="1" '
                f'stroke-opacity="0.45"{dash}/>'
            )
        path = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in zip(xs, trend_px))
        body.append(
            f'<path d="{path}" fill="none" stroke="{color}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round" stroke-opacity="{opacity}"{dash}/>'
        )
    if smooth:  # name the smoothing honestly — the bold line is a derived average.
        # Right-aligned on the title row so it never collides with the "结构转折"
        # changepoint labels that sit in the band just above the plot.
        body.append(
            f'<text x="{width - pad_r}" y="18" text-anchor="end" class="ca-cat">'
            f'趋势线为 {2 * k + 1} 日移动平均</text>'
        )
    for i in {0, n - 1}:  # anchor first + last observations (single point => one dot)
        body.append(
            f'<circle cx="{_num(xs[i])}" cy="{_num(trend_px[i])}" r="4" '
            f'fill="{color}" fill-opacity="{opacity}"/>'
        )
    last_x, last_v = xs[n - 1], pts[n - 1][1]
    body.append(
        f'<text x="{_num(last_x)}" y="{_num(trend_px[n - 1] - 10)}" text-anchor="end" '
        f'class="ca-num">{_esc(value_fmt(last_v))}</text>'
    )
    ticks = min(6, n)
    if ticks <= 1:
        idxs = [0]
    else:
        step = (n - 1) / (ticks - 1)
        idxs = sorted({round(step * t) for t in range(ticks)})
    for i in idxs:
        body.append(
            f'<text x="{_num(xs[i])}" y="{_num(baseline_y + 20)}" text-anchor="middle" '
            f'class="ca-cat">{_esc(_short_date(pts[i][0]))}</text>'
        )
    return _frame("".join(body), width, height, label=title)


def _rank_bars(
    rows: list[dict],
    *,
    label_key: str,
    value_key: str,
    value_fmt: Callable[[float], str],
    confidence: ReaderConfidence,
    de_emphasize: bool,
    top_n: int = 8,
) -> str:
    """Horizontal bars ranked by value_key descending, top_n kept. Returns "" when
    no row carries a usable value (graceful degradation for absent/empty tables)."""
    clean = [r for r in rows if r.get(value_key) is not None]
    if not clean:
        return ""
    clean = sorted(clean, key=lambda r: float(r[value_key]), reverse=True)[:top_n]
    vmax = max(float(r[value_key]) for r in clean) or 1.0
    de = de_emphasize
    bar_rows = [
        (
            str(r.get(label_key) or "—"),
            float(r[value_key]),
            value_fmt(float(r[value_key])),
            "var(--ink-strong)",
        )
        for r in clean
    ]
    badge = _chart_badge(confidence, len(clean))
    return f'{badge}{_hbar(bar_rows, value_max=vmax, de_emphasize=de)}'


def _build_demand_funnel(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    rows = [
        r for r in result.tables.get("demand_funnel_trend", [])
        if r.get("add_to_cart_users") is not None
    ]
    if not rows:
        return ""
    total_cart = sum(float(r.get("add_to_cart_users") or 0) for r in rows)
    total_pay = sum(float(r.get("paid_buyers") or 0) for r in rows)
    if total_cart <= 0:
        return ""
    de = _de_emphasize(result)
    funnel_rows = [
        ("加购人数", total_cart, labels.format_number(total_cart), "var(--ink-strong)"),
        ("成交人数", total_pay, labels.format_number(total_pay), "var(--ink-strong)"),
    ]
    funnel = _hbar(funnel_rows, value_max=total_cart, de_emphasize=de)
    trend = _timeseries_line(
        rows, date_key="date", value_key="cart_to_pay",
        value_fmt=labels.format_percent, de_emphasize=de,
        title="加购→成交转化率趋势",
    )
    return f'{_chart_badge(confidence, int(total_cart))}{funnel}{trend}'


def _build_core_business(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    rows = [r for r in result.tables.get("business_trend", []) if r.get("gmv") is not None]
    if not rows:
        return ""
    de = _de_emphasize(result)
    changepoints = {str(r.get("date")) for r in rows if r.get("is_changepoint")}
    body = _timeseries_line(
        rows, date_key="date", value_key="gmv",
        value_fmt=labels.format_money, de_emphasize=de,
        title="成交金额(GMV)趋势", changepoint_dates=changepoints,
    )
    return f'{_chart_badge(confidence, len(rows))}{body}'


def _build_channel(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    return _rank_bars(
        result.tables.get("channel_scale", []),
        label_key="carrier_zh", value_key="gmv",
        value_fmt=labels.format_money, confidence=confidence,
        de_emphasize=_de_emphasize(result),
    )


def _build_sku_l2(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    return _rank_bars(
        result.tables.get("sku_category_l2_mix", []),
        label_key="category_l2", value_key="gmv",
        value_fmt=labels.format_money, confidence=confidence,
        de_emphasize=_de_emphasize(result),
    )


def _build_refund_category(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    return _rank_bars(
        result.tables.get("refund_by_category", []),
        label_key="category_l1", value_key="refund_orders",
        value_fmt=labels.format_number, confidence=confidence,
        de_emphasize=_de_emphasize(result),
    )


def _build_audience(result: AnalysisResult, confidence: ReaderConfidence) -> str:
    # findings[0] is the 人群转化对比 finding, so prefer the conversion table; fall
    # back to GMV composition share when conversion data is absent.
    conversion = [
        r for r in result.tables.get("audience_conversion_comparison", [])
        if r.get("conversion") is not None
    ]
    if conversion:
        return _rank_bars(
            conversion, label_key="audience_type", value_key="conversion",
            value_fmt=labels.format_percent, confidence=confidence,
            de_emphasize=_de_emphasize(result),
        )
    return _rank_bars(
        result.tables.get("audience_composition", []),
        label_key="audience_segment", value_key="gmv_share",
        value_fmt=labels.format_percent, confidence=confidence,
        de_emphasize=_de_emphasize(result),
    )


_BUILDERS["demand_funnel_diagnosis"] = _build_demand_funnel
_BUILDERS["core_business_diagnosis"] = _build_core_business
_BUILDERS["channel_structure_diagnosis"] = _build_channel
_BUILDERS["sku_structure_diagnosis"] = _build_sku_l2
_BUILDERS["refund_root_cause_diagnosis"] = _build_refund_category
_BUILDERS["audience_structure_diagnosis"] = _build_audience


# --- Spec-driven template renderers (agent-curated visuals) ----------------
#
# The task-keyed _BUILDERS above own the DETERMINISTIC report path and stay
# untouched. The curation path is different: a curation agent emits only a
# declarative view-spec (template + column binding), and this pure renderer fills
# the SVG from already-selected/ordered rows, reusing the very same SVG primitives
# (_line / _waterfall / _vbar). The agent decides *what it looks like*; the engine
# decides *what the numbers are* — no numeric value is ever authored by the agent.
#
# Contract: byte-deterministic (the primitives use no random ids/timestamps and a
# stable, input-driven element order) and NEVER-RAISE — any malformed template,
# binding, or row degrades to an empty Markup so a single bad view drops without
# blocking the report.

# chart-only whitelist (table templates render as HTML elsewhere, not here).
_CHART_TEMPLATES: frozenset[str] = frozenset(
    {"trend_line", "breakdown_waterfall", "share_bar", "horizontal_bar"}
)

# confidence tags/levels that should render the chart de-emphasised (hatched /
# dashed). Covers the view-spec 强/中/弱 axis, the reader-facing 高/中/低 axis, and
# their English keys, so either confidence model maps consistently.
_WEAK_CONFIDENCE: frozenset[str] = frozenset(
    {"弱", "低", "暂不下定论", "weak", "low", "not_judgable"}
)


def _cell(row: object, key: object) -> object:
    """Read a column from a row, tolerating non-dict rows (returns None)."""
    return row.get(key) if isinstance(row, dict) else None


def _cat_label(value: object) -> str:
    """Category-axis label for a curated/fallback chart cell. A boolean renders 是/否
    (same as the tables via ``format_scalar``), never the raw Python "True"/"False"
    (the "False/True值" leak). Every non-bool value keeps the existing enum→中文
    mapping byte-for-byte, so byte-stable chart output is unchanged."""
    if isinstance(value, bool):
        return "是" if value else "否"
    return labels.value_label(str(value))


def _as_float(value: object) -> float | None:
    """Coerce a cell to float, or None when it is not a finite number. bool is
    treated as non-numeric so a True/False cell never becomes a 1/0 bar."""
    if value is None or isinstance(value, bool):
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num == num and num not in (float("inf"), float("-inf")) else None


def _confidence_de_emphasize(confidence: object) -> bool:
    """Map an optional confidence (ReaderConfidence, a 强/中/弱 tag, or None) to the
    boolean de-emphasis flag the primitives expect. Never raises."""
    if confidence is None:
        return False
    if isinstance(confidence, ReaderConfidence):
        return bool(confidence.de_emphasize)
    return str(confidence) in _WEAK_CONFIDENCE


def render_chart_template(
    template: str,
    rows: list[dict],
    binding: dict,
    *,
    confidence: object = None,
) -> Markup:
    """Render one curated chart template to deterministic inline SVG.

    ``binding`` carries the ``{x, y}`` column keys; ``rows`` are already selected
    and ordered by the caller (no aggregation happens here). Displayed numbers are
    filled from the rows via :mod:`labels`, never from agent text. Returns an empty
    :class:`Markup` for an unknown template, an incomplete binding, or empty/garbage
    rows — the report degrades gracefully rather than raising.
    """
    try:
        if template not in _CHART_TEMPLATES:
            return Markup("")
        if not isinstance(rows, (list, tuple)) or not rows:
            return Markup("")
        if not isinstance(binding, dict):
            return Markup("")
        x_key, y_key = binding.get("x"), binding.get("y")
        if not x_key or not y_key:
            return Markup("")

        de = _confidence_de_emphasize(confidence)
        cats = [_cat_label(_cell(r, x_key)) for r in rows]
        values = [_as_float(_cell(r, y_key)) for r in rows]
        # Value labels are TYPE-AWARE via the shared fact-layer formatter: a percent
        # column reads "64.5%" (not the raw ratio "0.64"), money rounds to whole yuan,
        # counts group — exactly as the tables render the same key. This is the curated
        # + fallback chart path; the task-keyed builders pass their own value_fmt.
        texts = [
            format_scalar(y_key, v) if v is not None else "暂无数据" for v in values
        ]

        # Bar templates cap their category count: 50–250 bars render as unreadable
        # 2px slivers with overlapping numbers (a form failure, like a wall-of-dates
        # table). Ranking bars keep the top-N BY VALUE (SELECT-only — values stay
        # verbatim); a waterfall keeps its first-N so the cumulative story survives.
        if template in ("share_bar", "horizontal_bar") and len(values) > _MAX_BARS:
            keep = sorted(
                range(len(values)),
                key=lambda i: (values[i] is not None, abs(values[i] or 0.0)),
                reverse=True,
            )[:_MAX_BARS]
            cats = [cats[i] for i in keep]
            values = [values[i] for i in keep]
            texts = [texts[i] for i in keep]
        elif template == "breakdown_waterfall" and len(values) > _MAX_BARS:
            cats, values, texts = cats[:_MAX_BARS], values[:_MAX_BARS], texts[:_MAX_BARS]

        if template == "share_bar":
            svg = _vbar(cats, values, texts, title="", de_emphasize=de)
        elif template == "horizontal_bar":
            # Horizontal bars read far better than vertical when the category labels
            # are long CJK strings (search terms, SKU names): _hbar right-aligns and
            # truncates the label while keeping the full text in each bar's <title>.
            vmax = max((v for v in values if v is not None), default=0.0)
            hbar_rows = [
                (cat, v, txt, "var(--ink-strong)")
                for cat, v, txt in zip(cats, values, texts)
            ]
            svg = _hbar(hbar_rows, value_max=vmax, de_emphasize=de)
        elif template == "breakdown_waterfall":
            svg = _waterfall(cats, values, texts, title="", de_emphasize=de)
        else:  # trend_line — a single metric over the bound x column
            svg = _line([(str(y_key), values)], cats, de_emphasize=de)
        return Markup(svg)
    except Exception:  # never-raise: a bad view drops, the report still renders
        logger.exception("render_chart_template failed for template=%r", template)
        return Markup("")
