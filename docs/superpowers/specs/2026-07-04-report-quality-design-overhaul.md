# Report-Quality Design Overhaul — Spec

**Date:** 2026-07-04
**Goal:** Fix 13 report defects at their design source (shared layers), not per-module patches.

## Principle

Each defect cluster traces to a *missing or duplicated abstraction*. We fix the abstraction
once and retrofit consumers onto it. No symptom patches.

## Global constraints

- Python 3.11+; `.venv/bin/python` is the interpreter. Ruff line-length 100.
- Every module degrades, never raises, on missing table/column (existing contract).
- TDD: failing test → minimal impl → green. Preserve all existing green tests.
- After code: sync skill mirror (`scripts/sync-runtime`), regen real-data demo, republish skill.
- No Co-Authored-By trailer.

---

## A. Shared funnel-scope normalization layer  (fixes #1, #3)

**Root cause:** `shop_page_funnel` carries a `全部` rollup row (= 新客+老客) and cumulative
`first_purchase_cycle` windows (180天 ⊂ 365天). `audience_structure` normalizes this inline;
`core_business` does not — so it double-counts visitors and its two-proportion test compares
新客 vs 全部 (subset vs superset). `#3`: identical 180/365 rows get a meaningless "weakest".

**Fix:** New `xhs_ceramics_analytics/analysis/funnel_scope.py` owning:
- `ROLLUP = "全部"`
- `canonical_cycle(cycles) -> str | None` — moved verbatim from `audience_structure._canonical_cycle`.
- `normalize_funnel_rows(rows, has_audience, has_cycle) -> (segment_rows, rollup_rows, canonical_cycle)`
  — extracted from `audience_structure._conversion_finding` lines 113-137: drop rollup, collapse to
  widest numeric cycle window.

Retrofit:
- `audience_structure` imports and delegates (behavior identical → existing tests stay green;
  delete the now-duplicated inline logic and local `_canonical_cycle`).
- `core_business._funnel_finding`: normalize first; sum stage counts over `segment_rows`
  (rollup removed, single canonical window). Prefer `rollup_rows` for the store-wide `visit_pay`
  total when present (mirrors audience_structure). Add the canonical-window caveat.
- `core_business._audience_conversion`: aggregate over `segment_rows` only → agg holds 新客/老客,
  never 全部; top-2 test compares 新客 vs 老客. `audience_top2` reads `['新客','老客']`.
- `#3`: when the two compared cycles are numerically equal, emit "周期为累计窗口，无有效差异" rather
  than declaring a weakest.

---

## B. Timeseries hardening + shared trend_summary  (fixes #4, #5; enables #7)

**Root cause:** (a) `_parse_date` only accepts ISO — real dates are integer `YYYYMMDD`, so
`dow_seasonality`/`changepoint_date` silently degrade (`peak_dow: None`). (b) `changepoint` has
no minimum-segment guard → can return the last index with a one-point tail (endpoint artifact,
`20260630`). (c) Three modules judge trend by `series[-1] - series[0]` — fragile on noisy daily data.

**Fix in `analytics/timeseries.py`:**
- `_parse_date`: add `"%Y%m%d"` to the format loop so integer/8-digit `20260401` parses. Keeps ISO.
- `changepoint(values, min_segment=3)`: restrict split to `range(min_segment, n - min_segment + 1)`
  so both segments have ≥ `min_segment` points; return the None dict when `n < 2*min_segment`.
  Preserves `test_changepoint_detects_step` (index 5 in n=10 stays argmax); excludes single-point tails.

**New `trend_summary(series) -> dict`** (`analytics/trends.py`): robust direction via ordinary
least-squares slope over the index (uses all points, not endpoints). Returns
`{direction, slope, first_value, last_value, start_period, end_period, n}`. `direction` uses the
existing `direction_label` threshold on `slope`. For monotone series slope-sign == endpoint-sign, so
`test_*_trend_reports_direction` stay green; for noisy series it is honest.

