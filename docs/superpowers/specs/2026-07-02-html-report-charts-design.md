# HTML Report Charts Design

## Background

The report contract (`references/report_contract.md:24`) says the HTML report
"should also write a single-file HTML report **with charts** and tables." Today
the HTML report (`xhs_ceramics_analytics/reporting/html.py` +
`reporting/templates/report.html.j2`) renders styled tables and text cards but
**zero charts** — `grep` for `chart|plotly|<svg|canvas` in the template finds
only the `--canvas` CSS background variable, and `plotly` (declared in
`pyproject.toml` and gated by `doctor.py:20` `REQUIRED_MODULES`) is **imported
nowhere** in the source. So the contract promises charts, the implementation
ships none, and a multi-MB dependency sits dead in the blocking first-run gate.

This spec adds charts to the HTML report only. The Markdown report is unchanged
and remains chart-free and authoritative.

## Goals

1. Add a small, high-value set of charts to the single-file HTML report that
   speak to a non-technical Xiaohongshu ceramics-shop operator.
2. Preserve the report's core property: **no fake certainty.** Charts must make
   uncertainty and small samples *more* obvious, never hide them behind
   authoritative-looking geometry.
3. Keep the HTML a **true single self-contained file** that renders offline
   (`file://`, CSP `script-src 'none'`, sandboxed iframe, email/preview, GitHub
   blob view) with no network fetch and no JavaScript.
4. Charts are strict progressive enhancement: every chart sits above a table
   that already carries the same numbers, so a failed or omitted chart never
   costs the reader information.
5. Remove the dead `plotly` dependency.

## Non-Goals

- No charts in the Markdown report.
- No JavaScript, no client-side interactivity beyond native SVG `<title>` hover.
- No dark mode for charts (the report is light-only; adding dark properly means
  hand-stepping and validating a second palette against a dark surface — real
  work with no current consumer). Explicitly out of scope.
- No general charting engine. A closed set of three primitives only.
- No new analysis tasks or metrics. Charts read existing `AnalysisResult.tables`.

## Confirmed Decisions

| # | Decision | Choice |
|---|---|---|
| D1 | Rendering mechanism | **Hand-built inline `<svg>` generated in Python.** No plotly, no JS. |
| D2 | Scope | **7 charts across 3 primitives** (bar, 4-point line, scatter). |
| D3 | Dead `plotly` dep | **Remove** from `doctor.py` + `pyproject.toml`, in a separate commit. |
| D5 | Visibility | Charts **always visible**, above the collapsed `<details>` table. |
| D4 | "Don't reimplement a charting library" | Accept the tiny closed primitive set as domain glue (same category as the existing hand-emitted `<table>`); matplotlib-SVG is the documented fallback if a reviewer objects. |

## Rendering Architecture

A new module `xhs_ceramics_analytics/reporting/charts.py` owns all SVG
generation. It exposes small pure functions that take **raw table rows**
(`list[dict]`) plus an evidence/sample context and return an SVG **string**
(`""` when not chartable).

**Three primitives (the ceiling — nothing else):**

1. `bar(...)` — vertical or horizontal single-measure bar, zero baseline.
2. `line(...)` — 4-point line over ordered categorical x (the response windows).
3. `scatter(...)` — 2-measure scatter with optional median crosshairs.

Everything in the catalog is one of these three. The primitives are
deliberately dumb: a linear min→max→pixel map, no scale abstraction, no
auto-axis-layout engine, no dataframe/plugin layer. That is what keeps this on
the "domain glue" side of the design-spec line
(`docs/specs/2026-06-30-xiaohongshu-ceramics-analytics-design.md:35`,
"Do not rewrite a simplified imitation of ... charting").

**Public entry points consumed by `html.py`:**

- `charts.for_result(result: AnalysisResult) -> str` — dispatches on
  `result.task_id` to the right builder; returns `""` for non-chartable tasks
  or when the honesty gate suppresses the chart.
- `charts.evidence_distribution(evidence_counts) -> str` — the report-level
  meta-chart.

**Injection.** `html.py` autoescape stays **on**. SVG is injected via
`markupsafe.Markup` **only** at the point the builder returns it, and the
builder is responsible for escaping every interpolated text node
(`markupsafe.escape`) — note IDs, SKU names, angle labels. This is the single
autoescape bypass in the system and gets its own security test (see Testing).
Charts read the **raw** `result.tables[name]` numbers, never the pre-stringified
`_display_cell` output.

