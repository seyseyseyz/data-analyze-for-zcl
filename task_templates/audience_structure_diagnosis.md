# 人群结构诊断 (audience_structure_diagnosis)

> Sibling of `refund_structure_diagnosis` (the skeleton). Same module contract,
> shared stat helpers (`confidence.py` / `trends.py`), and never-raise degradation
> discipline. Design:
> `docs/superpowers/specs/2026-07-03-audience-structure-diagnosis-design.md`.

- `TASK_ID = "audience_structure_diagnosis"`，`TITLE = "人群结构诊断"`
- Module: `xhs_ceramics_analytics/analysis/audience_structure.py`
- Test: `tests/test_audience_structure.py`

## Purpose

回答「不同人群/首购周期的转化差多少、从哪些来源进店、人群构成如何」。把店铺页人群漏斗
（人群 × 首购周期）、进店来源、以及手工录入的人群画像，转化为可执行的人群转化对比。
仅做观察性描述，不做因果归因。

## Required tables

- `shop_page_funnel`（**必需**；缺失则返回单个 `NOT_JUDGABLE` 的 `_missing_result`）。
  颗粒度：date × audience_type × first_purchase_cycle。
  - 必需列：`shop_visitors`、`shop_payers`、`first_purchase_cycle`。
  - 选用列：`date`、`audience_type`、`product_click_users`、`visit_click_rate`、
    `click_pay_rate`、`visit_pay_rate`。

**关键：真实计数可用。** `shop_page_funnel` 自带真实 `shop_visitors` 与 `shop_payers`，
所以人群/周期转化直接用 `k = Σ shop_payers`、`n = Σ shop_visitors`，**不反推**。

## Optional tables

- `shop_page_source`（date × audience_type × first_purchase_cycle × source_page）。
  - 必需列：`source_page`、`shop_visitors`、`enter_pay_rate`；选用：`audience_type`、
    `first_purchase_cycle`、`shop_gmv`。
- `audience_profile`（**手工录入 CSV**；9.人群分析为图片，**无导入器**，生产中默认缺失）。
  - 列：`audience_segment`、`share`、`gmv`。

## Method — 各 Finding

### Finding 1 — 人群转化对比（始终产出）

- 按 `audience_type` 聚合 `shop_page_funnel`：`n = Σ shop_visitors`、`k = Σ shop_payers`、
  转化 `= k/n`。
- 当 `>= 2` 个人群组且每组 `n > 0` 时，对访客前二做
  `two_proportion(k_a, n_a, k_b, n_b)`；「显著」需同时满足 z 检验显著 **且** 效应量
  `|diff| >= 0.02`（非平凡差异门槛），并始终报告 `diff`。
- 当 `audience_type` 缺失或有效组 `< 2` 时，回退到整体转化
  （`Σshop_payers / Σshop_visitors` + Wilson），记 limitation——仍是一条真实 Finding。
- 缺 `shop_visitors`/`shop_payers` 列时，产出 `NOT_JUDGABLE` 的缺列告知 Finding（仍不为空）。
- Evidence `has_controls=False` → 上限 WEAK。Confounders：人群定义口径、流量来源差异、客单与品类。
- 输出表 `audience_conversion_comparison`（每人群一行；回退时单行整体）。

### Finding 2 — 首购周期漏斗（降级门控）

- 按 `first_purchase_cycle`（必需列）聚合：`n = Σ shop_visitors`、`k = Σ shop_payers`、
  转化 + Wilson（`min_n_guard(n)`，n≥30 才给区间）。
- 取「有足够样本且 Wilson 下界最低」的周期为最弱周期 → 对应 lever；周期区分新老客时报告转化差。
- Confounders：券与活动节奏、复购提醒机制、客群成熟度。输出表 `first_purchase_cycle_funnel`。

### Finding 3 — 进店来源结构（降级门控）

