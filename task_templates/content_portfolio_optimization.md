# content_portfolio_optimization

**Slug**: `content_portfolio_optimization`  |  **Module**: `xhs_ceramics_analytics/analysis/portfolio.py`  |  **Registry**: registry.py:39

## Purpose

按 copy_angle 维度统计已发布笔记的内容组合分布，计算各角度的笔记数量占比、平均阅读量及收藏率，帮助运营识别低占比但高效率的文案角度作为下周排期候选。本任务仅做描述性统计，不包含疲劳度分析、探索/利用比例拆分、也不生成排期建议矩阵（排期由 weekly_experiment_matrix 负责）。

## Required tables & fields

- `content_features` (required) — key columns: `copy_angle`, `note_id`
  - `copy_angle`: 分组维度，空值/NULL 统一归为 'unknown'
  - `note_id`: 与 notes 表关联的键；缺失时走 unjoined 路径
  - Chinese header hints: content_features 无中文别名定义，匹配依赖 exact/normalized 或 rapidfuzz

- `notes` (optional) — key columns: `note_id`, `reads`, `collects`
  - Chinese header hints: `笔记id/笔记ID -> note_id`, `阅读次数/笔记阅读数/阅读数 -> reads`, `收藏数/收藏次数 -> collects`
  - 仅当 content_features 含 note_id 且 notes 含 {note_id, reads, collects} 时才 JOIN

## Method

1. 打开 DuckDB 连接，检查 content_features 表是否存在；不存在则返回空行并附 limitation（portfolio.py:12-15）。
2. 通过 PRAGMA table_info 读取 content_features 列集合；如缺少 copy_angle 列，返回空行并附 limitation（portfolio.py:55-57）。
3. 判断是否可关联 notes 表：content_features 需有 note_id，且 notes 需有 {note_id, reads, collects}（portfolio.py:59-64）。
4. 若可关联：LEFT JOIN content_features 与 notes（按 CAST(note_id AS VARCHAR) 匹配），按清洗后 copy_angle 分组，计算 notes 数量、mix_share、avg_reads、avg_collect_rate（portfolio.py:65-80）。
5. 若不可关联：仅对 content_features 按 copy_angle 分组，avg_reads/avg_collect_rate 输出 NULL；若 notes 表存在但列不全则追加 limitation（portfolio.py:82-101）。
6. 对 mix_share、avg_reads、avg_collect_rate 四舍五入至 4 位小数（portfolio.py:108-113）。
7. 计算 sample_size = 所有行 notes 之和；top_role = 按 notes DESC 排序后第一行的 copy_angle（portfolio.py:19-20）。
8. 以 score_evidence(sample_size, has_controls=False, confounder_count=1) 评分证据强度，输出单条 Finding（portfolio.py:33-35）。

## Key formulas

- `copy_angle := COALESCE(NULLIF(TRIM(CAST(cf.copy_angle AS VARCHAR)), ''), 'unknown')`  (portfolio.py:68-69)
- `notes := COUNT(*) GROUP BY copy_angle`  (portfolio.py:70)
- `mix_share := COUNT(*) * 1.0 / SUM(COUNT(*)) OVER ()`  (portfolio.py:71)
- `avg_reads := AVG(CAST(n.reads AS DOUBLE))`  (portfolio.py:72)
- `avg_collect_rate := AVG(CASE WHEN n.reads > 0 THEN n.collects * 1.0 / n.reads END)`  (portfolio.py:73-74)
- `sample_size := Sigma(notes) over all rows`  (portfolio.py:19)
- `evidence_strength := score_evidence(sample_size, has_controls=False, confounder_count=1)`  (portfolio.py:33-35 + evidence.py:11-20)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|---------|---------|
| sample_size <= 0（无数据行） | Not-judgable | evidence.py:14-15 via portfolio.py:33-35 |
| sample_size >= 1, has_controls=False, confounder_count=1 | Weak | evidence.py:20 (default branch) |
| STRONG (sample_size>=30 AND has_controls AND confounder_count==0) | Strong (本任务不可达，has_controls 硬编码 False) | evidence.py:16-17 |
| MEDIUM (sample_size>=10 AND has_controls AND confounder_count<=1) | Medium (本任务不可达，has_controls 硬编码 False) | evidence.py:18-19 |

## Output

- **Result frame** `portfolio_mix`:
  - `copy_angle` — 清洗后文案角度标签
  - `notes` — 该角度下笔记数量（整数）
  - `mix_share` — 占比 (0-1)，4 位小数
  - `avg_reads` — 平均阅读量；无 notes 关联时为 NULL
  - `avg_collect_rate` — 平均收藏率（collects/reads，仅 reads>0 参与）；无关联时为 NULL
  - 排序：joined 路径 ORDER BY notes DESC, avg_reads DESC NULLS LAST, copy_angle；unjoined 路径 ORDER BY notes DESC, copy_angle

- **Finding**: title="文案角度组合已统计", evidence_strength=Weak/Not-judgable, caveat="角度占比描述的是已发布内容供给，不是受控需求。", recommended_action 视 rows 是否为空切换。

## Sample output section

```markdown
## 内容组合优化

### 文案角度组合已统计

已统计 47 篇笔记，覆盖 5 类文案角度。

证据强度：弱

关键数字：
- `notes`: 47
- `roles`: 5
- `top_role`: 送礼场景

注意事项：
- 角度占比描述的是已发布内容供给，不是受控需求。

建议动作：将占比不足且阅读率或收藏率更强的角度，作为下周内容档期候选。

表格 `portfolio_mix`：5 行

| copy_angle | notes | mix_share | avg_reads | avg_collect_rate |
| --- | --- | --- | --- | --- |
| 送礼场景 | 18 | 0.3830 | 1245.0 | 0.0832 |
| 日常泡茶 | 12 | 0.2553 | 980.5 | 0.0714 |
| 新品开箱 | 9 | 0.1915 | 1520.0 | 0.1023 |
| 收藏升值 | 5 | 0.1064 | 760.0 | 0.0456 |
| unknown | 3 | 0.0638 | 420.0 | 0.0312 |
```

## Common failure modes

- content_features 表缺失 -> rows=[], limitation='缺少 content_features 表。', evidence=Not-judgable -> 需先导入带 copy_angle 的内容标注数据
- content_features 有表但无 copy_angle 列 -> rows=[], limitation 叠加两条 -> 检查导入映射或手动添加标注列
- notes 表完全缺失 -> unjoined 路径执行，avg_reads/avg_collect_rate=NULL，无额外 limitation -> 导入千帆笔记数据即可恢复
- notes 存在但缺少 note_id/reads/collects -> unjoined 路径 + limitation '组合指标留空' -> 核实导出字段是否包含阅读数、收藏数
- content_features 无 note_id 列 -> can_join_notes=False，走 unjoined 路径，无额外 limitation（静默降级）-> 如需指标需在标注表补充 note_id
- 所有 notes 的 reads=0 或 NULL -> avg_collect_rate 对该 bucket 返回 NULL，avg_reads 按 AVG 跳过 NULL
- copy_angle 全部为空/NULL -> 统一归入 'unknown' 单行

## Fixtures

- `tests/fixtures/content_features.csv` — 必需
- `tests/fixtures/notes.csv` — 推荐（启用 JOIN 路径以获取完整指标）

Minimum viable fixture set for this task: content_features.csv (含 note_id + copy_angle 列)。

## Cross-links

- Depends on: 无直接依赖其他 task 的输出
- Feeds: [weekly_experiment_matrix](./weekly_experiment_matrix.md)（读取相同 content_features.copy_angle 源表做排期，但不消费本 task 输出）
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
