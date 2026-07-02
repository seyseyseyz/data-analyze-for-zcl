# reshoot_repost_candidates

**Slug**: `reshoot_repost_candidates`  |  **Module**: `xhs_ceramics_analytics/analysis/reshoot.py`  |  **Registry**: registry.py:41

## Purpose

识别收藏率高但阅读量受限的笔记，输出最多 10 条重拍/重发优先候选列表。核心逻辑：对每条笔记计算保守收藏率（按阅读样本量收缩），再加上与全局最高阅读量的差距得分，综合排序。本任务不涉及 SKU 销售数据、内容特征分析或封面风格判断 -- 仅依据 notes 表的阅读/收藏指标做排序。

## Required tables & fields

- `notes` (required) -- key columns: `note_id`, `reads`, `collects`
  Chinese header hints: `笔记id/笔记ID -> note_id`, `阅读次数/笔记阅读数/阅读数 -> reads`, `收藏数/收藏次数 -> collects`
- `notes.title` (optional column) -- 若存在则展示笔记标题，否则回退为 `note_id` 作为 title
  Chinese header hints: `笔记标题/标题 -> title`

## Method

1. 打开 DuckDB 连接，检查 `notes` 表是否存在 (reshoot.py:12-14)。
2. 通过 `PRAGMA table_info('notes')` 检查必需列 `{note_id, reads, collects}` 是否齐全；缺列则返回空结果 (reshoot.py:53-57)。
3. 查询每条笔记的 note_id、title（或 note_id 回退）、reads、collects；过滤掉 reads/collects 为 NULL 或 reads <= 0 的行 (reshoot.py:60-73)。
4. 计算全局 max_reads；对每条笔记计算 collect_rate、confidence_weight、conservative_collect_rate、read_gap_to_max (reshoot.py:82-90)。
5. 标记 needs_more_data（reads < 50）并分配 reason 字段 (reshoot.py:91, 105-109)。
6. 计算 opportunity_score 并按多级排序键排序，取前 10 条，附加 1-indexed rank (reshoot.py:92, 113-126)。
7. 将结果封装为 AnalysisResult，Finding 证据强度由 `score_evidence(len(metrics), has_controls=False, confounder_count=1)` 决定 (reshoot.py:30-32)。

## Key formulas

- `collect_rate = collects / reads`  (reshoot.py:87)
- `confidence_weight = reads / (reads + 50)`  (reshoot.py:88; _MIN_CONFIDENT_READS=50 at line 8)
- `conservative_collect_rate = collect_rate * confidence_weight`  (reshoot.py:89)
- `read_gap_to_max = (max_reads - reads) / max_reads`  (reshoot.py:90; 0.0 if max_reads==0)
- `needs_more_data = reads < 50`  (reshoot.py:91)
- `opportunity_score = conservative_collect_rate * 100 + read_gap_to_max * 0.25`  (reshoot.py:92)
- `sort_key = (needs_more_data ASC, -opportunity_score, -conservative_collect_rate, -collect_rate, -reads, note_id ASC); LIMIT 10`  (reshoot.py:113-125)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|----------|----------|
| sample_size > 0, has_controls=False, confounder_count=1 | Weak (本任务能达到的最高等级) | evidence.py:20; reshoot.py:30-32 |
| sample_size <= 0 (metrics 为空) | Not-judgable | evidence.py:14-15 |
| reads < 50 (行级) | 行标记 needs_more_data=True, 排序降权 | reshoot.py:91, 115 |
| reads >= 50 (行级) | reason='high_collect_rate_low_read_ceiling' | reshoot.py:105-109 |

注：由于 has_controls 始终为 False，本任务无法达到 Strong 或 Medium 等级。

## Output

- **Result frame** `reshoot_candidates` (最多 10 行):
  - `rank` -- 1-indexed 排名
  - `note_id` -- 笔记标识 (VARCHAR)
  - `title` -- 笔记标题或 note_id 回退
  - `reads` -- 阅读数 (int)
  - `collects` -- 收藏数 (int)
  - `collect_rate` -- 收藏率 (4位小数)
  - `conservative_collect_rate` -- 保守收藏率，按样本量收缩 (4位小数)
  - `confidence_weight` -- 样本置信权重 reads/(reads+50) (4位小数)
  - `read_gap_to_max` -- 与最高阅读的差距比 (4位小数)
  - `opportunity_score` -- 综合机会分 (4位小数)
  - `needs_more_data` -- 布尔标记
  - `reason` -- 'high_collect_rate_low_read_ceiling' 或 'promising_but_needs_more_reads'

- **Finding**: title="高收藏笔记重拍候选已排序", evidence_strength=Weak|Not-judgable
  - caveats: "高收藏率可能代表小众强意图，重拍优先级仍需要创意复核。" / "小样本笔记会被降权，进入队首前需要更多数据。"
  - recommended_action (有结果时): "优先重拍队首候选，用更清晰的开场画面做对照；确认阅读率提升后再扩大重发。"
  - recommended_action (空结果时): "先收集可读的笔记指标，再选择重拍候选。"

## Sample output section

```markdown
## 重拍与重发候选

### 高收藏笔记重拍候选已排序

已按收藏率并结合低阅读补偿，对 5 篇笔记排序。

证据强度：弱

关键数字：
- `candidate_notes`: 5
- `top_candidate`: n0023

注意事项：
- 高收藏率可能代表小众强意图，重拍优先级仍需要创意复核。
- 小样本笔记会被降权，进入队首前需要更多数据。

建议动作：优先重拍队首候选，用更清晰的开场画面做对照；确认阅读率提升后再扩大重发。

| rank | note_id | title | reads | collects | collect_rate | conservative_collect_rate | opportunity_score | needs_more_data | reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | n0023 | 素白拉丝盖碗 180ml | 320 | 48 | 0.1500 | 0.1297 | 13.0427 | False | high_collect_rate_low_read_ceiling |
| 2 | n0087 | 青瓷荷叶杯垫套装 | 185 | 26 | 0.1405 | 0.1106 | 11.1419 | False | high_collect_rate_low_read_ceiling |
| 3 | n0112 | 手工柴烧主人杯 | 32 | 7 | 0.2188 | 0.0854 | 8.7636 | True | promising_but_needs_more_reads |
```

## Common failure modes

- notes 表缺失 -> metrics=[], 返回空 reshoot_candidates, limitations=['没有可用的笔记阅读/收藏指标。'], evidence=Not-judgable -> 建议先导入笔记数据
- notes 存在但缺少 note_id/reads/collects 列 -> 同上空结果 -> 建议检查导入映射配置
- 所有行 reads 为 NULL 或 <= 0 -> SQL WHERE 过滤后 metrics 为空 -> 同上 -> 建议确认数据源是否包含有效阅读数
- 仅 1-2 条笔记 -> 排序正常进行但 max_reads 可能等于单行 reads，read_gap_to_max=0 -> opportunity_score 退化为 conservative_collect_rate*100 -> 结果可用但参考价值有限
- reads==0 行 -> 被 SQL `reads > 0` 过滤；Python 侧额外 guard `if reads else 0.0` 防止除零

## Fixtures

- `tests/fixtures/notes.csv` (3 rows: n1..n3, 含 note_id + reads + collects + title)

Minimum viable fixture set for this task: `notes.csv` (需包含 note_id, reads, collects 列，至少 1 行 reads > 0).

## Cross-links

- Depends on: none (standalone, only reads `notes` table)
- Feeds: [hypothesis_knowledge_base](./hypothesis_knowledge_base.md) (hypothesis task also reads notes but independently)
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
