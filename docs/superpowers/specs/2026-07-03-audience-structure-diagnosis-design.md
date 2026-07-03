# audience_structure_diagnosis — 人群结构诊断 (§6) Design

> Sibling of `refund_structure_diagnosis` (the skeleton). Same module contract,
> stat helpers, and never-raise degradation discipline. Worked example:
> `xhs_ceramics_analytics/analysis/refund_diagnosis.py`.

## Purpose

Answer "不同人群/首购周期的转化差多少、从哪些来源进店、人群构成如何",turning
the shop-page funnel (by audience × first-purchase cycle) plus enter-source and
manual audience-profile data into a prescriptive audience-conversion comparison.
Observational only.

## Files

- Create: `xhs_ceramics_analytics/analysis/audience_structure.py`
- Modify: `xhs_ceramics_analytics/analysis/registry.py` (import + TASKS entry)
- Template: `task_templates/audience_structure_diagnosis.md`
- Test: `tests/test_audience_structure.py`

Identifiers: `TASK_ID = "audience_structure_diagnosis"`,
`TITLE = "人群结构诊断"`, registry key `"audience_structure_diagnosis"`.

## Tables

- **Required:** `shop_page_funnel` → if missing, return `_missing_result` with a
  single `NOT_JUDGABLE` finding. Grain: date × audience_type ×
  first_purchase_cycle.
- **Optional:** `shop_page_source` (date × audience_type × first_purchase_cycle
  × source_page), `audience_profile` (**manual-entry CSV; 9.人群分析 is
  PNG-only, so this table has NO importer/alias mapping and is effectively
  absent in production**).

Column contracts (verbatim from `references/data_contract/`):

- `shop_page_funnel` Required: `shop_visitors, shop_payers,
  first_purchase_cycle`. Optional used here: `date, audience_type,
  product_click_users, visit_click_rate, click_pay_rate, visit_pay_rate`.
- `shop_page_source` Required: `source_page, shop_visitors, enter_pay_rate`.
  Optional used here: `audience_type, first_purchase_cycle, shop_gmv`.
- `audience_profile`: `audience_segment, share, gmv` (manual).

**CRITICAL — real counts available.** `shop_page_funnel` carries real
`shop_visitors` and `shop_payers`, so audience/cycle conversion uses genuine
`k = shop_payers`, `n = shop_visitors` — NO reverse derivation.

## Findings

### Finding 1 — 人群转化对比 (always emitted)

- Aggregate `shop_page_funnel` per `audience_type` (when present):
  `n = Σ shop_visitors`, `k = Σ shop_payers`, conversion `= k/n`.
- When `>= 2` audience groups each with `n > 0`, run
  `two_proportion(k_a, n_a, k_b, n_b)` on the top-2 by visitors; gate "显著" on a
  reported non-trivial `diff`. When `audience_type` absent OR `< 2` groups,
  fall back to the **overall** funnel conversion (`Σshop_payers / Σshop_visitors`
  + Wilson) as the finding body, and log a limitation — still a real finding.
- Evidence `has_controls=False` → ceiling WEAK. Confounders: 人群定义口径,
  流量来源差异, 客单与品类.
- Output `audience_conversion_comparison` (one row per audience_type, or a single
  overall row on fallback).

### Finding 2 — 首购周期漏斗 (degrade-gated)

- Aggregate per `first_purchase_cycle` (Required column): `n = Σ shop_visitors`,
  `k = Σ shop_payers`, conversion + Wilson (`min_n_guard(n)`).
- Identify the weakest cycle (lowest Wilson-lower conversion with adequate n) →
  lever. Report new vs repeat purchase gap when cycles distinguish them.
- Confounders: 券与活动节奏, 复购提醒机制, 客群成熟度. Output
  `first_purchase_cycle_funnel` (one row per cycle).

### Finding 3 — 进店来源结构 (degrade-gated)

- Only when `shop_page_source` present. Per `source_page`:
  `n = Σ shop_visitors`, `k = round(n × bounded_rate(enter_pay_rate))` (rate ×
  base → count). Visitor share `= n / Σn`; when `shop_gmv` present also GMV
  share.
- Rank sources by visitor share (Pareto); Wilson-guard the per-source pay rate
  (`min_n_guard(n)`); flag the highest-traffic low-conversion source as the
  承接优化点.
- Confounders: 来源意图差异, 承接页匹配, 活动引流结构. Output
  `shop_source_structure` (one row per source_page).

### Finding 4 — 人群构成 (permanently degraded in production)

- Only when `audience_profile` present with `share` + `gmv`. Compute share ×
  gmv concentration (which segments carry the money).
- **Because `audience_profile` has no importer (PNG-only source), this finding
  is expected to be degraded/absent in real runs.** When absent, emit a
  `NOT_JUDGABLE`/WEAK finding whose conclusion explicitly says 人群构成需手工录入
  `audience_profile`（9.人群分析 为图片，无法自动导入），并给出补数指引 — do NOT
  silently drop it, so the report always documents the gap.
- Confounders: n/a (composition snapshot). Output `audience_composition`.

## Levers (recommended_action)

- Low-conversion audience → 针对该人群做承接内容与利益点定制（人群包 + 定向笔记）。
- Weak first-purchase cycle → 首购人群补券/信任状；复购人群做召回与复购提醒。
- High-traffic low-conversion source → 优化该来源承接页的相关性与首屏转化。
- Composition skew → 向高 GMV 贡献人群加投，低效人群缩量或换承接。

## Output tables

`audience_conversion_comparison`, `first_purchase_cycle_funnel`,
`shop_source_structure`, `audience_composition`. Emit only those whose inputs
exist.

## Degradation matrix

| Missing | Behaviour |
|---|---|
| `shop_page_funnel` | NOT_JUDGABLE `_missing_result` (only case yielding no real findings). |
| `audience_type` | Finding 1 falls back to overall funnel conversion. |
| `< 2` audience groups | Finding 1 emits overall conversion, comparison skipped. |
| `first_purchase_cycle` single value | Finding 2 emits the one cycle, no gap. |
| `shop_page_source` | Finding 3 skipped, limitation logged. |
| `audience_profile` (typical) | Finding 4 emits a degraded gap-notice finding (not dropped). |

Finding 1 is **always** emitted when the Required table exists → `run()` never
returns an empty findings list.

## Corrections baked in (from design critique)

1. Guard every column with `_table_columns` before SQL reference.
2. Prefer real `shop_payers`/`shop_visitors` counts; no reverse derivation.
3. `bounded_rate(enter_pay_rate)` before `k = round(rate × base)`.
4. `two_proportion` only with `>= 2` groups `n > 0`; gate "显著" on effect size;
   fall back to overall conversion otherwise (never an empty finding).
5. `audience_profile` finding is documented-degraded, never silently dropped —
   its absence is a reported data gap, not a skip.
6. Every `Finding` fills `confounders` + observational caveat; guard all `/0`.
7. Note dedup caveat: funnel rows are per-day; summed visitors/payers may
   double-count returning users across days — flag in caveats.

## Non-goals

- No causal attribution; no new mart; no cross-module audience joins (orders,
  notes); no demographic inference beyond what `audience_type` /
  `audience_profile` literally provide.

## Cross-links

Skeleton: `refund_structure_diagnosis`. Sibling modules this batch:
`core_business_diagnosis` (§2), `search_efficiency_diagnosis` (§5).
