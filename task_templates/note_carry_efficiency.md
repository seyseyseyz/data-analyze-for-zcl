# 笔记承接效率诊断 (note_carry_efficiency)

> Observational analysis of notes' off-site referral efficiency (shop home and livestream).
> Same module contract, shared stat helpers, and never-raise degradation discipline.
> **Scope boundary:** Measures *how many visitors* notes drive to shop homepage and livestream,
> not livestream overview, dwell time, or product-level funnel. Never attribute sales
> to livestream product mix—that belongs to separate livestream diagnostics.

- `TASK_ID = "note_carry_efficiency"`，`TITLE = "笔记承接效率（进店与直播）"`
- Module: `xhs_ceramics_analytics/analysis/note_carry.py`
- Test: `tests/test_note_carry.py`

## Purpose

回答「笔记通过进店与直播间的承接效率怎么样、有没有发挥效力、哪些笔记承接最好」。
把商品笔记明细（`notes`）中的进店/直播承接数据，转化为可执行的笔记承接效率诊断。
仅做观察性描述，不做因果归因。

## Required tables

- `notes`（**必需**；缺失则返回单个 `NOT_JUDGABLE` 的 `_missing_result`）。
  颗粒度：笔记级（每篇笔记一行）。

## Optional / gated columns

每一列使用前均用 `_table_columns` 守卫（`read_csv_auto` 构建的表可能缺列）：

- 承接字段（至少一组必需；四列全缺则 `NOT_JUDGABLE`）：
  - 进店：`to_shop_home_count`（次数）+ `to_shop_home_gmv`（支付金额）
  - 直播间：`to_live_count`（次数）+ `to_live_gmv`（支付金额）
- `reads` / `impressions`（计算承接率时，优先用 reads；缺 reads 则用 impressions；均缺则承接率为 None）。
- `note_id` / `title`（任一存在即可用于标识笔记行；均缺失时标识为 `None`）。

## Method — 各 Finding

### Finding 1 — 笔记承接效率汇总与明细（始终产出当 notes 表存在时）

- 汇总指标：
  - 进店：`Σ to_shop_home_count` / `Σ to_shop_home_gmv`；承接率 `= Σ to_shop_home_count / (Σ reads 或 Σ impressions)`。
  - 直播间：`Σ to_live_count` / `Σ to_live_gmv`；承接率同理。
  - 平均支付：进店金额 / 进店次数；直播间金额 / 直播次数（次数 > 0 时计算）。
- 承接率分母优先选 reads；缺 reads 但有 impressions 时，在 caveat 标注。
- 明细表 `note_carry`（Top 20 按 `to_shop_home_gmv + to_live_gmv` 降序）：
  含 note_id/title、曝光/阅读、进店次数/金额、直播间次数/金额。
- 四列全缺时产出 `NOT_JUDGABLE` 缺列告知 Finding；部分缺失时记 limitation + caveat。
- Evidence `has_controls=False` → 上限 WEAK（`score_evidence(note_count, ...)`）。
  Confounders：笔记曝光结构差异、店铺主页承接与直播间体验差异、内容类型与渠道匹配。

## Thresholds

- Top 20 明细表：按总承接支付金额排序。
- 除零守卫：承接次数 = 0 时平均支付为 None，不抛异常。

## Output tables

`note_carry`（Top 20 承接笔记明细）。仅在四列之一存在时产出。

## Failure modes（降级矩阵）

| 缺失 | 行为 |
|---|---|
| `notes` | `NOT_JUDGABLE` `_missing_result`（唯一无真实 Finding 的情形）。 |
| 四列全缺（进店/直播承接字段） | `NOT_JUDGABLE` 缺列告知 Finding，仍不为空。 |
| 部分列缺（如仅缺直播） | 只计算有列的渠道，记 limitation + caveat 说明缺哪边。 |
| `reads` 和 `impressions` 均缺 | 承接率为 None，记 caveat。 |
| 承接次数 = 0 | 平均支付为 None（不求商）。 |
| 无正承接支付 | 明细表为空，结论说「无有效承接数据」。 |

Finding 1 在 `notes` 表存在时**始终**产出 → `run()` 的 findings 永不为空（`notes` 表存在时）。

## Levers（recommended_action）

- 进店/直播承接效率低 → 优化笔记与店铺主页/直播间的视觉/文案衔接，测试新的引流选题。
- 高曝光但低承接 → 检查笔记与店铺主页/直播间的产品相关性与价位是否匹配。
- 某类笔记承接好 → 复制该笔记的选题/形式并加投或做系列延展。

## Caveats baked in

1. 用 `_table_columns` 守卫每一列后再引用（`read_csv_auto` 可能缺列）。
2. `note_id`/`title` 任一存在即可标识笔记行，均缺失时标识为 `None`，不抛异常。
3. 承接率优先用 reads；缺 reads 则用 impressions；均缺则为 None，在 caveat 标注。
4. 所有 `/ count` 都守卫 count > 0；0 分母返回 None，不抛异常。
5. 每个 Finding 填 confounders（笔记曝光结构差异、店铺主页承接与直播间体验差异、内容类型与渠道匹配）
   + 观察性 caveat。
6. 不做因果归因：承接率是笔记到店铺主页/直播间的流量比例，不涉及转化机制、
   直播间商品选品、或主播表现——这些属于独立的直播/店铺诊断模块。

## Cross-links

- 同级模块：`note_commercial_diagnosis`（笔记直接成交效能）。
- 同批模块：`channel_structure_diagnosis`（渠道与笔记效率矩阵）。

## 常见误读提醒

- **「笔记承接效率」不等于「直播总览」：** 本模块只看笔记引流到直播间的*次数与支付*，
  不涉及直播间的停留时长、主播话术、商品选品或实时转化——那些需要独立的直播诊断。
- **「进直播间 GMV」不是「直播间产品销量」：** 计数的是笔记引流到直播间后*可归因的支付*，
  取决于千帆导出的字段精度（支付时间口径），不是直播间商品级漏斗。
- **「承接率」是流量比，不是转化：** Σ 进店次数 / Σ 阅读数 ≠ 进店后成交率；
  后者需要店铺主页的人群与产品漏斗数据。
