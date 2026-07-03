# search_efficiency_diagnosis

**Slug**: `search_efficiency_diagnosis`  |  **Module**: `xhs_ceramics_analytics/analysis/search_efficiency.py`  |  **Registry**: registry.py

## Purpose

诊断搜索这条路的成交效率：哪个载体（笔记/商卡）更能承接搜索流量、搜索成交转化的时间走势、哪些搜索词是高机会或高流失。把搜索概览与分词聚合转成可执行的载体对比 + 转化趋势 + 搜索词机会/流失清单。全程内部相对基准，观察性、非因果。

## Required tables & fields

- `search_overview` (required) — `date`, `carrier`, `card_impression_users`（卡片曝光人数，漏斗基数）, `product_click_rate`, `pay_conversion`；可选 `gmv`, `paid_orders`, `paid_buyers`, `product_click_users`。缺失整表 → NOT_JUDGABLE。粒度：一行/（date × carrier）。
- `search_terms` (optional) — `search_term`, `card_impression_users`, `product_click_rate`, `pay_conversion`；可选 `gmv`, `paid_buyers`, `product_click_users`。粒度：一行/`search_term`（全周期，无 date 列）。

**口径**：`card_impression_users` 为漏斗基数；`product_click_rate` / `pay_conversion` 是率列，运算前一律经 `bounded_rate` 归一到 [0,1]。

## Method

1. 无 `search_overview` → 返回单个 NOT_JUDGABLE `_missing_result`（唯一无实质 finding 的情形）。
2. **Finding 1 载体搜索效率对比（始终产出）**：按 `carrier` 聚合 `impressions = Σ card_impression_users`。成交人数**优先取真实值**——有 `paid_buyers` 时 `k = Σ paid_buyers`；否则**正推**（非反推）`k = round(Σ 曝光 × bounded_rate(点击率) × bounded_rate(成交转化率))`，绝不 `n = k / rate`。效率 = `k / impressions`。`>= 2` 个 `impressions > 0` 的载体时，对曝光前二载体跑 `two_proportion`，"显著"需同时满足 z 检验显著且效应量 `|diff| >= 0.005`。`< 2` 载体则输出单载体效率并记 limitation（仍是真实 finding）。
3. **Finding 2 搜索转化时间趋势（降级门控）**：有 `date` 且 `>= 2` 个不同日期时，序列 = `[(date, AVG(bounded_rate(pay_conversion)))]` 按日期排序。`mom_change` + 整体 `direction_label`；逐期 delta 入 `appendix`。仅报方向与幅度，不做显著性检验。`< 2` 期则跳过并记 limitation。
4. **Finding 3 高机会/高流失搜索词（降级门控）**：有 `search_terms` 时，每词 `n = card_impression_users`，`k = paid_buyers`（有则用）否则正推。基线 = 曝光加权均值 `Σk / Σn`。Wilson 区间分类（`min_n_guard(n)` 守卫）：下界 `> baseline` → **高机会**；上界 `< baseline` → **高流失**；`n < MIN_ORDERS_FOR_RATE` 列出但标 `small_sample` 不分类。Pareto 按 `gmv`（有则用）否则 `card_impression_users` 排序，小样本排末尾。

## Thresholds & evidence

- 所有 finding `has_controls=False` → 证据强度上限 WEAK；每个 finding 均填 `confounders` 与观察性 caveat，所有分母守卫除零。
- `min_n_guard` = 30 曝光（`MIN_ORDERS_FOR_RATE`）。
- 显著性：两样本比例 z 检验 `|z| >= 1.96`，并要求非平凡效应量 `|diff| >= 0.005`，辅以 Wilson 区间重叠。

## Output tables

- `carrier_search_efficiency`（一行/载体：carrier, impressions, payers, effectiveness）。
- `search_conversion_trend`（一行/期：period, avg_pay_conversion）。
- `search_term_opportunities`（一行/词：search_term, n, k, rate, wilson_low, wilson_high, gmv, term_class）。
- 仅在输入存在时建对应表。

## Levers (recommended_action)

- `carrier_gap` → 向高转化载体倾斜搜索承接内容与预算。
- `conversion_trend_decline` → 排查搜索承接页与词-货匹配，止跌优先。
- `opportunity_terms` → 高机会词加投 / 做定向笔记与商详承接。
- `leak_terms` → 高流失词降权 / 修词-货匹配 / 修承接页相关性。

## Failure modes（降级矩阵）

| Missing | Behaviour |
|---|---|
| `search_overview` | NOT_JUDGABLE `_missing_result`（唯一无实质 finding）。 |
| `search_overview.paid_buyers` | 由率正推成交人数（caveat 说明）。 |
| `carrier` 列缺失 | 按单一载体聚合，记 limitation。 |
| `< 2` 载体 | 输出单载体效率，跳过对比。 |
| `date` / `< 2` 期 / 无 `pay_conversion` | Finding 2 跳过，记 limitation。 |
| `search_terms` 缺失 | Finding 3 跳过，记 limitation。 |
| 词 `n < MIN_ORDERS_FOR_RATE` | 列出但标 `small_sample` 不分类。 |
| 空数据行 | 不 raise；Finding 1 仍产出（效率 None + limitation）。 |

Finding 1 在 Required 表存在时**始终**产出 → `run()` 的 findings 列表永不为空。

## Non-goals

- 无因果归因；不建新 mart；不覆盖付费搜索/广告重叠（属 `paid_traffic_efficiency`）；无关键词 NLP/聚类——分类纯统计（Wilson vs 基线）。

## Cross-links

- Reference: [../references/data_contract.md](../references/data_contract.md)
- Skeleton: `refund_structure_diagnosis`；同批 sibling：`core_business_diagnosis` (§2)、`audience_structure_diagnosis` (§6)。
