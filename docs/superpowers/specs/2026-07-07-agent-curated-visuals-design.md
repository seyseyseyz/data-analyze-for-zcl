# Agent-Curated Visuals for the Narrative Report — Design

**Date:** 2026-07-07
**Status:** Approved (brainstorming), pending spec review → writing-plans
**Builds on:** `docs/superpowers/specs/2026-07-06-hybrid-report-writer-design.md`

## Problem

The narrative report path produces fluent merchant-facing prose but strips the
structured evidence the deterministic path renders. Measured on the live
`PiGoo手作瓷器2026年4-6月经营诊断报告`:

| | Deterministic path (2026-07-04) | Narrative path (2026-07-08) |
|---|---|---|
| HTML tables | 87 | 1 (appendix only) |
| Inline SVG charts | 305 | 0 |
| Size / lines | 791 KB / 1499 lines | 13 KB / 83 lines |

Root cause: `narrative_render.bundle_to_markdown` consumes only prose claims and
never renders `section.table_ref` / `section.chart_ref`; the narrative HTML uses
a plain markdown→HTML converter that bypasses `charts.for_result` and
`result.tables`. The bundle schema already reserves `table_ref`/`chart_ref` — the
pipe was designed but never connected.

The fix is **not** to dump all 87 tables back in. Per user direction, an agent
must *curate* — decide which tables/charts carry merchant value, how to organize
them, which trustworthy numbers to surface — and that curation must survive
**adversarial multi-reviewer review** so the report never becomes a low-value,
hard-to-read data dump.

## Goal

Each of the 6 domain sections carries agent-curated deterministic visuals
(≤2 tables + ≤1 chart) alongside its narrative prose, where the agent decides the
*view* (template, columns, rows, captions) and a deterministic engine supplies
every *value*. Reach the readability of a human/Codex-written reference report
while keeping numeric trustworthiness absolute.

## Global Constraints

- **Numeric trust boundary (CRITICAL):** the curation agent emits only a
  declarative *view-spec* (template + column/row selection + prose captions). It
  writes **no numeric values** except structural integers (e.g. `top_n`). A
  deterministic engine fills every displayed number from already-computed
  `result.tables`. The gate byte-verifies displayed numbers against the source.
- **No new aggregation:** view-specs may select / sort / TopN / highlight
  existing rows only. No sums, averages, ratios, or numeric-threshold filters —
  L1 already computed the correct calibers; the agent gets no chance to re-derive
  them wrong.
- **Anti-dump cap:** ≤2 tables + ≤1 chart per domain section; every view MUST
  cite a real `supports_claim`. Enforced by the gate as a hard failure.
- **Never-raise / graceful degradation:** any malformed spec, missing table, or
  unresolved review drops that single view; the report still delivers exactly two
  artifacts. A section with zero passing views degrades to prose-only (today's
  behavior), which is not a failure.
- **Delivery contract unchanged:** exactly two artifacts — `<name>.md` +
  `<name>.html`. The full deterministic report and `facts.json`/`results.json`
  are the audit trail, produced on demand, never counted against the two.
- **Host neutrality:** no `claude`/`codex`/`gpt`/`opus`/`sonnet`/`anthropic`/
  `openai` in shipped artifact content.
- **Evidence tier on every view:** `confidence` (强/中/弱) is derived
  deterministically from the source Finding's `evidence_strength`, never authored
  by the agent.
- **TDD:** failing test first. Interpreter is `.venv/bin/python`.

## Architecture

L1 deterministic analysis (13 modules, unchanged) emits `result.tables` with
calibers already correct. The narrative L3 DAG gains one output and one stage:

```
L1 分析 (不动) ──► result.tables (已算好, 口径已对)
                        │
L3 叙事 DAG:            │
  seed ─► fan(≤6 域写手) ──► 每写手额外产出 view_spec[] ◄─┘ (选模板+绑列/行, 无数值)
                │
                ▼
        synth (narrative_bundle, 挂 section.curated_views)
                │
   ┌──► 确定性 gate (引用真实 / 数值一致 / 每域≤上限 / 标题无捏造数字)
   │            │ PASS
   ▼            ▼
 curated_view 引擎        review 阶段: 每域 3 视角评审员投票
 (spec+tables→表HTML+图SVG) │  多数否决 ► drop / revise ► patch
                           ▼
                       patch (≤2 轮, 重挑/减列/换模板) ──► 回 gate+投票
                           │ 收敛
                           ▼
                    continuity ─► 渲染: 散文 + 每域策展表/图 内联
                    ►  <name>.md + <name>.html
```