**`html.py` wiring.**
- `_result_view()` gains `chart_svg = charts.for_result(raw_result)`.
- `_build_report_context()` gains `evidence_chart_svg =
  charts.evidence_distribution(...)`.
- No other change to the existing view-building logic.

## Chart Catalog

Ship set: **7 charts, 3 primitives.** Each new primitive serves ≥2 consumers or
a flagship decision (the YAGNI guardrail).

| task_id | Chart | Primitive | Data source (raw table → columns) |
|---|---|---|---|
| report-level | Evidence-strength distribution | segmented horizontal bar | `report.evidence_counts` → `count` per strength |
| `content_response_curve` | Response curve **(flagship)** | line (4-pt) | `response_windows` (long: one row per note-SKU-window) → y = `post_units` (zero-based, an honest absolute count; not `relative_lift`, which misleads on small `pre_units`), x = ordered windows `d0_1→d1_3→d4_7→d8_14`, one faint line per note-SKU |
| `cover_style_effect` | Cover effect | **bar small-multiple pair** | `cover_effects` → `avg_reads` and `avg_collects` per `composition_type` |
| `copy_angle_effect` | Copy-angle effect | **bar small-multiple pair** (same helper) | `copy_effects` → `avg_reads` and `avg_collects` per `copy_angle` |
| `comment_demand_mining` | Demand share | horizontal share bar | `comment_demands` → `comment_share` over the fixed demand groups |
| `product_opportunity_matrix` | Opportunity quadrant | scatter | `product_opportunities` → `units` × `gmv`, median crosshairs, `opportunity_type` (≤2 plotted) by **mark shape** (filled vs hollow) + label |
| `paid_traffic_efficiency` | Paid efficiency | scatter (only when `total_spend > 0`) | `paid_traffic_efficiency` → `spend` × `roas_calc`, `budget_action` (3 values) by **pale-pastel status token** + label |

### Dual-measure correctness (cover / copy)

The naive "grouped bar of `avg_reads` + `avg_collects`" is a hidden dual-axis
chart: reads run in the hundreds–thousands, collects in the tens, so the collect
bars vanish and the comparison lies. dataviz non-negotiable: **never a
dual-axis chart.** Fix: render a **small-multiple pair** — two single-measure
bars (平均阅读数 / 平均收藏数), each with its own zero baseline, sharing the same
category order. Single hue per chart; identity comes from the axis category
labels, not per-bar rainbow.

### Explicitly NOT charted (and why)

- `note_funnel` — per-note *rates*, not funnel stages; a funnel/Sankey would be
  an outright lie.
- `weekly_business_review` — `value` column mixes non-comparable units per row;
  a cross-row bar is a false comparison. Keep status tiles.
- `sku_counterfactual_lift` — overlaps the response-curve story; would need a
  faceting primitive for marginal gain.
- `product_content_interaction` — sparse heatmap for one analyst-flavored
  consumer; new primitive not justified.
- `content_portfolio_optimization` — cheap to add on the scatter later; not a
  top decision now.
- `account_baseline` — genuine time series but needs a time-axis primitive for
  one context/vanity consumer; and it must **never** be dual-axis.
- `reshoot_repost_candidates`, `weekly_experiment_matrix`,
  `data_quality_check`, `ad_data_quality_check`, `hypothesis_knowledge_base`
  — ranked tables / plans / coverage / status / text seed cards; a chart adds
  nothing.

## Honesty & Small-Sample Grammar (hard requirement)

Every builder receives raw `n` and the finding's `evidence_strength`
(`xhs_ceramics_analytics/evidence.py`: `strong|medium|weak|not_judgable`) and
applies one consistent grammar:

1. **Not-judgable / missing data → NO chart.** Return `""`; the existing table
   empty-state shows. Never a misleading zero-bar or blank canvas.
2. **Empty series inside a drawn chart** → explicit centered text
   `数据不足，无法判断`.
3. **Sample gate.** Below the task's confident threshold (mirror the existing
   evidence logic; e.g. reshoot's `_MIN_CONFIDENT_READS = 50.0`,
   `reshoot.py:8`), suppress "confident" geometry: **one observed point draws a
   dot, never a line. No smoothing, no regression, no extrapolation, ever.**
