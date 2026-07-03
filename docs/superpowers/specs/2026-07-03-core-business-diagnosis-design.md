# core_business_diagnosis — 核心经营结构诊断 (§2) Design

> Sibling of `refund_structure_diagnosis` (the skeleton). Same module contract,
> stat helpers, and never-raise degradation discipline. Worked example:
> `xhs_ceramics_analytics/analysis/refund_diagnosis.py`.

## Purpose

Answer "生意的整体盘子有多大、靠什么载体/渠道成交、店铺页在哪一步漏人",
turning the daily business overview into a prescriptive snapshot + trend +
carrier/channel structure + shop-page funnel diagnosis. Observational only —
report direction and effect size, never causal claims.

## Files

- Create: `xhs_ceramics_analytics/analysis/core_business.py`
- Modify: `xhs_ceramics_analytics/analysis/registry.py` (import + TASKS entry)
- Template: `task_templates/core_business_diagnosis.md`
- Test: `tests/test_core_business.py`

Identifiers: `TASK_ID = "core_business_diagnosis"`, `TITLE = "核心经营结构诊断"`,
registry key `"core_business_diagnosis"`.

## Tables

- **Required:** `business_overview_daily` → if missing, return `_missing_result`
  with a single `NOT_JUDGABLE` finding. Grain: one row per `date` (YYYYMMDD int).
- **Optional:** `traffic_source` (grain xhs_id × channel × note_type),
  `shop_page_funnel` (grain date × audience_type × first_purchase_cycle).

Column contracts (verbatim from `references/data_contract/`):

- `business_overview_daily` Required: `date, gmv, paid_orders, paid_buyers, aov`.
  Optional used here: `note_gmv, card_gmv, note_paid_orders, card_paid_orders,
  product_visitors, paid_units, pay_conversion_pv, pay_conversion_uv,
  total_visitors`.
- `traffic_source` Required: `xhs_id, channel, product_clicks,
  product_click_users`. Optional used here: `paid_buyers, pay_conversion_uv, gmv`.
- `shop_page_funnel` Required: `shop_visitors, shop_payers,
  first_purchase_cycle`. Optional used here: `product_click_users,
  visit_click_rate, click_pay_rate, visit_pay_rate`.

**CRITICAL — note/card is a COLUMN split, not a row dimension.** Carrier
structure comes from `note_gmv`/`card_gmv` (+ `note_paid_orders`/
`card_paid_orders`) columns on each daily row, NOT a `carrier` column.

## Findings

### Finding 1 — 整体经营快照 + 时间趋势 (always emitted)

- `SUM(gmv)`, `SUM(paid_orders)`, `SUM(paid_buyers)`, `SUM(paid_units)` (guard
  each column present).
- `aov_derived = gmv / paid_buyers` when `paid_buyers > 0`; else fall back to the
  `aov` Required column (report which was used).
- Pay conversion: prefer real `paid_buyers / product_visitors` when
  `product_visitors` present and `> 0`; else average `pay_conversion_uv`
  (normalise each via `bounded_rate`).
- Trend: `mom_change` over `[(date_str, gmv), ...]` ordered by date; report
  overall `direction_label` from first→last plus per-step deltas in `appendix`.
- Evidence: `has_controls=False`, `confounder_count>=1` → ceiling WEAK.
  Confounders: 促销节奏, 季节性, 流量结构变化.
- Output table `business_snapshot` (single aggregate row) + `business_trend`
  (one row per date).

### Finding 2 — 载体 + 渠道结构拆解 (degrade-gated)

- **Carrier (note vs card):** only when both `note_gmv` and `card_gmv` present.
  Compute GMV share and (when `note_paid_orders`/`card_paid_orders` present)
  order share. No significance test — it is a share decomposition, not a rate
  comparison. Caveat that shares are aggregate snapshots.
- **Channel:** only when `traffic_source` present with `channel` +
  `product_click_users`. Aggregate per channel: click share =
  `product_click_users / Σ product_click_users`. When `paid_buyers` present,
  run `two_proportion(k=paid_buyers, n=product_click_users)` on the **top-2
  channels by click_users** (real counts — no reverse derivation). Require
  `>= 2` distinct channels with `n > 0`; otherwise skip with a limitation.
  Gate the significance verdict on a non-trivial effect size (report `diff`).