Curation is folded into the existing **Fan** writer (it already owns its section
and picks `table_ref`/`chart_ref`); it now emits the richer `view_spec[]`. A new
**review** stage runs after the deterministic gate.

### Components (high cohesion, small files)

- `reporting/view_spec.py` — view-spec data model + pure validation.
- `reporting/curated_view.py` — deterministic executor:
  `render_view(spec, result_tables) -> (table_html, chart_svg)`.
- `reporting/charts.py` — generalize the task-keyed builders (`_line`, `_vbar`,
  `_waterfall`, `_scatter`) into spec-driven **template renderers**.
- `reporting/factcheck_gate.py` — extend `run_gate` with view-spec rules.
- `orchestration/narrative_workflow.py` — new `review` stage (multi-reviewer
  vote) + wire `curated_views` into `finalize`.
- `reporting/narrative_render.py` — `bundle_to_markdown` renders
  `section.curated_views` inline (the missing pipe).

## view-spec Contract

Per curated view — declarative, zero numeric values except structural ints:

```jsonc
{
  "view_id": "core.gmv_bridge_table",
  "section_id": "core_business",
  "supports_claim": "core.gmv_bridge",     // REQUIRED — anti-dump
  "template": "breakdown_waterfall",       // whitelist enum (below)
  "source": { "task_id": "core_business_diagnosis", "table": "growth_bridge" },
  "columns": ["component", "delta_gmv"],   // ⊆ source table columns; order = display order
  "column_labels": { "component": "增长来源", "delta_gmv": "对GMV的拉动" },
  "rows": {                                // select / sort / TopN / highlight only — NO aggregation
    "sort_by": "delta_gmv", "order": "desc", "top_n": 5,
    "highlight": { "component": "转化" }   // highlight by existing categorical value, not numeric threshold
  },
  "chart": { "x": "component", "y": "delta_gmv" },  // chart templates only; binds already-chosen columns
  "title": "GMV 增长拆解:谁在拉动、谁在抵消",      // prose, no invented digits
  "how_to_read": "柱子向右为拉动、向左为抵消,越长影响越大",  // one-line caption, no digits
  "why_it_matters": "锁定被转化抵消的那一块,是本周第一优先"  // interpretive hook
}
```

### Templates (whitelist — covers all current chart types)

| template | 用途 | reuses |
|---|---|---|
| `comparison_table` | 两三组对比(新老客、笔记vs商品卡) | markdown table |
| `ranking_table` | TopN 排名(高退款SKU、高贡献笔记) | markdown table |
| `trend_line` | 时间趋势(搜索转化91期、13周GMV) | `_line` |
| `breakdown_waterfall` | 拆解/瀑布(增长归因、发货前后退款) | `_waterfall` |
| `share_bar` | 占比柱(渠道结构、价位带GMV) | `_vbar` |

### Trust & anti-dump rules (gate enforces each)

1. `source.table` must exist in `result.tables`; `columns` ⊆ its real columns;
   `rows` allows only select / sort / TopN / highlight-by-existing-category — no
   aggregation, no numeric-threshold filter.
2. `title` / `column_labels` / `how_to_read` are prose and must not contain bare
   digits outside `facts` (numbers live only in table cells, filled by the
   engine).
3. `supports_claim` required and must reference a real claim in the bundle.
4. ≤2 tables + ≤1 chart per domain section — over-cap is a hard failure.
5. `confidence` (强/中/弱) derived deterministically from the source Finding's
   `evidence_strength`; weak-evidence views carry a "弱" badge.

Execution: `curated_view.render_view` selects columns/rows per spec, fills real
values from the source table into table HTML, and (for chart templates) feeds the
chosen columns to the matching template renderer for deterministic inline SVG.
The agent decides *what it looks like*; the engine decides *what the numbers are*.

## Multi-Reviewer Review (adversarial)

