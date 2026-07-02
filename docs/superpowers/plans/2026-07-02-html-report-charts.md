# HTML Report Charts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small set of hand-built inline-SVG charts to the single-file HTML report (Markdown stays chart-free), preserving the report's "no fake certainty" grammar, and remove the dead `plotly` dependency.

**Architecture:** A new module `xhs_ceramics_analytics/reporting/charts.py` owns all SVG generation from **raw** `AnalysisResult.tables` rows. Three dumb primitives (bar, 4-point line, scatter) back 7 charts. `html.py` calls two public entry points — `charts.for_result(result)` (per-result) and `charts.evidence_distribution(evidence_counts)` (report-level) — each returning a `markupsafe.Markup` HTML string (`""` when not chartable). A minimal `reporting/labels.py` extraction lets both `html.py` and `charts.py` share value-labels and number formatters without a circular import.

**Tech Stack:** Python 3.11+, Jinja2 (autoescape ON), markupsafe, pytest. No JavaScript, no charting library, no new runtime dependency.

## Global Constraints

- **HTML only.** The Markdown report (`reporting/markdown.py`) is untouched and stays chart-free and authoritative — copied verbatim from the spec.
- **Single self-contained file.** No `<script>`, no external `src=`/`http(s)://`, no JS. SVG is inline text.
- **Autoescape stays ON.** SVG bypasses it only via `markupsafe.Markup` at the public entry point; every interpolated text node (note IDs, SKU names, angle labels, categories) is escaped with `markupsafe.escape` inside the builder.
- **No fake certainty.** `not_judgable` / missing data → no chart (fall through to the table). Below-confidence samples render de-emphasized (hatch + reduced opacity) with a `样本不足 · n=X` badge. One observed point draws a dot, never a line. No smoothing, regression, or extrapolation. Zero baseline on all magnitude bars. NULL is a gap, never 0.
- **Charts are progressive enhancement.** Every chart sits above the existing collapsed `<details>` table that carries the same numbers; a failed or omitted chart costs the reader no information. Per-chart `try/except → return ""` isolation.
- **Monochrome-first, semantic-only color.** Marks use the report's CSS custom properties (`var(--ink-strong)`, `var(--muted)`, `var(--line)`). Categorical distinction leads with shape + direct label + 45° hatch texture — no categorical hue palette. Semantic pastel tokens only for the evidence distribution and `budget_action` status. No emoji, no icon font, no gradient.
- **Chinese labels only, no new English strings** in reader-facing text. Reuse `labels.VALUE_LABELS` / `labels.format_number` / `labels.format_percent`.
- **Tests use substring `in`/`not in` + `str.split` region scoping** (no DOM parser), matching `tests/test_report_rendering.py`. Assert semantic substrings (labels, classes, badges), never exact pixel coordinates.
- **Design tokens (verbatim, `report.html.j2:8-25`):** `--canvas:#F7F6F3; --surface:#FFFFFF; --surface-soft:#F9F9F8; --ink:#2F3437; --ink-strong:#111111; --muted:#787774; --line:#EAEAEA; --blue-bg:#E1F3FE; --blue-text:#1F6C9F; --green-bg:#EDF3EC; --green-text:#346538; --yellow-bg:#FBF3DB; --yellow-text:#956400; --red-bg:#FDEBEC; --red-text:#9F2F2D;`
- **Tag → color mapping (verbatim, `report.html.j2:272-276`):** `.tag.strong`/`.tag.medium`→green, `.tag.weak`→yellow, `.tag.not_judgable`→red, `.tag.info`→blue.

---

## File Structure

| File | Responsibility |
|---|---|
| `xhs_ceramics_analytics/reporting/labels.py` | **Create.** Shared `VALUE_LABELS` dict, `value_label()`, `format_number()`, `format_percent()`. Extracted verbatim from `html.py` so `charts.py` can reuse them without importing `html.py` (circular). |
| `xhs_ceramics_analytics/reporting/charts.py` | **Create.** All SVG generation: primitives, honesty grammar, 7 builders, and the two public entry points `for_result()` / `evidence_distribution()`. |
| `xhs_ceramics_analytics/reporting/html.py` | **Modify.** Re-import moved symbols from `labels.py`; wire `chart_svg` into `_result_view()` and `evidence_chart_svg` into `_build_report_context()`. |
| `xhs_ceramics_analytics/reporting/templates/report.html.j2` | **Modify.** `.chart` CSS + `@media print`; evidence-chart slot in `#guide`; per-result chart slot in `#analysis`. |
| `xhs_ceramics_analytics/doctor.py` | **Modify (separate commit).** Remove `"plotly"` from `REQUIRED_MODULES`. |
| `pyproject.toml` | **Modify (separate commit).** Remove `plotly` runtime dep. |
| `references/troubleshooting.md` | **Modify (separate commit).** Drop `plotly` from the doctor dep list. |
| `tests/test_report_charts.py` | **Create.** Unit tests for builders + primitives + honesty invariants. |
| `tests/test_report_rendering.py` | **Modify.** Placement, self-contained, security, and fallback assertions. |

## Ground-Truth Data Shapes (verified against source — use these exact columns)