4. **De-emphasis fill.** Small-`n` marks render at ~45% opacity + a 45° SVG
   `<pattern>` hatch (defined once by id, zero JS) + gray stroke, so shaky marks
   read quieter than solid ones.
5. **Badge.** `样本不足 · n=X`, using the reserved yellow evidence token.
6. **Every chart carries its evidence badge** using the report's existing tag
   mapping (`strong`/`medium`→green, `weak`→yellow, `not_judgable`→red); the
   chart's semantic coloring must agree with the evidence tag beside it.
7. **Zero baseline mandatory** on all magnitude bars. **NULL renders as a
   gap/annotation, never 0.**
8. **Plot conservative/shrunk values** (`conservative_collect_rate`) where the
   task computes them, not raw rates; raw may appear only as a faint ghost.
9. **Humanized Chinese labels** via the existing `html.py` formatters and label
   dictionaries (`html.py:9-19`, `23-145`). Zero new English strings.

## Color System (editorial-monochrome, semantic-only)

The report is already a faithful **minimalist-ui** implementation — identical
tokens (`report.html.j2`): canvas `#F7F6F3`, surface `#FFFFFF`/`#F9F9F8`, borders
`#EAEAEA`, ink `#2F3437`/`#111111`, muted `#787774`, the four pale-pastel status
tokens (`--red/blue/green/yellow-bg`/`-text`); fonts SF Pro Display / Geist Mono /
editorial serif; a single ultra-diffuse hover shadow `0 2px 8px rgba(0,0,0,0.04)`;
no emoji, no icon font, no gradient. Charts must inherit this language: **color is
a scarce, semantic resource — never decorative identity.**

So charts are **monochrome-first**, and categorical distinction leads with
**shape, position, direct label, and texture** — not a saturated hue rainbow.
This also satisfies dataviz, which mandates secondary encoding whenever
categorical marks fall below the chroma/contrast floor: here we drop the
saturated fill entirely and lead with those secondary channels, so **no new
categorical hue palette is introduced and nothing needs the CVD validator** —
distinction is colorblind- and print-safe by construction.

- **Bars** (cover/copy small-multiples, comment share): single charcoal fill
  (`--ink`/`--ink-strong`), hairline `#EAEAEA` gridlines, `--muted` axis/labels.
  Identity is the category axis label, never per-bar color.
- **Response line**: faint `--muted` lines (one per note-SKU); the aggregate /
  highlighted line in `--ink`. Notes are never color-coded.
- **Evidence distribution** — the one semantic-color chart. Each segment wears its
  existing pastel status token so the chart matches the tags beside it. Note the
  current CSS collapses **`strong` and `medium` to the same green**
  (`report.html.j2:272-273`), `weak`→yellow (`274`), `not_judgable`→red (`275`);
  the chart therefore distinguishes strong vs medium by **order + direct count
  label**, not a new hue, keeping exact palette parity with the tags.
- **Scatters** (opportunity, paid): monochrome ink marks; categories separated by
  **mark shape + always-on direct label**:
  - `opportunity_type` (≤2 plotted): filled circle (`sales_response_present`) vs
    hollow circle (`needs_more_content_or_data`).
  - `budget_action` (`increase`/`hold`/`reduce`) is genuinely a recommendation
    *status*, so it may carry the pale-pastel status tokens
    (green / neutral-gray / red) — the one place semantic pastel is justified —
    always paired with the direct label, never color alone.
- **Small-sample de-emphasis**: 45° `<pattern>` hatch + reduced opacity +
  `样本不足 · n=X` badge. Texture is minimalist-ui's sanctioned accessibility
  channel and reads in monochrome, print, and forced-colors.
- **Text wears text tokens** (`--ink`, `--muted`), never a mark color. Labels are
  text or clean SVG primitives only — **no emoji, no icon font** (keeps the
  existing "no Lucide / no gradient" test green).

## Marks & Anatomy

Per `dataviz/references/marks-and-anatomy.md`:

- Thin marks; bar data-ends 4px rounded, anchored to the zero baseline; 2px
  lines; markers ≥8px; a 2px surface gap between adjacent bars; a 2px surface
  ring on overlapping scatter marks.
