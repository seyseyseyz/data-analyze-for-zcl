# 退款根因诊断 (refund_root_cause_diagnosis)

> Sibling of `refund_structure_diagnosis` / `sku_structure_diagnosis` (skeleton
> module contract). Same helpers (`confidence.py`), plus `multiplicity.py`
> (Benjamini-Hochberg FDR control) for the many-category outlier scan. Design:
> `docs/superpowers/specs/2026-07-03-refund-root-cause-diagnosis-design.md`.

- `TASK_ID = "refund_root_cause_diagnosis"`，`TITLE = "退款根因诊断"`
- Module: `xhs_ceramics_analytics/analysis/refund_root_cause_diagnosis.py`
- Test: `tests/test_refund_root_cause.py`

## Purpose

回答「退款主要发生在发货前还是发货后、哪些品类退款显著偏高、哪个价位带退款率最高」，
把 `sku_performance` 的退款相关列分解为三条互补视角，供物流/质检/详情页/定价团队分头
排查。仅做观察性分解，不做因果归因。

## Required tables

- `sku_performance`（**必需**；缺失则返回单个 `NOT_JUDGABLE` 的 `_missing_result`）。
  颗粒度：SKU 级。用到的列（任一可能在降级导出中缺失，逐列 `_table_columns` 守卫）：
  `category_l1`、`category_l2`、`aov`、`gmv`、`paid_orders`、`refund_rate_pay`、
  `refund_orders_pay`、`pre_ship_refund_rate_pay`、`post_ship_refund_rate_pay`。

## Optional tables

- `business_overview_daily`（按天的市场级发货前/发货后退款率 + `paid_orders`）。
  存在且列齐全时，Finding 1 优先用它计算市场级发货前后退款占比（比 SKU 汇总更贴近
  大盘口径）；否则退回 `sku_performance` 按 `paid_orders` 加权聚合。

## Method — 各 Finding

### Finding 1 — 发货前 vs 发货后分解（始终产出）

- 优先取 `business_overview_daily`（若含 `pre_ship_refund_rate_pay` /
  `post_ship_refund_rate_pay` / `paid_orders`）：`pre_rate = Σ(pre_ship_rate×paid_orders) / Σpaid_orders`，
  `post_rate` 同理；`source = "business_overview"`。
- 否则退回 `sku_performance` 同样加权聚合，`source = "sku_performance"`。
- 二者列均缺失时产出 `NOT_JUDGABLE` 的缺列告知 Finding（仍不为空）。
- 判定 `dominant_stage`（`pre_ship`/`post_ship`，二者相等或任一为 `None` 时不判定），
  给出对应排查方向：发货前 → 物流时效/悔单/价保；发货后 → 质量/描述不符/尺寸。
- Evidence `has_controls=False` → 上限 WEAK。Confounders：品类与尺寸结构、物流与时效、
  描述一致性。输出表 `refund_by_ship_stage`（stage、stage_zh、rate）。

### Finding 2 — 品类退款分解（降级门控：`category_l1` + 退款/支付列）

- 按 `category_l1` 聚合真实计数：`k = Σ refund_orders_pay`、`n = Σ paid_orders`
  （`refund_orders_pay` 缺失时退回 `bounded_rate(refund_rate_pay) × paid_orders`）。
- 市场基线 `baseline = Σ全部refund_orders / Σ全部paid_orders`。
- 对 `min_n_guard(n)`（n≥30）通过的品类，用 `one_sided_binomial_p(k, n, baseline)`
  做单边二项检验（H1：品类退款率 > 大盘基线），再对所有守卫品类的 p 值做
  `benjamini_hochberg(alpha=0.05)` 控制多重比较下的假发现率，标记
  `fdr_significant`。用 `expected_false_positives` 报告"预计假阳性约 N 个"仅作
  提示，非决策依据。
- 结论点名退款率最高的品类与 FDR 显著品类数。
- Confounders：品类内价格带混合、尺寸与包装、季节与活动。输出表
  `refund_by_category`（category_l1、paid_orders、refund_orders、refund_rate、
  wilson_low、wilson_high、fdr_significant）。