- **`evidence_counts`** (`html.py:_evidence_counts`, list ordered `strong,medium,weak,not_judgable`): `{"value": str, "label": str, "count": int, "help": str}`.
- **`response_windows`** (`response_curve.py`): `note_id, sku_id, publish_time, d0_1_units, d1_3_units, d4_7_units, d8_14_units`. (No `post_units`/`relative_lift`; the four `d*_units` values in COALESCE-to-0 form ARE the 4-point line, x-ordered `d0_1→d1_3→d4_7→d8_14`.)
- **`cover_effects`** (`cover_effect.py`): `composition_type, notes, avg_reads, avg_collects`. `avg_reads`/`avg_collects` may be `None`.
- **`copy_effects`** (`copy_effect.py`): `copy_angle, notes, avg_reads, avg_collects`. Same nullability.
- **`comment_demands`** (`comment_demand.py`): `demand_group, comments, notes, comment_share, example_comments`. `comment_share` is a 0–1 float; groups ∈ `price,link,capacity,gift,other`.
- **`product_opportunities`** (`product_opportunity.py`): `sku_id, sku_name, units, gmv, opportunity_type`. `units`/`gmv` are `None` when `opportunity_type == "needs_sales_data"`. Plotted types: `sales_response_present`, `needs_more_content_or_data`.
- **`paid_traffic_efficiency`** (`paid_traffic.py`): dimension cols + `paid_active_days, spend, impressions, clicks, gmv_optional, roas_calc, ctr_calc, cpc_calc, budget_action`. `roas_calc` is `None` when no return data; `budget_action` ∈ `increase,hold,reduce,needs_data`.

---

## Task 1: Extract `reporting/labels.py` (shared labels + formatters)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/labels.py`
- Modify: `xhs_ceramics_analytics/reporting/html.py:147-218` (the `_VALUE_LABELS` dict), `:974-984` (`_format_percent`, `_format_number`)
- Test: `tests/test_report_rendering.py` (existing suite is the regression gate)

**Interfaces:**
- Produces: `labels.VALUE_LABELS: dict[str, str]`, `labels.value_label(value: str) -> str`, `labels.format_number(value: float) -> str`, `labels.format_percent(value: float) -> str`.

- [ ] **Step 1: Create `labels.py` and move the definitions**

Create `xhs_ceramics_analytics/reporting/labels.py`. Move the **entire** `_VALUE_LABELS = { ... }` dict literal (currently `html.py:147-218`) into this file verbatim, renamed to `VALUE_LABELS` (drop the leading underscore). Then add the two formatter functions (copied verbatim from `html.py:974-984`) and one helper:

```python
"""Shared reader-facing labels and number formatters for the HTML report.

Extracted from html.py so reporting.charts can reuse them without importing
html.py (which imports charts -> would be circular).
"""
from __future__ import annotations

VALUE_LABELS = {
    # <<< paste the full dict body moved verbatim from html.py:147-218 here >>>
}


def value_label(value: str) -> str:
    return VALUE_LABELS.get(value, value)


def format_percent(value: float) -> str:
    percent = value * 100
    decimals = 2 if abs(percent) < 10 else 1
    text = f"{percent:.{decimals}f}".rstrip("0").rstrip(".")
    return f"{text}%"


def format_number(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")
```

- [ ] **Step 2: Re-point `html.py` at the moved symbols**

In `html.py`, delete the moved `_VALUE_LABELS` dict (147-218) and the `_format_percent` / `_format_number` function defs (974-984). Add this import near the top (after the existing `from xhs_ceramics_analytics.reporting.markdown import render_markdown` line):

```python
from xhs_ceramics_analytics.reporting.labels import (
    VALUE_LABELS as _VALUE_LABELS,
    format_number as _format_number,
    format_percent as _format_percent,
)
```

All existing references (`_VALUE_LABELS`, `_format_number`, `_format_percent`) keep working unchanged because the aliases preserve the private names.

- [ ] **Step 3: Run the full existing suite to prove behavior is unchanged**

Run: `python -m pytest tests/test_report_rendering.py -q`
Expected: PASS (same count as before the change; this is a pure move).

- [ ] **Step 4: Commit**

```bash
git add xhs_ceramics_analytics/reporting/labels.py xhs_ceramics_analytics/reporting/html.py
git commit -m "refactor: extract shared labels and number formatters to labels.py"
```

---

## Task 2: `charts.py` foundation — SVG kit, honesty gate, dispatcher

**Files:**
- Create: `xhs_ceramics_analytics/reporting/charts.py`
- Test: `tests/test_report_charts.py`

**Interfaces:**
- Consumes: `labels.value_label`, `labels.format_number`, `labels.format_percent`; `AnalysisResult`, `Finding`; `EvidenceStrength`.
- Produces:
  - `charts.for_result(result: AnalysisResult) -> Markup` — dispatches on `result.task_id`; `Markup("")` when non-chartable, when `findings[0].evidence_strength is NOT_JUDGABLE`, or when a builder raises.
  - `charts.evidence_distribution(evidence_counts: list[dict]) -> Markup` — report-level (implemented in Task 3; stub returns `Markup("")` here).
  - Internal helpers used by later tasks: `_esc`, `_num`, `_frame`, `_empty_state`, `_chart_badge`, `_HATCH`, module constants `_VIEW_W`, `_STRENGTH_LABEL`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_report_charts.py`:

```python
from markupsafe import Markup

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting import charts