- 仅当 `shop_page_source` 存在。按 `source_page`：`n = Σ shop_visitors`，
  `k = Σ round(shop_visitors × bounded_rate(enter_pay_rate))`（率×基数→计数）。
  访客占比 `= n / Σn`；有 `shop_gmv` 时另算 GMV 占比。
- 按访客占比排序（帕累托）；对每来源支付率做 Wilson 守卫（`min_n_guard(n)`）；
  标记「高流量但转化低于整体」的来源为承接优化点。
- Confounders：来源意图差异、承接页匹配、活动引流结构。输出表 `shop_source_structure`。

### Finding 4 — 人群构成（生产环境永久降级，绝不静默丢弃）

- 仅当 `audience_profile` 存在且含 `share` + `gmv` 时计算 share × gmv 集中度（谁贡献 GMV）。
- **因 `audience_profile` 无导入器（PNG 来源），真实运行时预期缺失。** 缺失时产出
  `NOT_JUDGABLE`/WEAK 的「数据缺口告知」Finding，结论明确写「人群构成需手工录入
  audience_profile（9.人群分析 为图片，无法自动导入）」并给补数指引——**不静默丢弃**，
  使报告永远记录该缺口。
- Confounders：n/a（构成快照）。输出表 `audience_composition`。

## Thresholds

- `MIN_ORDERS_FOR_RATE = 30`（`min_n_guard`）：低于此不给 Wilson 区间。
- `_MIN_MEANINGFUL_DIFF = 0.02`：人群对比「显著」的最小效应量门槛。
- `bounded_rate`：率归一到 [0,1]，(1,100] 视为百分数除 100，脏值返回 None。

## Output tables

`audience_conversion_comparison`、`first_purchase_cycle_funnel`、
`shop_source_structure`、`audience_composition`。仅在输入存在时产出对应表。

## Failure modes（降级矩阵）

| 缺失 | 行为 |
|---|---|
| `shop_page_funnel` | `NOT_JUDGABLE` `_missing_result`（唯一无真实 Finding 的情形）。 |
| `shop_visitors`/`shop_payers` 列 | Finding 1 产出缺列告知（NOT_JUDGABLE），仍不为空。 |
| `audience_type` | Finding 1 回退整体转化。 |
| 人群组 `< 2` | Finding 1 产出整体转化，跳过对比。 |
| `first_purchase_cycle` 单值 | Finding 2 产出单周期，无转化差。 |
| `shop_page_source` | Finding 3 跳过，记 limitation。 |
| `audience_profile`（典型） | Finding 4 产出降级缺口告知 Finding（不丢弃）。 |

Finding 1 与 Finding 4 **始终**产出（Required 表存在时）→ `run()` 的 findings 永不为空。

## Levers（recommended_action）

- 低转化人群 → 针对该人群做承接内容与利益点定制（人群包 + 定向笔记）。
- 薄弱首购周期 → 首购人群补券/信任状；复购人群做召回与复购提醒。
- 高流量低转化来源 → 优化该来源承接页的相关性与首屏转化。
- 构成倾斜 → 向高 GMV 贡献人群加投，低效人群缩量或换承接。

## Caveats baked in

1. 用 `_table_columns` 守卫每一列后再引用（CREATE TABLE AS SELECT read_csv_auto 可能缺列）。
2. 优先真实 `shop_payers`/`shop_visitors` 计数，不反推。
3. `bounded_rate(enter_pay_rate)` 后再 `k = round(rate × base)`。
4. `two_proportion` 仅 `>= 2` 组且每组 `n > 0`；「显著」配合效应量；否则回退整体转化。
5. `audience_profile` 缺失是被记录的数据缺口，非跳过。
6. 每个 Finding 填 confounders + 观察性 caveat；守卫所有 `/0`。
7. 漏斗按天记录，跨天汇总可能重复计入回访用户——在 caveats 标注。

## Cross-links

- 骨架：`refund_structure_diagnosis`。
- 同批模块：`core_business_diagnosis`（§2）、`search_efficiency_diagnosis`（§5）。
