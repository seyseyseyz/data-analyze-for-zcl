# weekly_experiment_matrix

**Slug**: `weekly_experiment_matrix`  |  **Module**: `xhs_ceramics_analytics/analysis/experiment_matrix.py`  |  **Registry**: registry.py:40

## Purpose

基于历史 SKU 销量和内容表现数据，生成未来七天、每天五个时段的确定性实验排期矩阵（35 个档期）。通过取模轮转将 top SKU 与 top 文案角度交叉组合，让运营按计划发布并收集对比数据。本任务只负责生成排期计划，不做效果回测或因果推断——因果分析由 sku_counterfactual_lift 完成。

## Required tables & fields

所有表均为可选；缺失时触发兜底逻辑：

- `daily_sku_sales` (optional) — key columns: `sku_id`, `units`, `gmv`
  作为 top-SKU 首选来源；按 SUM(units) DESC, SUM(gmv) DESC 排序取前 5。
- `skus` (optional) — key columns: `sku_id`, `sku_name`, `price`
  用于 JOIN 获取 sku_name；当 daily_sku_sales 缺失时作为兜底 SKU 源（按 price DESC 排序）。
- `content_features` (optional) — key columns: `copy_angle`, `note_id`
  文案角度来源；按 COUNT(*) 和 AVG(reads) 排序取前 5。
- `notes` (optional) — key columns: `note_id`, `reads`, `publish_time`
  reads 用于文案角度加权排序；publish_time 用于确定计划起始日期。

## Method

1. 打开 DuckDB 连接，依次获取 top-5 SKU、top-5 文案角度、计划起始日期（lines 13-20）。
2. SKU 获取：若 daily_sku_sales 存在且含 sku_id，按 SUM(units) DESC / SUM(gmv) DESC 分组排序取前 5，并 JOIN skus 获取名称（lines 62-124）。
3. SKU 兜底：若 daily_sku_sales 不可用，读取 skus 按 price DESC LIMIT 5；若均不可用则返回单行 'unassigned / 未分配 SKU'（lines 126-159）。
4. 文案角度获取：读取 content_features；若 notes 可 JOIN 则按 COUNT(*) DESC, AVG(reads) DESC 排序；否则仅按 COUNT(*) 排序。空白角度转为 'unknown'，全空则兜底为 ['lifestyle']（lines 162-212）。
5. 计划起始日：取 max(publish_time)+1 天，下限为 today+1；可通过环境变量 XHS_CA_TODAY 覆盖 today（lines 215-246）。
6. 构建 7x5=35 格排期：对 absolute_slot = day*5 + slot，sku = skus[absolute_slot % len(skus)]，angle = angles[(day+slot) % len(angles)]（lines 249-272）。
7. 计算证据强度：score_evidence(evidence_inputs, has_controls=False, confounder_count=2)；当使用兜底 SKU 或兜底角度时 evidence_inputs=0（lines 23-42）。

## Key formulas

- `planned_rows = 7 * len(_SLOTS) = 35`  (lines 10, 253-256)
- `sku = skus[(day_offset * 5 + slot_offset) mod len(skus)]`  (lines 256-257)
- `angle = angles[(day_offset + slot_offset) mod len(angles)]`  (line 258)
- `experiment_seed = f"{plan_date_iso}-{slot_time}-{sku_id}-{angle}"`  (line 268)
- `planning_start = max(max(publish_time) + 1day, today + 1day)`  (lines 234-235, 238-246)
- `evidence_inputs = 0 if any(sku_id=='unassigned') or angles==['lifestyle'] else len(skus)+len(angles)`  (lines 23-26)
- `copy_angle ranking: ORDER BY COUNT(*) DESC, AVG(reads) DESC NULLS LAST, copy_angle`  (lines 186-187)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|---------|---------|
| sample_size <= 0 or confounder_count < 0 | Not-judgable / 不可判断 | evidence.py:15 |
| sample_size >= 30 AND has_controls AND confounder_count == 0 | Strong / 强 | evidence.py:16（本任务不会触发：has_controls=False） |
| sample_size >= 10 AND has_controls AND confounder_count <= 1 | Medium / 中 | evidence.py:18（本任务不会触发） |
| 默认路径（本任务固定 has_controls=False, confounder_count=2） | Weak / 弱 | evidence.py:20; experiment_matrix.py:41-43 |
| 使用兜底 SKU 或兜底角度 -> evidence_inputs=0 | Not-judgable / 不可判断 | experiment_matrix.py:23-26 + evidence.py:15 |

