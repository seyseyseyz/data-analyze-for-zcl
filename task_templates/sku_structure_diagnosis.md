# SKU 结构与退款诊断 (sku_structure_diagnosis)

> Sibling of `refund_structure_diagnosis` / `audience_structure_diagnosis` (same
> skeleton). Same module contract, shared stat helpers (`confidence.py` /
> `evidence.py`), and never-raise degradation discipline.

- `TASK_ID = "sku_structure_diagnosis"`，`TITLE = "SKU 结构与退款诊断"`
- Module: `xhs_ceramics_analytics/analysis/sku_structure.py`
- Test: `tests/test_sku_structure.py`

## Purpose

回答「GMV 集中在哪些 SKU/类目、哪些 SKU 退款异常偏高、加购转化与客单价结构如何」。
把 SKU 销售明细（`sku_performance`）转化为可执行的结构诊断：帕累托集中度、高退款
SKU 清单、加购转化与客单价分层。仅做观察性描述，不做因果归因。

## Required tables

- `sku_performance`（**必需**；缺失则返回单个 `NOT_JUDGABLE` 的 `_missing_result`）。
  颗粒度：sku_id（按 SKU 汇总的销售/退款/转化指标）。
  - 必需列（Finding 1 生效需要）：`gmv`。
  - 选用列：`sku_id`、`sku_name`、`product_id`、`product_name`、
    `is_channel_product`、`category_l1`、`category_l2`、`brand`、
    `add_to_cart_users`、`paid_buyers`、`paid_orders`、`paid_units`、`aov`、
    `refund_rate_pay`、`refund_orders_pay`、`pre_ship_refund_rate_pay`、
    `post_ship_refund_rate_pay`、`net_gmv_pay`。

**关键：每列都需先经 `_table_columns` 守卫再引用**——导出口径不稳定，缺列不应导致
异常，而应触发对应 Finding 的降级或跳过。

## Optional tables

无（本模块仅依赖单表 `sku_performance`；`category_l1` 等列本身是可选列，缺失时对应
子输出降级，不影响其余 Finding）。

## Method — 各 Finding

### Finding 1 — GMV 集中度与类目结构（帕累托）（始终产出）

- 需要 `gmv` 列；缺失时产出 `NOT_JUDGABLE` 的缺列告知 Finding（仍不为空）。
- 取 `gmv > 0` 的 SKU，按 `gmv` 降序排序；`total_gmv = Σgmv`（仅含 gmv>0 的行）。
- 头部 10%（`ceil(sku_count * 0.1)`，至少 1 个）SKU 的 GMV 占比
  `= top_decile_gmv / total_gmv`。
- 按累计 GMV 占比找到达到 80% 所需的 SKU 数 `skus_for_80pct`（全部达不到 80% 时取
  全部 SKU 数）。
- 若 `category_l1` 列存在，另按类目聚合 GMV 与份额，取份额最高的类目为
  `top_category`。
- Evidence `has_controls=False` → 上限 WEAK。Confounders：品类与价格带混合、流量
  分配差异、活动与折扣节奏。
- 输出表 `sku_gmv_pareto`（GMV 前 ~20 的 SKU：`sku_name, gmv, gmv_share,
  cum_share`）；`category_l1` 存在时另输出 `sku_category_mix`
  （`category_l1, gmv, gmv_share`）。

### Finding 2 — 高退款 SKU 识别（降级门控）

- 需要 `refund_rate_pay` **且** `paid_orders` 列；任一缺失则跳过（记 limitation）。
- 基线退款率：若有 `refund_orders_pay` 列，`baseline = Σrefund_orders_pay /
  Σpaid_orders`；否则用 `Σ(bounded_rate(refund_rate_pay) × paid_orders) /
  Σpaid_orders` 加权平均近似。
