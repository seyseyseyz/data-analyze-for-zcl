# 核心经营结构诊断 (core_business_diagnosis)

> 姊妹模块：`refund_structure_diagnosis`（骨架范例）。同一模块契约、共享统计助手、
> 绝不 raise 的降级纪律。设计：
> docs/superpowers/specs/2026-07-03-core-business-diagnosis-design.md

## Purpose

回答「生意的整体盘子有多大、靠什么载体/渠道成交、店铺页在哪一步漏人」。把每日经营概览
转化为规范化的快照 + 时间趋势 + 载体/渠道结构拆解 + 店铺页漏斗诊断。纯观察性——只报告
方向与效应量，绝不做因果归因。

## Tables

### Required

- `business_overview_daily`（粒度：一行一 `date`，YYYYMMDD 整数）。缺失即返回单个
  `NOT_JUDGABLE` 的 `_missing_result`，这是唯一不产出真实 Finding 的降级分支。
  - Required 列：`date, gmv, paid_orders, paid_buyers, aov`
  - 本模块可选用列：`note_gmv, card_gmv, note_paid_orders, card_paid_orders,
    product_visitors, paid_units, pay_conversion_pv, pay_conversion_uv, total_visitors`

### Optional

- `traffic_source`（粒度：xhs_id × channel × note_type）
  - Required 列：`xhs_id, channel, product_clicks, product_click_users`
  - 可选用列：`paid_buyers, pay_conversion_uv, gmv`
- `shop_page_funnel`（粒度：date × audience_type × first_purchase_cycle）
  - Required 列：`shop_visitors, shop_payers, first_purchase_cycle`
  - 可选用列：`product_click_users, visit_click_rate, click_pay_rate,
    visit_pay_rate, audience_type`

**关键——note/card 是列拆分而非行维度。** 载体结构来自每日行上的
`note_gmv`/`card_gmv`（及 `note_paid_orders`/`card_paid_orders`）列，不存在 `carrier` 列。

## Method（各 Finding）

### Finding 1 — 整体经营快照与趋势（始终产出）

- `SUM(gmv/paid_orders/paid_buyers/paid_units)`，逐列用 `_table_columns` 守卫后再取。
- 客单价：`paid_buyers > 0` 时 `aov = gmv / paid_buyers`（derived）；否则回退 `aov` 列均值
  （column），并在 key_numbers/caveat 中标明来源。
- 支付转化率：优先真实计数 `paid_buyers / SUM(product_visitors)`（`product_visitors`
  存在且 > 0）；否则对 `pay_conversion_uv` 逐值 `bounded_rate` 归一后取均值。
- 趋势：对按日期排序的 `[(date_str, gmv), ...]` 跑 `mom_change`，用首→末 `direction_label`
  给出整体方向，逐期 delta 存入 `appendix`。
- 证据：`has_controls=False, confounder_count>=1` → 天花板 WEAK。
- 输出 `business_snapshot`（单聚合行）+ `business_trend`（一日一行）。

### Finding 2 — 载体 + 渠道结构拆解（降级门控）

- **载体（note vs card）**：仅当 `note_gmv` 与 `card_gmv` 同时存在。计算 GMV 份额，
  （当 `note_paid_orders`/`card_paid_orders` 存在时）计算订单份额。不做显著性检验——这是
  份额分解而非比率对比。caveat 标明份额为聚合快照。
- **渠道**：仅当 `traffic_source` 存在且含 `channel` + `product_click_users`。按渠道聚合
  点击客数，`click_share = product_click_users / Σ product_click_users`。当 `paid_buyers`
  存在时，对**按点击客数排序的 Top-2 渠道**跑
  `two_proportion(k=paid_buyers, n=product_click_users)`（真实计数，不反推）。要求 ≥2 个
  `n > 0` 的渠道，否则跳过并记 limitation。「显著」结论须配合非平凡效应量（`diff`）。
- 任一子分析可用即产出 Finding；两者皆无则整段跳过并记 limitation。
- 输出 `carrier_structure` 和/或 `traffic_channel_structure`。