def _result(task_id, strength, tables):
    return AnalysisResult(
        task_id=task_id,
        title="t",
        findings=[Finding(title="f", conclusion="c", evidence_strength=strength)],
        tables=tables,
    )


def test_for_result_returns_markup_empty_for_unknown_task():
    result = _result("account_baseline", EvidenceStrength.MEDIUM, {})
    out = charts.for_result(result)
    assert isinstance(out, Markup)
    assert out == ""


def test_for_result_suppresses_not_judgable():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.NOT_JUDGABLE,
        {"cover_effects": [{"composition_type": "flatlay", "notes": 3,
                             "avg_reads": 900.0, "avg_collects": 40.0}]},
    )
    assert charts.for_result(result) == ""


def test_for_result_isolates_builder_exceptions(monkeypatch):
    result = _result("cover_style_effect", EvidenceStrength.MEDIUM, {"cover_effects": [{}]})

    def boom(*args, **kwargs):
        raise ValueError("bad row")

    monkeypatch.setitem(charts._BUILDERS, "cover_style_effect", boom)
    assert charts.for_result(result) == ""


def test_escape_neutralizes_markup():
    assert "<script>" not in charts._esc("<script>alert(1)</script>")
    assert "&lt;script&gt;" in charts._esc("<script>alert(1)</script>")


def test_empty_state_carries_message():
    svg = charts._frame(charts._empty_state(640, 200), 640, 200)
    assert "数据不足，无法判断" in svg
    assert svg.startswith("<svg")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_charts.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'xhs_ceramics_analytics.reporting.charts'`.

- [ ] **Step 3: Implement the foundation**

Create `xhs_ceramics_analytics/reporting/charts.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_charts.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py tests/test_report_charts.py
git commit -m "feat: add charts.py foundation (svg kit, honesty gate, dispatcher)"
```

---

## Task 3: `bar` primitive + evidence-distribution chart + template wiring

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py`
- Modify: `xhs_ceramics_analytics/reporting/html.py:441-473` (`_build_report_context`)
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2` (CSS after line 381; slot after line 723)
- Test: `tests/test_report_charts.py`, `tests/test_report_rendering.py`

**Interfaces:**
- Consumes: `_frame`, `_esc`, `_num`, `_empty_state` (Task 2).
- Produces:
  - `_hbar(rows, *, value_max, de_emphasize) -> str` where `rows` is `list[tuple[label:str, value:float, value_text:str, tone:str]]` — horizontal bars with a shared zero baseline; `tone` is a CSS color string (`"var(--ink-strong)"` or a pastel). Reused by `comment_demand_mining` in Task 5.
  - `evidence_distribution(evidence_counts)` now renders a segmented horizontal bar.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_report_charts.py`:

```python
def test_evidence_distribution_renders_segments_with_counts():
    counts = [
        {"value": "strong", "label": "强", "count": 2, "help": "h"},
        {"value": "medium", "label": "中", "count": 3, "help": "h"},
        {"value": "weak", "label": "弱", "count": 1, "help": "h"},
        {"value": "not_judgable", "label": "不可判断", "count": 4, "help": "h"},
    ]
    svg = charts.evidence_distribution(counts)
    assert "<svg" in svg
    assert "var(--green-bg)" in svg   # strong+medium share green
    assert "var(--yellow-bg)" in svg  # weak
    assert "var(--red-bg)" in svg     # not_judgable
    assert "强 2" in svg and "中 3" in svg and "弱 1" in svg and "不可判断 4" in svg


def test_evidence_distribution_empty_when_no_findings():
    counts = [{"value": v, "label": v, "count": 0, "help": "h"}
              for v in ("strong", "medium", "weak", "not_judgable")]
    assert charts.evidence_distribution(counts) == ""


def test_evidence_distribution_escapes_and_has_no_raw_float():
    counts = [{"value": "strong", "label": "强", "count": 1, "help": "h"}]
    svg = charts.evidence_distribution(counts)
    assert "0.333333" not in svg  # widths are formatted, never raw ratios
```