- 标记 `bounded_rate(refund_rate_pay) > baseline` 且 `paid_orders >= 10`
  （`min_orders guard`）的 SKU 为高退款异常；若存在
  `pre_ship_refund_rate_pay`/`post_ship_refund_rate_pay`，一并带出以提示
  发货前/后驱动因素。
- Confounders：品类与价格带混合、流量分配差异、活动与折扣节奏。
- 输出表 `sku_refund_outliers`（按退款率降序）。

### Finding 3 — 加购转化与客单价结构（降级门控）

- 需要 `add_to_cart_users` **且** `paid_buyers` 列；任一缺失则跳过（记
  limitation）。
- 整体加购转化 `= bounded_rate(Σpaid_buyers / Σadd_to_cart_users)`；逐 SKU 同法
  计算 `cart_to_pay`。
- 若 `aov` 列存在，计算客单价中位数；单 SKU `aov >= median × 1.5` 标记「高客单」，
  `<= median × 0.5` 标记「低客单」，其余「中位」。
- Confounders：品类与价格带混合、流量分配差异、活动与折扣节奏。
- 输出表 `sku_conversion_and_aov`（按加购人数降序）。

## Thresholds

- `min_orders guard = 10`：高退款 SKU 标记所需的最低支付订单数。
- `80% pareto`：GMV 帕累托集中度的累计份额阈值，用于计算 `skus_for_80pct`。
- `bounded_rate`：率归一到 [0,1]，(1,100] 视为百分数除 100，脏值返回 None。
- AOV 分层：`>= median × 1.5` 高客单，`<= median × 0.5` 低客单。

## Output tables

`sku_gmv_pareto`、`sku_category_mix`（`category_l1` 存在时）、
`sku_refund_outliers`、`sku_conversion_and_aov`。仅在输入存在时产出对应表。

## Failure modes（降级矩阵）

| 缺失 | 行为 |
|---|---|
| `sku_performance` | `NOT_JUDGABLE` `_missing_result`（唯一无真实 Finding 的情形）。 |
| `gmv` 列 | Finding 1 产出缺列告知（NOT_JUDGABLE），仍不为空。 |
| `category_l1` | Finding 1 仍产出，跳过 `sku_category_mix` 与 `top_category`。 |
| `refund_rate_pay`/`paid_orders` | Finding 2 跳过，记 limitation。 |
| `refund_orders_pay` | Finding 2 基线退款率改用加权平均近似。 |
| `add_to_cart_users`/`paid_buyers` | Finding 3 跳过，记 limitation。 |
| `aov` | Finding 3 仍产出，跳过客单价中位数与分层标记。 |

Finding 1 **始终**产出（`sku_performance` 存在时）→ `run()` 的 findings 永不为空。

## Levers（recommended_action）

- GMV 高度集中 → 头部 SKU 保供与加投，腰部测新。
- 高退款 SKU → 复核详情页/尺寸描述与发货时效，针对性优化退货流程。
- 加购转化偏低或客单价失衡 → 优化详情页转化钩子，高客单 SKU 强化权益，低客单
  SKU 测试搭配销售。

## Caveats baked in

1. 用 `_table_columns` 守卫每一列后再引用（导出口径不稳定，缺列不报错，只降级）。
2. 所有率列先经 `bounded_rate` 归一（值可能是 0-1 的小数，也可能是 0-100 的百分数）。
3. 高退款判定同时要求「退款率高于基线」与「支付订单数 ≥10」，避免小样本噪声。
4. 每个 Finding 填 confounders + 观察性 caveat；守卫所有 `/0`。
5. 观察性诊断，非因果——GMV/退款/转化差异可能由品类结构、价格带、流量分配与活动
   节奏共同驱动。

## Cross-links

- 骨架：`refund_structure_diagnosis`。
- 姊妹模块：`note_commercial_diagnosis`（笔记侧商业化诊断）。
- 同批模块：`core_business_diagnosis`（§2）、`search_efficiency_diagnosis`
  （§5）、`audience_structure_diagnosis`（§6）。