## Output

**Result frame — `experiment_plan`** (35 rows):

| Column | Semantics |
|--------|-----------|
| `date` | ISO 日期字符串，计划日期 |
| `day_index` | 1..7，第几天 |
| `slot_index` | 1..5，当天第几个时段 |
| `slot_time` | '09:00' / '12:00' / '15:00' / '18:00' / '21:00' |
| `sku_id` | 选中的 SKU id；兜底时为 'unassigned' |
| `sku_name` | 可读 SKU 名称；无名称时回退为 sku_id |
| `copy_angle` | 文案角度（如 lifestyle / gift / unknown） |
| `experiment_seed` | 确定性种子 '{date}-{slot}-{sku_id}-{angle}' |
| `success_metric` | 固定值 'collect_rate' |

**Finding**: 标题「七天实验计划已生成」，evidence_strength 由上表决定，caveat 固定为「这是确定性排期矩阵，不代表这些档期一定会胜出。」，recommended_action =「按矩阵发布受控周档期，并用阅读、收藏和评论需求指标比较每个档期。」

## Sample output section

```markdown
## 每周实验矩阵

限制：
- skus 表缺少 price，实验 SKU GMV 留空。

### 七天实验计划已生成

已生成 35 个确定性测试档期，覆盖 7 天、每天 5 个时段。

证据强度：弱

关键数字：
- `planned_rows`: 35
- `days`: 7
- `slots_per_day`: 5
- `unique_skus`: 5
- `content_angles`: 4

注意事项：
- 这是确定性排期矩阵，不代表这些档期一定会胜出。

建议动作：
按矩阵发布受控周档期，并用阅读、收藏和评论需求指标比较每个档期。

| date | day_index | slot_index | slot_time | sku_id | sku_name | copy_angle | experiment_seed | success_metric |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-07-04 | 1 | 1 | 09:00 | 8123 | 素白拉丝盖碗 | lifestyle | 2026-07-04-09:00-8123-lifestyle | collect_rate |
| 2026-07-04 | 1 | 2 | 12:00 | 8456 | 青釉咖啡杯 单只 | gift | 2026-07-04-12:00-8456-gift | collect_rate |
```

## Common failure modes

- daily_sku_sales 缺失或无 sku_id 列 -> 兜底至 skus 表；若 skus 也不可用则生成单行 'unassigned' SKU，evidence_inputs=0 导致证据强度为不可判断。
- daily_sku_sales 存在但缺 units/gmv 列 -> 对应 SELECT 表达式变为 NULL，行仍返回，追加 limitation 字符串。
- skus 表无 sku_name -> JOIN 跳过，sku_name 回退为 CAST(sku_id AS VARCHAR)。
- content_features 表缺失或缺 copy_angle 列 -> 返回 ['lifestyle'] 兜底角度，触发 evidence_inputs=0。
- notes 表缺失或缺 note_id/reads -> 文案角度仅按 COUNT(*) 排序，无 AVG(reads) 加权。
- notes.publish_time 缺失或全 NULL -> 计划起始日默认为 today+1。
- content_features 查询结果全为空白角度 -> COALESCE/NULLIF 将其映射为 'unknown'；若结果集为空则兜底 ['lifestyle']。

## Fixtures

- `tests/fixtures/notes.csv` — 提供 note_id, publish_time, reads（计划起始日期和角度排序）
- `tests/fixtures/content_features.csv` — 提供 note_id, copy_angle（角度来源；样例值 lifestyle, gift）
- `tests/fixtures/skus.csv` — 提供 sku_id, sku_name, price（兜底 SKU 来源，因无 daily_sku_sales fixture）

Minimum viable fixture set for this task: notes.csv, content_features.csv, skus.csv.

## Cross-links

- Depends on: 无（本任务独立运行，不消费其他分析任务的输出）
- Feeds: [sku_counterfactual_lift](./sku_counterfactual_lift.md)（运营按矩阵执行后，用因果分析评估效果）
- Reference: [../references/evidence_strength.md](../references/evidence_strength.md), [../references/data_contract.md](../references/data_contract.md)