Add to `tests/test_report_rendering.py` (near the other rendering tests; reuse that file's existing report fixture/helper for `render_html`):

```python
def test_evidence_chart_lands_in_guide_section():
    html = _render_sample_report()  # existing helper in this test module
    guide = html.split('id="guide"', 1)[1].split('id="actions"', 1)[0]
    assert 'class="chart"' in guide
    assert "<svg" in guide
```

> If the test module's existing render helper is named differently, use that name — do not invent a new fixture.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_charts.py -q tests/test_report_rendering.py -q`
Expected: FAIL — `evidence_distribution` returns empty / `class="chart"` not in `#guide`.

- [ ] **Step 3: Implement the `_hbar` primitive and `evidence_distribution`**

In `charts.py`, add:

```python
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
```

- [ ] **Step 4: Wire `evidence_chart_svg` into `_build_report_context`**

In `html.py`, add the import (top, with the other reporting imports):

```python
from xhs_ceramics_analytics.reporting import charts
```

Then in `_build_report_context` (the returned dict, alongside `"evidence_counts": _evidence_counts(findings),`) add:

```python
        "evidence_chart_svg": charts.evidence_distribution(_evidence_counts(findings)),
```

- [ ] **Step 5: Add `.chart` CSS + print block to the template**

In `report.html.j2`, immediately **after** the `.finding-grid { ... }` rule (closes at line 381), insert:

```css
    .chart {
      border: 1px solid #EAEAEA;
      border-radius: 12px;
      padding: 28px;
      background: var(--surface);
      display: grid;
      gap: 12px;
    }
    .chart-badge { align-self: start; }
    .chart-multiples {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 16px;
    }
    .chart-svg { width: 100%; height: auto; display: block; overflow: visible; }
    .chart-svg text {
      font-family: 'SF Pro Display', 'Geist Sans', 'Helvetica Neue', sans-serif;
      fill: var(--ink);
    }
    .chart-svg .ca-title,
    .chart-svg .ca-cat { fill: var(--muted); font-size: 12px; }
    .chart-svg .ca-num {
      fill: var(--ink-strong);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }
    .chart-svg .ca-empty { fill: var(--muted); font-size: 14px; }
    .chart-svg .ca-axis,
    .chart-svg .ca-grid { stroke: var(--line); stroke-width: 1; }
    @media (max-width: 860px) {
      .chart-multiples { grid-template-columns: 1fr; }
    }
    @media print {
      .chart, .chart-svg {
        print-color-adjust: exact;
        -webkit-print-color-adjust: exact;
      }
    }
```

- [ ] **Step 6: Add the evidence-chart slot in `#guide`**

In `report.html.j2`, inside the "这份报告怎么读" `span-12` card, **between** the `<p>可信度说明…</p>` line (723) and `<div class="action-meta-grid">` (724), insert:

```html
          {% if report.evidence_chart_svg %}
          <div class="chart">{{ report.evidence_chart_svg }}</div>
          {% endif %}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_charts.py tests/test_report_rendering.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py xhs_ceramics_analytics/reporting/html.py \
        xhs_ceramics_analytics/reporting/templates/report.html.j2 \
        tests/test_report_charts.py tests/test_report_rendering.py
git commit -m "feat: add evidence-distribution chart and chart wiring to HTML report"
```

---

## Task 4: `_vbar` primitive + cover/copy small-multiple pairs + per-result slot

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py`
- Modify: `xhs_ceramics_analytics/reporting/html.py:476-486` (`_result_view`)
- Modify: `xhs_ceramics_analytics/reporting/templates/report.html.j2` (slot between lines 858–860)
- Test: `tests/test_report_charts.py`, `tests/test_report_rendering.py`

**Interfaces:**
- Consumes: `_frame`, `_esc`, `_num`, `_empty_state`, `_title`, `_chart_badge`, `labels.value_label`, `labels.format_number`.
- Produces:
  - `_vbar(cats, values, value_texts, *, title, de_emphasize) -> str` — vertical single-measure bars, zero baseline; empty-state text when no non-null value. Reused nowhere else but defined generically.
  - `_small_multiple_pair(...)` via the two builders `_build_cover` / `_build_copy` registered in `_BUILDERS`.
  - `_result_view` dict gains `"chart_svg": charts.for_result(result)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_report_charts.py`:

```python
def test_cover_chart_has_two_measure_panels_and_zero_baseline():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.MEDIUM,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 5, "avg_reads": 1200.0, "avg_collects": 48.0},
            {"composition_type": "lifestyle", "notes": 4, "avg_reads": 800.0, "avg_collects": 60.0},
        ]},
    )
    html = charts.for_result(result)
    assert "平均阅读数" in html and "平均收藏数" in html
    assert 'class="chart-multiples"' in html
    assert "可信度 中" in html          # evidence badge present
    assert html.count("<svg") == 2       # one panel per measure


def test_cover_chart_shows_empty_state_for_all_null_measure():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.MEDIUM,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 5, "avg_reads": 1200.0, "avg_collects": None},
        ]},
    )
    html = charts.for_result(result)
    assert "数据不足，无法判断" in html   # the collects panel degrades honestly


def test_cover_chart_weak_evidence_is_de_emphasized():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.WEAK,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 2, "avg_reads": 300.0, "avg_collects": 9.0},
        ]},
    )
    html = charts.for_result(result)
    assert "样本不足" in html
    assert "url(#ca-hatch)" in html


def test_copy_chart_uses_copy_angle_column():
    result = _result(
        "copy_angle_effect",
        EvidenceStrength.MEDIUM,
        {"copy_effects": [
            {"copy_angle": "gift", "notes": 6, "avg_reads": 1100.0, "avg_collects": 70.0},
        ]},
    )
    html = charts.for_result(result)
    assert "送礼角度" in html          # value_label("gift")
    assert "<svg" in html
```

Add to `tests/test_report_rendering.py`:

```python
def test_task_charts_land_in_analysis_section():
    html = _render_sample_report()
    analysis = html.split('id="analysis"', 1)[1]
    assert 'class="chart"' in analysis
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_charts.py tests/test_report_rendering.py -q`
Expected: FAIL — `cover_style_effect` not in `_BUILDERS`; `chart_svg` absent from `#analysis`.

- [ ] **Step 3: Implement `_vbar`, the pair helper, and the two builders**

In `charts.py`, add:

```python
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
```

- [ ] **Step 4: Wire `chart_svg` into `_result_view`**

In `html.py`, in `_result_view` add to the returned dict:

```python
        "chart_svg": charts.for_result(result),
```

- [ ] **Step 5: Add the per-result chart slot in `#analysis`**