### Finding 3 — 价格带退款分解（降级门控：`aov` + 退款/支付列）

- 用 `gmv>0` 的 SKU 的 `aov` 做四分位（`statistics.quantiles(n=4)`，从真实数据算
  25/50/75 分位，不写死阈值）切出 4 个价位带（低/中低/中高/高价位）；不足 4 个
  有效样本时跳过。
- 每个价位带：`k = Σ refund_orders`（同 Finding 2 的真实计数/回退口径）、
  `n = Σ paid_orders`，`refund_rate = k/n`；`gmv_share = 该带gmv / 全部gmv`；
  用 `min_n_guard(n)` 守卫哪些价位带可判定"最高退款价位带"。
- Confounders：价格与预期差、高价类目结构、赠品与活动。输出表
  `refund_by_price_band`（band、aov_low、aov_high、paid_orders、refund_rate、
  gmv_share）。

## Thresholds

- `MIN_ORDERS_FOR_RATE = 30`（`min_n_guard`）：低于此不给 Wilson 区间，也不参与
  "最高退款品类/价位带"的判定与 FDR 检验。
- BH-FDR `alpha = 0.05`：跨品类多重比较的假发现率上限。
- `bounded_rate`：率归一到 [0,1]，(1,100] 视为百分数除 100，脏值返回 None。
- 价位带阈值：`statistics.quantiles` 的 25/50/75 分位（来自 `gmv>0` SKU 的
  真实 `aov` 分布，非硬编码）。

## Output tables

`refund_by_ship_stage`、`refund_by_category`、`refund_by_price_band`。
仅在输入列齐全时产出对应表（Finding 1 始终产出，Finding 2/3 降级门控）。

## Failure modes（降级矩阵）

| 缺失 | 行为 |
|---|---|
| `sku_performance` | `NOT_JUDGABLE` `_missing_result`（唯一无真实 Finding 的情形）。 |
| 发货前后退款率列（两表均无） | Finding 1 产出缺列告知（NOT_JUDGABLE），仍不为空。 |
| `category_l1` | Finding 2 跳过，记 limitation。 |
| `paid_orders` / 退款列（品类） | Finding 2 跳过，记 limitation。 |
| `aov` | Finding 3 跳过，记 limitation。 |
| `paid_orders` / 退款列（价位带） | Finding 3 跳过，记 limitation。 |
| `gmv>0` 样本 < 4 | Finding 3 跳过（无法计算分位），记 limitation。 |

Finding 1 **始终**产出（`sku_performance` 存在时）→ `run()` 的 findings 永不为空。

## Levers（recommended_action）

- 发货前退款为主 → 排查物流时效承诺、悔单率与价保规则。
- 发货后退款为主 → 排查商品质量、描述一致性与尺寸/包装。
- 高退款品类 → 复核该品类详情页描述、尺寸表与质检标准，优先跟进 BH-FDR 显著品类。
- 高退款价位带 → 核对价格与预期落差，复核该价位带的赠品/活动政策。

## Caveats baked in

1. 用 `_table_columns` 守卫每一列后再引用（CREATE TABLE AS SELECT read_csv_auto
   可能缺列）。
2. 优先真实 `refund_orders_pay`/`paid_orders` 计数，`refund_rate_pay` 仅作回退。
3. BH-FDR 控制的是多重比较下的假发现率，不是逐品类因果证明；报告预计假阳性数仅供
   参考。
4. 价位带阈值来自当次数据的真实分位数，不同导出批次会漂移，不可跨批次直接比较。
5. 每个 Finding 填 confounders + 观察性 caveat；守卫所有 `/0`。

## Cross-links

- 骨架：`refund_structure_diagnosis`、`sku_structure_diagnosis`。
- 共享多重比较工具：`xhs_ceramics_analytics/analytics/multiplicity.py`。
- 同批模块：`audience_structure_diagnosis`（§6）、`core_business_diagnosis`（§2）、
  `search_efficiency_diagnosis`（§5）。
