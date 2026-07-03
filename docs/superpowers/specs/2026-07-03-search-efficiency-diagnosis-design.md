# search_efficiency_diagnosis — 搜索效率诊断 (§5) Design

> Sibling of `refund_structure_diagnosis` (the skeleton). Same module contract,
> stat helpers, and never-raise degradation discipline. Worked example:
> `xhs_ceramics_analytics/analysis/refund_diagnosis.py`.

## Purpose

Answer "搜索这条路的成交效率如何、哪个载体更能承接搜索流量、哪些搜索词是高机会
或高流失",turning search overview + per-term aggregates into a prescriptive
carrier comparison + conversion trend + search-term opportunity/leak list.
Observational only.

## Files

- Create: `xhs_ceramics_analytics/analysis/search_efficiency.py`
- Modify: `xhs_ceramics_analytics/analysis/registry.py` (import + TASKS entry)
- Template: `task_templates/search_efficiency_diagnosis.md`
- Test: `tests/test_search_efficiency.py`

Identifiers: `TASK_ID = "search_efficiency_diagnosis"`, `TITLE = "搜索效率诊断"`,
registry key `"search_efficiency_diagnosis"`.

## Tables

- **Required:** `search_overview` → if missing, return `_missing_result` with a
  single `NOT_JUDGABLE` finding. Grain: one row per `date` × `carrier`.
- **Optional:** `search_terms` (grain: one row per `search_term`, whole-period,
  NO date column).

Column contracts (verbatim from `references/data_contract/`):

- `search_overview` Required: `date, carrier, card_impression_users,
  product_click_rate, pay_conversion`. Optional used here: `gmv, paid_orders,
  paid_buyers, product_click_users`.
- `search_terms` Required: `search_term, card_impression_users,
  product_click_rate, pay_conversion`. Optional used here: `gmv, paid_buyers,
  product_click_users`.

**Caliber:** `card_impression_users` = 卡片曝光人数 (the funnel base);
`product_click_rate` and `pay_conversion` are rates → normalise via
`bounded_rate`.

## Findings

### Finding 1 — 载体搜索效率对比 (always emitted)

- Aggregate `search_overview` per `carrier`: `impressions = Σ
  card_impression_users`.
- Payers per carrier — **prefer real counts**: when `paid_buyers` present use
  `k = Σ paid_buyers`; else **forward-derive** (not reverse):
  `k = round(Σ card_impression_users × bounded_rate(product_click_rate) ×
  bounded_rate(pay_conversion))` at the row level then summed. Never divide by a
  rate here — search derives the numerator forward.
- Effectiveness per carrier = `k / impressions`.
- When `>= 2` carriers each with `impressions > 0`, run
  `two_proportion(k_a, n_a, k_b, n_b)` on the top-2 carriers by impressions;
  gate "显著" on a reported non-trivial `diff`. With `< 2` carriers, emit the
  single-carrier effectiveness and log a limitation (still a real finding).
- Evidence `has_controls=False` → ceiling WEAK. Confounders: 载体流量结构,
  搜索意图差异, 品类混合.
- Output `carrier_search_efficiency` (one row per carrier).

### Finding 2 — 搜索转化时间趋势 (degrade-gated)

- Only when `date` present with `>= 2` distinct dates. Series =
  `[(date_str, AVG(bounded_rate(pay_conversion)))]` grouped by date, ordered.
- `mom_change` + overall `direction_label`; per-step deltas in `appendix`.
- Report direction + magnitude only; no significance test on the trend.
- With `< 2` dates, skip with a limitation.
- Confounders: 搜索大盘季节性, 活动节奏. Output `search_conversion_trend`.

### Finding 3 — 高机会 / 高流失搜索词 (degrade-gated)

- Only when `search_terms` present. Per term: `n = card_impression_users`,
  `k` = `paid_buyers` if present else `round(n × bounded_rate(product_click_rate)
  × bounded_rate(pay_conversion))`.
- Baseline = impression-weighted mean effectiveness `Σk / Σn`.
- Classification via Wilson interval (guard `min_n_guard(n)`):
  - **高机会 (opportunity):** Wilson **lower** bound `> baseline` — reliably
    above-average conversion → scale exposure / bid up / make dedicated content.
  - **高流失 (leak):** Wilson **upper** bound `< baseline` — reliably
    below-average → suppress spend / fix landing relevance / re-map intent.
- Pareto: rank by `card_impression_users` (or `gmv` when present) to surface the
  high-traffic terms first; note that terms below `MIN_ORDERS_FOR_RATE` are
  listed but unranked (small-sample).
- Confounders: 词意图混合, 季节性, 竞争度. Output `search_term_opportunities`
  (one row per term with class label). `next_test`: 对高机会词做定向内容/加投后复测转化。

## Levers (recommended_action)

- `carrier_gap` → 向高转化载体倾斜搜索承接内容与预算。
- `conversion_trend_decline` → 排查搜索承接页与词-货匹配，止跌优先。
- `opportunity_terms` → 高机会词加投 / 做定向笔记与商详承接。
- `leak_terms` → 高流失词降权 / 修词-货匹配 / 修承接页相关性。

## Output tables

`carrier_search_efficiency`, `search_conversion_trend`,
`search_term_opportunities`. Emit only those whose inputs exist.

## Degradation matrix

| Missing | Behaviour |
|---|---|
| `search_overview` | NOT_JUDGABLE `_missing_result` (only case yielding no real findings). |
| `paid_buyers` in search_overview | forward-derive payers from rates (documented in caveat). |
| `< 2` carriers | single-carrier effectiveness emitted; comparison skipped. |
| `date` / `< 2` dates | Finding 2 skipped, limitation logged. |
| `search_terms` | Finding 3 skipped, limitation logged. |
| terms `n < MIN_ORDERS_FOR_RATE` | listed but not classified (small-sample). |

Finding 1 is **always** emitted when the Required table exists → `run()` never
returns an empty findings list.

## Corrections baked in (from design critique)

1. Guard every column with `_table_columns` before SQL reference.
2. `bounded_rate` on `product_click_rate` / `pay_conversion` before math.
3. Search derives the numerator **forward** (impressions × rates); never
   reverse-derive `n = k / rate` here.
4. Prefer real `paid_buyers` over the forward-derived numerator when present.
5. `two_proportion` only with `>= 2` carriers `n > 0`; gate "显著" on effect size.
6. Small-sample terms (`n < MIN_ORDERS_FOR_RATE`) listed but not classified.
7. Every `Finding` fills `confounders` + observational caveat; guard all `/0`.

## Non-goals

- No causal attribution; no new mart; no paid-search/ad overlap (that is
  `paid_traffic_efficiency`); no keyword NLP/clustering — classification is
  purely statistical (Wilson vs baseline).

## Cross-links

Skeleton: `refund_structure_diagnosis`. Sibling modules this batch:
`core_business_diagnosis` (§2), `audience_structure_diagnosis` (§6).