In `report.html.j2`, **between** the finding-grid closing `{% endif %}` (line 858) and the `{% for table in result.table_views %}` (line 860), insert:

```html
            {% if result.chart_svg %}
            <div class="chart">{{ result.chart_svg }}</div>
            {% endif %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_charts.py tests/test_report_rendering.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py xhs_ceramics_analytics/reporting/html.py \
        xhs_ceramics_analytics/reporting/templates/report.html.j2 \
        tests/test_report_charts.py tests/test_report_rendering.py
git commit -m "feat: add cover/copy small-multiple bar charts and per-result slot"
```

---

## Task 5: comment-demand horizontal share bar

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py`
- Test: `tests/test_report_charts.py`

**Interfaces:**
- Consumes: `_hbar` (Task 3), `_chart_badge`, `labels.value_label`, `labels.format_percent`.
- Produces: `_build_comment_demand` registered under `comment_demand_mining`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_report_charts.py`:

```python
def test_comment_demand_share_bar_uses_percent_labels():
    result = _result(
        "comment_demand_mining",
        EvidenceStrength.MEDIUM,
        {"comment_demands": [
            {"demand_group": "capacity", "comments": 12, "notes": 5,
             "comment_share": 0.48, "example_comments": ["多大容量"]},
            {"demand_group": "price", "comments": 8, "notes": 4,
             "comment_share": 0.32, "example_comments": ["多少钱"]},
            {"demand_group": "other", "comments": 5, "notes": 3,
             "comment_share": 0.20, "example_comments": ["好看"]},
        ]},
    )
    html = charts.for_result(result)
    assert "<svg" in html
    assert "48%" in html                # format_percent(0.48)
    assert "容量/尺寸需求" in html        # value_label("capacity")
    assert "0.48" not in html           # never a raw ratio


def test_comment_demand_skips_zero_comment_groups():
    result = _result(
        "comment_demand_mining",
        EvidenceStrength.WEAK,
        {"comment_demands": [
            {"demand_group": "capacity", "comments": 3, "notes": 1,
             "comment_share": 1.0, "example_comments": []},
            {"demand_group": "gift", "comments": 0, "notes": 0,
             "comment_share": 0.0, "example_comments": []},
        ]},
    )
    html = charts.for_result(result)
    assert "样本不足" in html            # weak evidence badge
    assert "送礼角度" not in html         # zero-comment group omitted
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report_charts.py -q -k comment_demand`
Expected: FAIL — `comment_demand_mining` returns empty.

- [ ] **Step 3: Implement the builder**

In `charts.py`, add:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report_charts.py -q -k comment_demand`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py tests/test_report_charts.py
git commit -m "feat: add comment-demand share bar chart"
```

---

## Task 6: `line` primitive + content-response-curve (flagship)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py`
- Test: `tests/test_report_charts.py`

**Interfaces:**
- Consumes: `_frame`, `_esc`, `_num`, `_title`, `_chart_badge`, `_empty_state`, `labels.value_label`, `labels.format_number`.
- Produces:
  - `_line(series, x_labels, *, de_emphasize) -> str` — `series` is `list[tuple[name:str, ys:list[float|None]]]`; draws one faint line per series plus a bold `--ink-strong` aggregate (mean of non-null values per x). A series with fewer than 2 non-null points draws **dots only, no `<path>`**.
  - `_build_response_curve` registered under `content_response_curve`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_report_charts.py`:

```python
_WINDOWS = ("d0_1_units", "d1_3_units", "d4_7_units", "d8_14_units")


def _rw(note_id, sku_id, vals):
    row = {"note_id": note_id, "sku_id": sku_id, "publish_time": "2026-06-01"}
    row.update(dict(zip(_WINDOWS, vals)))
    return row


def test_response_curve_draws_lines_over_four_windows():
    result = _result(
        "content_response_curve",
        EvidenceStrength.MEDIUM,
        {"response_windows": [
            _rw("n1", "s1", [2.0, 5.0, 3.0, 1.0]),
            _rw("n2", "s1", [0.0, 4.0, 6.0, 2.0]),
        ]},
    )
    html = charts.for_result(result)
    assert "<svg" in html
    assert "<path" in html                 # multi-point series draw a line
    assert "发布后 0-1 天" in html          # value_label("d0_1")
    assert "发布后 8-14 天" in html