After the deterministic gate passes (numeric trust already guaranteed), a
`review` stage runs per domain. Three reviewers, each a distinct failure-mode
lens — not redundant voters:

| reviewer | 只问一件事 | typical reject |
|---|---|---|
| **价值** | 能让商家做出一个动作吗?还是内部统计琐碎? | "过程指标,商家看了不知道干嘛" |
| **可读性** | 非分析师商家 5 秒看得懂吗? | "7 列太挤 / 列名黑话 / 该用趋势线却用表" |
| **支撑** | 真的证明了 `supports_claim` 那条结论吗? | "视图与结论无关,纯装饰 / 方向相反" |

Adversarial framing: each reviewer defaults to reject when a view is trivial,
hard to read, or does not clearly support its claim. Prefer fewer visuals over a
dump.

Voting (per view, independent) — resolved by strict precedence so every verdict
combination maps to exactly one outcome:
- 3 verdicts `keep / revise / drop` (structured JSON + reason).
1. **drop ≥ 2 → drop** (view removed; section keeps prose).
2. **else keep ≥ 2 → keep** → render. (So 2 keep + 1 drop → keep; 2 keep +
   1 revise → keep.)
3. **else → patch**: a patch agent re-authors the view-spec (different template /
   fewer columns / different source) using merged reasons; re-runs gate + vote.
   (Covers mixed with no majority, e.g. 1 keep + 1 revise + 1 drop, or
   2 revise + 1 keep.)

Bounds & degradation:
- patch ≤ 2 rounds (reuses existing patch machinery); still-failing views are
  dropped, never blocking the report.
- Zero passing views in a section is normal → prose-only.
- Reviewers judge value/readability/support only — they cannot change numbers
  (the deterministic gate already locked those).

Honest tradeoff: LLM reviewers are non-deterministic, so *which views appear* may
vary run-to-run; the *values inside any view that appears* are deterministic and
reproducible. Uncertainty is confined to selection; determinism is welded to
values.

## Audit vs Delivery Coexistence

- **Delivery = hybrid narrative report, always two files** (`<name>.md` +
  `<name>.html`) — prose + per-domain curated visuals. This is what the merchant
  reads.
- **Audit trail = existing deterministic artifacts**: `facts.json` +
  `results.json` (machine-checkable, every number carries a `fact_id`) are the
  complete audit trail; the full deterministic HTML (all tables) is an optional
  human-readable audit view, produced only on request (`--audit` or a plain
  non-narrative `run`), never default, never counted against the two.
- **Per-view provenance:** each curated table/chart footer carries a light stamp
  `来源:core_business_diagnosis · growth_bridge · 证据:中`, so a reader/auditor
  can locate the full source table in the audit trail. Deterministic, zero cost.

Merchant reads the hybrid report; auditor reads facts.json / the full report;
both share one source of numbers and never disagree.

## Testing Strategy (TDD)

- **view_spec validation** (pure): accept valid; reject unknown template /
  nonexistent column / aggregation attempt / missing `supports_claim` / digits in
  title.
- **curated_view engine**: `render_view(spec, tables)` — every cell equals the
  source table; SVG byte-stable (no random ids / timestamps).
- **template renderers** (generalized charts): given a spec, produce the expected
  SVG structure; determinism.
- **gate extension**: one failing case per new rule — ref exists, value-match,
  per-domain ≤2 tables/≤1 chart, caption no-invented-number.
- **vote tally** (pure logic): 2 drop → drop; mixed → patch; all keep → keep;
  patch exhausted → drop; never raises; empty-views section OK.
- **render wiring** (integration): a bundle with `curated_views` →
  `bundle_to_markdown` output actually contains the tables and SVG (the gap being
  closed).
- **degradation**: malformed spec / missing table → view dropped, report still
  produces two artifacts.
- **host neutrality**: shipped artifact content greps clean of vendor/model
  identity.
- **routine**: runtime mirror sync + skill-wiring tests stay green.

## Out of Scope

- Free-form SQL / DuckDB-level view composition (caliber risk too high; rejected
  in favor of templated composition over pre-computed `result.tables`).
- New analysis modules or new metrics — this design only re-presents existing L1
  output.
- Changing the deterministic report renderer's own output.
