# refund_structure_diagnosis

**Slug**: `refund_structure_diagnosis`  |  **Module**: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`  |  **Registry**: registry.py

## Purpose

诊断退款结构并定位杆杆：把总退款拆为发货前/发货后/退货三层，比较载体（笔记/商卡）退款率，报告退款率时间趋势，并两方面下钻——哪些笔记、哪些产品退款高及其共有特征。全程内部相对基准，观察性、非因果。

## Required tables & fields

- `refund_overview` (required) — `refund_amount_pay`, `pre_ship_refund_amount`, `post_ship_refund_amount`, `return_refund_amount`, `refund_orders_pay`, `refund_rate_pay`, `carrier`
- `business_overview_daily` (optional) — `date`, `refund_rate_pay`（趋势）
- `notes` (optional) — `note_refund_rate_pay`, `note_paid_orders`, `title`（笔记反思）
- `content_features` (optional) — `composition_type`, `scene_hint`, `copy_angle`（笔记特征）
- `sku_performance` (optional) — `product_id`, `gmv`, `net_gmv_pay`, `refund_rate_pay`, `refund_orders_pay`（产品反思）
- `products` (optional) — `vessel_type`, `series`, `category`, `price_band`（产品特征）

## Method

1. 无 `refund_overview` → NOT_JUDGABLE。
2. Finding 1 层级拆解：三层金额份额 + 整体退款率 Wilson CI（n 由 refund_orders/refund_rate 反推）+ 陶瓷杆杆。
3. Finding 2 载体对比：两载体退款率 `two_proportion` 检验（<2 载体则跳过）。
4. Finding 3 时间趋势：`business_overview_daily` 逐期退款率方向（<2 期或缺表则跳过）。
5. Finding 4 笔记反思：Wilson 下界 > 加权基线判高退款笔记；有 content_features 则报过度代表特征。
6. Finding 5 产品反思：sku_performance 聚合到 product_id，退款金额 Pareto + 高退款标记（有订单量则 Wilson 守卫）；有 products 则报过度代表特征。

## Thresholds & evidence

- 所有 finding `has_controls=False` → 证据强度上限 WEAK。
- `min_n_guard` = 30 退款订单（`MIN_ORDERS_FOR_RATE`）。
- 显著性：两样本比例 z 检验 |z|>=1.96，辅以 Wilson 区间重叠。

## Output

- Tables: `refund_layer_breakdown`, `carrier_refund_comparison`, `refund_trend`, `high_refund_notes`, `product_refund_concentration`（缺源则不建对应表）。
- Findings: 退款主漏点层级 / 载体退款率对比 / 退款率时间趋势 / 笔记退款反思 / 产品退款反思。

## Common failure modes

- 无 refund_overview → NOT_JUDGABLE，limitations 记原因。
- 单一载体 / 无 business_overview_daily / 无 notes / 无 content_features / 无 sku_performance / 无 products → 对应 finding 跳过或降级，其余照常。

## Cross-links

- Reference: [../references/data_contract.md](../references/data_contract.md)
- Skeleton for: §2 核心经营 / §5 搜索 / §6 人群 报告模块。