- Emit whichever sub-analysis is available; if neither, skip Finding 2 entirely
  and record a limitation. Output `carrier_structure` and/or
  `traffic_channel_structure`.
- Confounders: 渠道流量结构, 客群差异, 投放节奏.

### Finding 3 — 店铺页转化漏斗诊断 (degrade-gated)

- Only when `shop_page_funnel` present. Aggregate across rows:
  `V = Σ shop_visitors`, `C = Σ product_click_users` (if present),
  `P = Σ shop_payers`.
- Stage conversions preferring real counts: `visit→click = C/V`,
  `click→pay = P/C`, `visit→pay = P/V`; when `product_click_users` absent,
  fall back to averaging `visit_click_rate`/`click_pay_rate`/`visit_pay_rate`
  (each `bounded_rate`-normalised) and note the fallback.
- Weakest stage = min stage conversion → drives `recommended_action` lever.
- Wilson interval on each stage rate (`min_n_guard` on the stage denominator).
- When `audience_type` present with `>= 2` groups each with `shop_visitors > 0`,
  run `two_proportion(k=shop_payers, n=shop_visitors)` on the top-2 audiences by
  visitors → `audience_conversion` table.
- Confounders: 客群构成, 流量质量, 详情页与价格.

## Output tables

`business_snapshot`, `business_trend`, `carrier_structure`,
`traffic_channel_structure`, `shop_funnel_stages`, `audience_conversion`.
Emit only the tables whose inputs exist; absent ones are simply omitted.

## Levers (recommended_action)

- `visit_click` weakest → 优化店铺页首屏与商品卡点击诱因（主图、卖点、价格锚点）。
- `click_pay` weakest → 优化商详转化（尺寸/规格说明、评价、优惠与信任状）。
- `visit_pay` overall low → 全链路诊断，先补最弱阶段再看承接。
- Carrier skew → 检视 note vs card 的投入产出，向高转化载体倾斜内容与预算。

## Degradation matrix

| Missing | Behaviour |
|---|---|
| `business_overview_daily` | NOT_JUDGABLE `_missing_result` (only degraded case that yields no real findings). |
| `gmv`/`paid_buyers` columns | snapshot uses whatever present; `aov` column fallback; limitation logged. |
| `< 2` dated rows | snapshot still emitted; trend skipped with limitation. |
| `note_gmv`/`card_gmv` | carrier sub-analysis skipped, limitation logged. |
| `traffic_source` | channel sub-analysis skipped, limitation logged. |
| `paid_buyers` in traffic_source | channel share only, no `two_proportion`. |
| `shop_page_funnel` | Finding 3 skipped, limitation logged. |
| `product_click_users` | funnel uses rate columns fallback, note logged. |
| `audience_type` | audience `two_proportion` skipped, funnel still emitted. |

Finding 1 is **always** emitted whenever the Required table exists, so `run()`
never returns an empty findings list.

## Corrections baked in (from design critique)

1. Never reference a column in SQL without a `_table_columns` guard —
   build.py can omit even "Required" columns.
2. Normalise every rate column through `bounded_rate` before arithmetic.
3. Prefer real count columns (`paid_buyers`, `shop_payers`,
   `product_click_users`) over reverse-derived denominators.
4. `two_proportion` only with `>= 2` groups each `n > 0`; gate the "显著"
   verdict on a reported effect size, not just `|z| >= 1.96`.
5. Every `Finding` fills `confounders` and carries an observational caveat.
6. Guard every denominator (`/0` → `None`, never raise).

## Non-goals

- No causal attribution; no new mart table; no ad/paid-traffic overlap
  (that is `paid_traffic_efficiency`); no note-content analysis (that is the
  content modules); refund columns are out of scope (that is §7).

## Cross-links

Skeleton: `refund_structure_diagnosis`. Sibling modules this batch:
`search_efficiency_diagnosis` (§5), `audience_structure_diagnosis` (§6).