def test_response_curve_single_point_series_draws_dot_not_line():
    result = _result(
        "content_response_curve",
        EvidenceStrength.WEAK,
        {"response_windows": [
            _rw("n1", "s1", [3.0, None, None, None]),
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "<path" not in html             # one observed point never draws a line
    assert "样本不足" in html


def test_response_curve_empty_when_no_rows():
    result = _result("content_response_curve", EvidenceStrength.MEDIUM,
                     {"response_windows": []})
    assert charts.for_result(result) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_charts.py -q -k response_curve`
Expected: FAIL — `content_response_curve` returns empty.

- [ ] **Step 3: Implement `_line` and the builder**

In `charts.py`, add:

```python
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
        f'<line x1="{pad_l}" y1="{_num(baseline_y)}" x2="{width - pad_r}" '
        f'y2="{_num(baseline_y)}" class="ca-axis"/>'
    ]
    for i, label in enumerate(x_labels):
        body.append(
            f'<text x="{_num(xs[i])}" y="{_num(baseline_y + 20)}" text-anchor="middle" '
            f'class="ca-cat">{_esc(label)}</text>'
        )

    def draw(ys, *, color, opacity, dash):
        pts = [(xs[i], y_of(v)) for i, v in enumerate(ys) if v is not None]
        if len(pts) >= 2:
            d = "M" + " L".join(f"{_num(x)} {_num(y)}" for x, y in pts)
            body.append(
                f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
                f'stroke-opacity="{opacity}"{dash}/>'
            )
        for x, y in pts:  # markers (also the only glyph for 1-point series)
            body.append(
                f'<circle cx="{_num(x)}" cy="{_num(y)}" r="3.5" fill="{color}" '
                f'fill-opacity="{opacity}"/>'
            )

    line_opacity = "0.35"
    dash = ' stroke-dasharray="4 3"' if de_emphasize else ""
    for name, ys in series:
        draw(ys, color="var(--muted)", opacity=line_opacity, dash=dash)
    if len(series) > 1:  # bold aggregate = mean of non-null values at each x
        agg: list[float | None] = []
        for i in range(n_x):
            col = [ys[i] for _, ys in series if ys[i] is not None]
            agg.append(sum(col) / len(col) if col else None)
        draw(agg, color="var(--ink-strong)", opacity="1", dash="")
    return _frame("".join(body), width, height)


def _build_response_curve(result: AnalysisResult, strength: EvidenceStrength) -> str:
    rows = result.tables.get("response_windows", [])
    if not rows:
        return ""
    x_labels = [labels.value_label(key) for _, key in _RESPONSE_WINDOWS]
    series = [
        (
            f'{row.get("note_id")}·{row.get("sku_id")}',
            [row.get(col) for col, _ in _RESPONSE_WINDOWS],
        )
        for row in rows
    ]
    de = strength == EvidenceStrength.WEAK
    body = _line(series, x_labels, de_emphasize=de)
    return f'{_title("笔记发布后的销量响应窗口") and ""}{_chart_badge(strength, len(rows))}{body}'


_BUILDERS["content_response_curve"] = _build_response_curve
```

> Note: `_title(...) and ""` is a no-op guard removed below — replace that final `return` line with the clean version:
> `    return f'{_chart_badge(strength, len(rows))}{body}'`

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_charts.py -q -k response_curve`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py tests/test_report_charts.py
git commit -m "feat: add content-response-curve line chart"
```

---

## Task 7: `scatter` primitive + product-opportunity & paid-traffic charts

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py`
- Test: `tests/test_report_charts.py`

**Interfaces:**
- Consumes: `_frame`, `_esc`, `_num`, `_chart_badge`, `_empty_state`, `labels.value_label`, `labels.format_number`.
- Produces:
  - `_scatter(points, *, x_label, y_label, median_lines) -> str`; `points` is `list[dict]` with keys `x:float, y:float, label:str, shape:"filled"|"hollow", tone:str, de_emphasize:bool`.
  - `_build_opportunity` (`product_opportunity_matrix`) and `_build_paid` (`paid_traffic_efficiency`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_report_charts.py`:

```python
def test_opportunity_scatter_plots_only_rows_with_sales():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "青瓷杯", "units": 12.0, "gmv": 480.0,
             "opportunity_type": "sales_response_present"},
            {"sku_id": "b", "sku_name": "礼盒", "units": 1.0, "gmv": 60.0,
             "opportunity_type": "needs_more_content_or_data"},
            {"sku_id": "c", "sku_name": "无数据", "units": None, "gmv": None,
             "opportunity_type": "needs_sales_data"},
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "青瓷杯" in html
    assert "无数据" not in html          # null units/gmv row is not plotted


def test_opportunity_scatter_uses_shape_not_hue_for_type():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "a", "sku_name": "A", "units": 12.0, "gmv": 480.0,
             "opportunity_type": "sales_response_present"},
            {"sku_id": "b", "sku_name": "B", "units": 1.0, "gmv": 60.0,
             "opportunity_type": "needs_more_content_or_data"},
        ]},
    )
    html = charts.for_result(result)
    # hollow marks paint their interior with the surface token, not a new hue
    assert "var(--surface)" in html
    assert "var(--ink-strong)" in html


def test_paid_scatter_suppressed_when_no_spend():
    result = _result(
        "paid_traffic_efficiency",
        EvidenceStrength.WEAK,
        {"paid_traffic_efficiency": [
            {"campaign_name_optional": "c1", "spend": 0.0, "roas_calc": None,
             "gmv_optional": None, "budget_action": "needs_data", "paid_active_days": 1},
        ]},
    )
    assert charts.for_result(result) == ""