- Selective **direct labels** (never a number on every point); recessive grid.
- `viewBox` + `width:100%` so charts collapse responsively at the existing 860px
  breakpoint; font uses the report's stack; axis ticks `tabular-nums`.
- **Hover:** native SVG `<title>` on each mark (zero JS) gives the value tooltip;
  the always-present drill-down table covers the rest of what interactivity would.

## Template Slotting

`reporting/templates/report.html.j2`. Charts render **outside `<details>`**;
raw tables stay collapsed below as drill-down + fallback. Every injection is
guarded by `{% if x.chart_svg %}`.

1. **Evidence meta-chart** → `#guide` section, inside the "这份报告怎么读"
   `span-7` card near the `evidence_counts` loop (**~lines 722–736**). The bar
   visualizes exactly what that card explains in words.
2. **Per-result charts** → in `#analysis`, **between the finding-grid
   `{% endif %}` (line 858) and the table loop `{% for table ... %}` (line
   860)**. `.panel-body` is `display:grid; gap:18px` (`report.html.j2:371`), so a
   chart stacks as a clean row above the tables. This is the primary
   always-visible slot.

**CSS additions:** a `.chart` wrapper reusing the card shell (`1px solid
var(--line)`, `border-radius:12px`, `28px` padding); `<text>` in `--ink`/`--muted`;
a small `@media print { .chart { print-color-adjust: exact; } }` block (none
exists today), so charts survive printing to PDF.

## Failure & Fallback (consistent with the report contract)

- **Per-chart isolation:** every builder call in `charts.for_result` is wrapped
  `try: ... except Exception: log; return ""`. One broken chart degrades to the
  table already present — never blanks a section, never aborts the render.
- **Two-layer:** the existing `cli.py:83-100` catch is unchanged — catastrophic
  HTML failure still keeps the `.md`, writes `render_errors.txt`, and removes any
  stale `.html`.
- **Markdown is authoritative and chart-free**, always succeeds.
- **No runtime dependency to fail:** hand-emitted SVG has no charting library to
  be missing — the reason `plotly` can leave the blocking gate.

## Testing Strategy

The existing suite (`tests/test_report_rendering.py`) uses substring `in`/`not
in` and `str.split` region scoping — no DOM parser. Match that.

- **Unit-test builders in isolation** (primary): call each builder with crafted
  raw rows, assert on the returned SVG string. Cheaper and more precise than a
  full render.
- **Presence/placement:** `assert "<svg" in html`; `assert 'class="chart' in
  html`; region-scope with `html.split('id="analysis"',1)[1]` to prove task
  charts land in `#analysis` and the evidence chart in `#guide`.
- **Honesty invariants (highest value):** `样本不足` present below threshold;
  `数据不足，无法判断` for not-judgable/empty; **no raw floats** (extend the
  existing number-formatting test); the line `<path>` is **absent** on a
  1-point series.
- **Security:** feed a `note_id`/`sku_name` containing `<script>`; assert
  `&lt;script&gt;` present and `<script>` absent (the Markup-bypass escape test).
- **Self-contained invariants:** `assert "<script" not in html`; no external
  `src=`/`http`; keep the existing "no gradient / no Lucide" test green.
- **Determinism:** assert semantic substrings (labels, classes, badges), never
  exact pixel coordinates.
- **Fallback:** extend the CLI test — force a builder to raise; assert the
  section still renders its table and the rest of the HTML is intact.

## Plotly Removal (separate commit)

Independent of the chart work, in its own reviewable commit:
- Remove `"plotly"` from `REQUIRED_MODULES` (`doctor.py:20`).
- Remove `plotly` from `pyproject.toml` runtime deps.
- Update `references/troubleshooting.md:136` and any doctor-list docs that
  enumerate the runtime deps.
- No code imports `plotly`, so nothing else changes; this only speeds bootstrap
  and unblocks first run.

## First-Version Boundary

- 7 charts, 3 primitives, light mode only, zero JS, single file.
- Monochrome-first: no categorical hue palette; identity via shape + direct
  label + texture. Semantic pastel only for evidence and `budget_action` status.
- Scatter is included (serves 2 consumers). Heatmap, time-axis, and dumbbell are
  **out** — each would serve one consumer today.
- If a scatter's category count later exceeds the available shapes, extras fold
  to a neutral "其他" shape/label; no rainbow of hues is ever introduced.