Retrofit `core_business._gmv_trend`, `refund_diagnosis._trend_finding`, `search_efficiency._trend_finding`:
- Direction from `trend_summary`, not endpoints.
- Reframe conclusions to "整体呈{direction}趋势（{n}期，起 X 止 Y）" + a daily-volatility caveat.
- **Move `mom_change` per-period `delta`/`pct`/`direction` into the trend TABLE columns**
  (`business_trend`/`refund_trend`/`search_conversion_trend`) where the formatter renders them.
- `appendix` becomes a concise methods sentence (no raw `str(steps)` dump). This resolves #7 at source:
  per-period detail lives in the structured table, not a stringified list.

---

## C. Shared report value-formatter  (fixes #8, #9, #10; #7 finalized)

**Root cause:** Two renderers diverge. `markdown.py` has zero value formatting (raw floats, `None`,
int dates); `html.py._display_cell` formats numbers but has no date branch, and both render a shell
for 0-row tables.

**Fix:** New `xhs_ceramics_analytics/reporting/formatting.py`:
- `format_scalar(field_name, value) -> str` — the unified cell/keynumber formatter: list/tuple join,
  `None → "暂无数据"`, bool → 是/否, string value-labels, **date fields → `YYYY-MM-DD`** (int
  `20260630` and ISO both), percent fields, money, number rounding. `html._display_cell` becomes a
  thin wrapper; `markdown.py` key_numbers and table cells route through it.
- `should_render_table(rows) -> bool` — both renderers skip empty tables (HTML: filter `table_views`;
  MD: skip the `表格 … 0 行` line). Preserve the non-empty `共 N 行，当前展示 M 行` format.
- Markdown key_numbers keys route through `_field_label`; table names/columns through the label maps
  — so the `.md` twin matches HTML labels.
- Centralize `labels.format_percent`/`format_number` usage into the formatter (import into markdown).

Date fields set: names ending `_date` plus `date`, `changepoint_date`, `week_start`, `week_end`, `period`.

---

## D. Refund / SKU caliber semantics  (fixes #2, #11, #12)

**#2 root cause:** `refund_diagnosis._layer_finding` puts three layers in one table sharing a single
`total` denominator, but `pre_ship`+`post_ship` partition the ship-stage axis (sum 100%) while
`return` is a different, overlapping axis → column sums 127%, implying additivity.
**Fix:** Add an `axis` field. `pre_ship`/`post_ship` → `axis="ship_stage"`, `share` = amount / (pre+post)
so they cleanly partition. `return` → `axis="return_type"`, share = amount / total, labeled "占总退款额",
with a caveat that it is a post-ship subset, not part of the ship-stage partition. `dominant`/`dominant_share`
computed over ship-stage rows only.

**#11:** Add brief cross-reference caveats between the three pre/post-ship analyses
(`refund_diagnosis` = amount share; `refund_root_cause` = order-weighted rate; `channel_structure` =
per-channel rate) so the reader knows they are different calibers, not repetition.

**#12:** `sku_structure`: the "3405 有效 SKU" (gmv>0) and the 3991-row `sku_conversion_and_aov`
(add_to_cart_users>0) are different universes. Add `conversion_universe` key_number + a caveat naming
both filters so the counts are reconciled explicitly.

---

## E. Report title from --name  (fixes #13)

**Root cause:** `--name` reaches only output filenames (`cli.py:143-144`); both renderers hardcode
`# 小红书账号分析报告`. **Fix:** `render_markdown(results, title=None)` and
`render_html(results, title=None)` accept a title; `cli.py` passes `basename`. Fallback stays
`小红书账号分析报告`. MD H1 (markdown.py:32) and HTML template (`report.html.j2:62,777`) use it.

---

## Verification

`.venv/bin/python -m pytest` (full), `ruff check`, `scripts/sync-runtime`, mirror pytest,
regen `/tmp/xhs-demo-root` real-data report, spot-check the 13 defects are gone, republish skill.