### Finding 3 — 店铺页转化漏斗诊断（降级门控）

- 仅当 `shop_page_funnel` 存在。跨行聚合 `V=Σ shop_visitors`、
  `C=Σ product_click_users`（存在时）、`P=Σ shop_payers`。
- 阶段转化优先真实计数：`visit→click=C/V`、`click→pay=P/C`、`visit→pay=P/V`；缺
  `product_click_users` 时回退对 `visit_click_rate`/`click_pay_rate`/`visit_pay_rate`
  逐值 `bounded_rate` 归一后取均值，并记 fallback。
- 最弱阶段 = 最小阶段转化 → 驱动 `recommended_action` 杠杆。
- 对每个阶段率跑 Wilson 区间（分母过 `min_n_guard`）。
- 当 `audience_type` 存在且 ≥2 组各 `shop_visitors > 0`，对按访客数排序的 Top-2 客群跑
  `two_proportion(k=shop_payers, n=shop_visitors)` → `audience_conversion` 表。

## Thresholds

- `min_n_guard`：n ≥ 30 才给 Wilson 区间 / 显著性可信。
- 显著判定：`|z| >= 1.96` 且 `|diff| >= 0.01`（1pct）方标「显著」。
- 趋势方向：`|delta| < 1e-9` 视为「持平」。

## Output tables

`business_snapshot`、`business_trend`、`carrier_structure`、
`traffic_channel_structure`、`shop_funnel_stages`、`audience_conversion`。
仅产出输入存在的表；缺失表直接省略。

## Failure modes / 降级矩阵

| 缺失 | 行为 |
|---|---|
| `business_overview_daily` | NOT_JUDGABLE `_missing_result`（唯一无真实 Finding 的分支）。 |
| `gmv`/`paid_buyers` 列 | 快照用现有列；`aov` 列回退；记 limitation。 |
| `< 2` 日期行 | 快照照常产出；趋势跳过并记 limitation。 |
| `note_gmv`/`card_gmv` | 载体子分析跳过并记 limitation。 |
| `traffic_source` | 渠道子分析跳过并记 limitation。 |
| `traffic_source.paid_buyers` | 仅渠道份额，无 `two_proportion`。 |
| `shop_page_funnel` | Finding 3 跳过并记 limitation。 |
| `product_click_users` | 漏斗回退比率列均值并记 note。 |
| `audience_type` | 客群 `two_proportion` 跳过，漏斗照常产出。 |

Required 表存在时 Finding 1 **始终**产出，`run()` 的 findings 列表永不为空。

## Levers（recommended_action）

- `visit_click` 最弱 → 优化店铺页首屏与商品卡点击诱因（主图、卖点、价格锚点）。
- `click_pay` 最弱 → 优化商详转化（尺寸/规格说明、评价、优惠与信任状）。
- `visit_pay` 整体偏低 → 全链路诊断，先补最弱阶段再看承接。
- 载体倾斜 → 检视 note vs card 的投入产出，向高转化载体倾斜内容与预算。

## Corrections baked in

1. SQL 引用任何列前必先 `_table_columns` 守卫——build.py 可能省略「Required」列。
2. 每个率列先 `bounded_rate` 归一再运算。
3. 优先真实计数列（`paid_buyers`、`shop_payers`、`product_click_users`），有真实计数
   时不反推分母。
4. `two_proportion` 仅在 ≥2 组各 `n > 0` 时运行；「显著」须配合报告效应量（`diff`）。
5. 每个 Finding 都填 `confounders` 且带观察性 caveat。
6. 守卫所有分母（`/0` → `None`，绝不 raise）。

## Non-goals

无因果归因；不建新 mart 表；不涉及广告/付费流量重叠（那是 `paid_traffic_efficiency`）；
不做笔记内容分析（内容模块负责）；退款列超出范围（§7 负责）。

## Cross-links

骨架：`refund_structure_diagnosis`。本批姊妹模块：`search_efficiency_diagnosis`（§5）、
`audience_structure_diagnosis`（§6）。