def test_paid_scatter_colors_budget_action_status():
    result = _result(
        "paid_traffic_efficiency",
        EvidenceStrength.MEDIUM,
        {"paid_traffic_efficiency": [
            {"campaign_name_optional": "c1", "spend": 300.0, "roas_calc": 4.0,
             "gmv_optional": 1200.0, "budget_action": "increase", "paid_active_days": 5},
            {"campaign_name_optional": "c2", "spend": 250.0, "roas_calc": 0.5,
             "gmv_optional": 125.0, "budget_action": "reduce", "paid_active_days": 4},
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "var(--green-text)" in html   # increase -> good
    assert "var(--red-text)" in html     # reduce -> bad
    assert "增加预算" in html            # value_label("increase")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_report_charts.py -q -k "opportunity or paid"`
Expected: FAIL — neither task registered.

- [ ] **Step 3: Implement `_scatter` and both builders**

In `charts.py`, add:

```python
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
        opacity = "0.55" if p.get("de_emphasize") else "1"
        if p["shape"] == "hollow":
            fill, stroke = "var(--surface)", p["tone"]
        else:
            fill, stroke = p["tone"], p["tone"]
        body.append(
            f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="6" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="2" fill-opacity="{opacity}">'
            f'<title>{_esc(p["label"])}</title></circle>'
        )
        body.append(
            f'<text x="{_num(cx + 9)}" y="{_num(cy + 4)}" class="ca-cat">'
            f'{_esc(p["label"])}</text>'
        )
    return _frame("".join(body), width, height)


def _build_opportunity(result: AnalysisResult, strength: EvidenceStrength) -> str:
    rows = [
        r for r in result.tables.get("product_opportunities", [])
        if r.get("units") is not None and r.get("gmv") is not None
    ]
    if not rows:
        return ""
    de = strength == EvidenceStrength.WEAK
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
    return f'{_chart_badge(strength, len(points))}{body}'


_BUDGET_TONE = {
    "increase": "var(--green-text)",
    "reduce": "var(--red-text)",
    "hold": "var(--muted)",
}


def _build_paid(result: AnalysisResult, strength: EvidenceStrength) -> str:
    rows = result.tables.get("paid_traffic_efficiency", [])
    total_spend = sum(float(r.get("spend") or 0) for r in rows)
    plotted = [
        r for r in rows
        if (r.get("spend") or 0) > 0 and r.get("roas_calc") is not None
    ]
    if total_spend <= 0 or not plotted:
        return ""  # honest: no spend / no return -> no efficiency chart
    de = strength == EvidenceStrength.WEAK
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
                "shape": "filled",
                "tone": _BUDGET_TONE.get(action, "var(--ink-strong)"),
                "de_emphasize": de,
            }
        )
    body = _scatter(points, x_label="消耗", y_label="投产比 ROAS", median_lines=True)
    return f'{_chart_badge(strength, len(points))}{body}'


_BUILDERS["product_opportunity_matrix"] = _build_opportunity
_BUILDERS["paid_traffic_efficiency"] = _build_paid
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_report_charts.py -q -k "opportunity or paid"`
Expected: PASS.

- [ ] **Step 5: Run the whole charts suite**

Run: `python -m pytest tests/test_report_charts.py -q`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py tests/test_report_charts.py
git commit -m "feat: add product-opportunity and paid-traffic scatter charts"
```

---

## Task 8: Cross-cutting invariants — security, self-contained, fallback

**Files:**
- Modify: `tests/test_report_rendering.py`
- Modify: `tests/test_report_charts.py`

**Interfaces:**
- Consumes: `charts.for_result`, the existing `render_html` and its sample-report helper, `charts._BUILDERS`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_report_charts.py` (security — the single autoescape bypass):

```python
def test_builder_escapes_injected_text():
    result = _result(
        "product_opportunity_matrix",
        EvidenceStrength.MEDIUM,
        {"product_opportunities": [
            {"sku_id": "x", "sku_name": "<script>alert(1)</script>",
             "units": 5.0, "gmv": 100.0, "opportunity_type": "sales_response_present"},
        ]},
    )
    html = charts.for_result(result)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
```

Add to `tests/test_report_rendering.py` (self-contained + fallback):

```python
def test_html_report_has_no_script_or_external_refs():
    html = _render_sample_report()
    assert "<script" not in html
    assert "http://" not in html
    assert "https://" not in html
    assert 'src=' not in html


def test_section_keeps_table_when_a_chart_builder_raises(monkeypatch):
    from xhs_ceramics_analytics.reporting import charts

    def boom(*args, **kwargs):
        raise RuntimeError("chart exploded")

    monkeypatch.setitem(charts._BUILDERS, "cover_style_effect", boom)
    html = _render_sample_report()
    # the render still completes and the drill-down table for the section survives
    assert "封面风格效果" in html
    assert 'class="table-details"' in html or "table-details" in html
```

> If the sample report the helper builds has no `cover_style_effect` result, point the monkeypatch at a `task_id` the helper does include (inspect the helper once and pick one from Task 3–7's registered set).

- [ ] **Step 2: Run tests to verify they fail (or already hold)**

Run: `python -m pytest tests/test_report_charts.py tests/test_report_rendering.py -q -k "escape or no_script or keeps_table"`
Expected: The security + fallback assertions pass immediately if the isolation from Task 2 is correct; the external-ref test may reveal an accidental `src=`/URL and must be fixed if it fails. Investigate any FAIL rather than weakening the assertion.

- [ ] **Step 3: If any assertion fails, fix the source (not the test)**

- A stray `http(s)://` or `src=` in emitted SVG → remove it (charts must be self-contained).
- The fallback test failing → confirm `for_result`'s `try/except` wraps the builder call (Task 2) and the template guards the chart with `{% if result.chart_svg %}`.

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest -q`
Expected: PASS (whole project green).

- [ ] **Step 5: Render a real report and eyeball it (dataviz step 7)**

Run the CLI against a sample DB (use the project's existing sample/fixture path — see `tests/` fixtures or `references/data_contract.md`), open the produced `.html` in a browser, and confirm: charts sit above the collapsed tables; evidence chart in 经营导读; no clipped labels; badges read correctly; prints to PDF with color intact.

- [ ] **Step 6: Commit**

```bash
git add tests/test_report_rendering.py tests/test_report_charts.py
git commit -m "test: cover chart security, self-contained, and fallback invariants"
```

---

## Task 9: Remove the dead `plotly` dependency (separate commit)

**Files:**
- Modify: `xhs_ceramics_analytics/doctor.py:20` (`REQUIRED_MODULES`)
- Modify: `pyproject.toml` (runtime deps)
- Modify: `references/troubleshooting.md:~136` (doctor dep list)
- Test: `tests/` doctor test (if present)

**Interfaces:** none (dependency + docs cleanup; no code imports `plotly`).

- [ ] **Step 1: Confirm plotly is imported nowhere**

Run: `grep -rn "plotly" xhs_ceramics_analytics/ tests/`
Expected: only the `doctor.py` `REQUIRED_MODULES` entry (and possibly a doctor test) — no `import plotly` in library code.

- [ ] **Step 2: Remove `plotly` from `REQUIRED_MODULES`**

In `doctor.py`, delete the `"plotly"` entry from the `REQUIRED_MODULES` list/tuple (line ~20). Leave the other modules untouched.

- [ ] **Step 3: Remove `plotly` from `pyproject.toml`**

Delete the `plotly` line from the `[project].dependencies` (or the runtime dependency group). Leave version pins of other deps unchanged.

- [ ] **Step 4: Update the docs dep list**

In `references/troubleshooting.md` (around line 136 where the doctor-required modules are enumerated), remove `plotly` from that list.

- [ ] **Step 5: Run doctor + tests**

Run: `python -m pytest -q` and (if the CLI exposes it) `./scripts/xhs-ca doctor` — or the doctor unit test.
Expected: PASS; doctor no longer requires `plotly`; first-run bootstrap no longer installs a multi-MB unused wheel.

- [ ] **Step 6: Commit**

```bash
git add xhs_ceramics_analytics/doctor.py pyproject.toml references/troubleshooting.md
git commit -m "chore: drop unused plotly runtime dependency"
```

---

## Self-Review

**1. Spec coverage** (against `docs/superpowers/specs/2026-07-02-html-report-charts-design.md`):

- Rendering architecture (charts.py, 3 primitives, `for_result` + `evidence_distribution`, Markup-at-boundary, autoescape ON) → Tasks 2–7. ✓
- Chart catalog — 7 charts / 3 primitives: evidence (T3), cover+copy (T4), comment demand (T5), response curve (T6), opportunity+paid (T7). ✓
- Honesty grammar: not_judgable→no chart (T2 gate); empty series→`数据不足，无法判断` (T2 `_empty_state`, used in T4/T6/T7); weak→hatch+opacity+`样本不足` badge (T4–T7); 1-point→dot-not-line (T6); zero baseline on bars (T3/T4); NULL as gap not 0 (T4 filters None, T6 skips None); Chinese labels via `labels` (all); evidence badge reusing tag CSS (T2 `_chart_badge`). ✓
- Color system: monochrome marks via CSS vars, shape+hatch+direct label; pastel only for evidence (T3) and budget_action (T7). ✓
- Template slotting: evidence in `#guide` span-12 card (T3); per-result between finding-grid endif and table loop (T4); `.chart` CSS + `@media print` (T3). ✓
- Failure/fallback: per-chart try/except (T2); CLI two-layer catch unchanged; fallback test (T8). ✓
- Testing strategy: isolated builder unit tests, placement via `str.split`, honesty invariants, security escape, self-contained, determinism (substrings only), fallback (T8). ✓
- Plotly removal as separate commit (T9). ✓
- Non-goals respected: no Markdown charts, no JS, no dark mode, no general engine, no new analysis. ✓

**2. Placeholder scan:** The only deferred content is the verbatim **move** of the existing `_VALUE_LABELS` dict (T1 Step 1) — a mechanical cut of `html.py:147-218`, not a placeholder. The T6 `return` cleanup note is called out explicitly. Test helper names (`_render_sample_report`) are flagged to match the existing module rather than invent. No `TBD`/`handle edge cases`/"write tests for the above".

**3. Type consistency:**
- `for_result` / `evidence_distribution` return `Markup` everywhere; `""`/`Markup("")` are falsy for the `{% if %}` guards. ✓
- `_BUILDERS` values are `(AnalysisResult, EvidenceStrength) -> str`; all six builders match, all return `""` when not chartable. ✓
- Primitive signatures are fixed once and reused: `_hbar(rows, *, value_max, de_emphasize)` (T3→T5); `_vbar(cats, values, value_texts, *, title, de_emphasize)` (T4); `_line(series, x_labels, *, de_emphasize)` (T6); `_scatter(points, *, x_label, y_label, median_lines)` (T7). Names match across definition and call sites. ✓
- Column names match verified source (`d*_units`, `roas_calc`, `comment_share`, `opportunity_type`, `composition_type`/`copy_angle`, `avg_reads`/`avg_collects`). ✓
- `labels.value_label` / `format_number` / `format_percent` signatures match T1 definitions and all call sites. ✓
