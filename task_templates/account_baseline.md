# account_baseline

**Slug**: `account_baseline`  |  **Module**: `xhs_ceramics_analytics/analysis/account_baseline.py`  |  **Registry**: registry.py:30

## Purpose

计算账号的发布基线：按日统计笔记发布量和平均阅读数，形成对"正常发布节奏"的描述性概括。此任务仅做描述性统计（笔记数、活跃天数、日均阅读），不做趋势预测、异常检测或因果归因，也不计算互动率（点赞率/收藏率等属于 note_funnel 任务）。

## Required tables & fields

- `notes` (required) — key columns: `publish_time`, `reads`(optional)
  Chinese header hints: `发布时间 / 笔记发布时间 / 笔记创建时间 / 创建时间 -> publish_time`; `阅读次数 / 笔记阅读数 / 阅读数 -> reads`

注意：`reads` 列缺失时不会报错，SQL 会用 NULL 替代 avg_reads；但 `publish_time` 列缺失会直接返回 NOT_JUDGABLE。

## Method

1. 打开 DuckDB 连接，检查 `notes` 表是否存在；不存在则返回 NOT_JUDGABLE 并注明"缺少 notes 表。"（L12-13）
2. 获取 notes 表所有列名，检查 `publish_time` 是否存在；不存在则返回 NOT_JUDGABLE 并注明"notes 表缺少 publish_time 字段。"（L14-16）
3. 根据 `reads` 列是否存在，构建 avg_reads 表达式：有则为 `AVG(CAST(reads AS DOUBLE))`，无则为 `NULL`（L17）
4. 执行聚合 SQL：`CAST(publish_time AS DATE)` 分组，统计每日 posts 数量和 avg_reads，按日期升序排列，过滤 `publish_time IS NOT NULL`（L18-28）
5. 将查询结果物化为 `daily_posts` 列表（L30-33）
6. 计算 sample_size = SUM(所有日 posts 数)（L36）
7. 调用 `score_evidence(sample_size, has_controls=False, confounder_count=1)` 确定证据强度，组装 Finding 返回（L47-48）

## Key formulas

- `posts_per_day = COUNT(*) GROUP BY CAST(publish_time AS DATE)`  (account_baseline.py:22)
- `avg_reads = AVG(CAST(reads AS DOUBLE)) GROUP BY CAST(publish_time AS DATE)`  (account_baseline.py:23)
- `sample_size = SUM(row["posts"] for row in daily_posts)`  (account_baseline.py:36)
- `evidence = score_evidence(sample_size, has_controls=False, confounder_count=1)`  (account_baseline.py:47-48)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|---------|---------|
| notes 表不存在 | Not-judgable | account_baseline.py:12-13 |
| publish_time 列不存在 | Not-judgable | account_baseline.py:15-16 |
| sample_size <= 0（空表或全部 publish_time 为 NULL） | Not-judgable | evidence.py:14 |
| sample_size >= 1 但 < 30（has_controls=False 走 else 分支） | Weak | evidence.py:20 |
| sample_size >= 30（has_controls=False，仍走 else 分支） | Weak | evidence.py:20 |

注：由于 `has_controls=False`，score_evidence 永远不会返回 STRONG 或 MEDIUM，此任务证据强度上限为 Weak。

## Output

- **Result frame**: `daily_posts` — columns: `date`(VARCHAR, YYYY-MM-DD), `posts`(int, 当日发布笔记数), `avg_reads`(float|None, 当日平均阅读数)
- **Finding**: title="发布基线", evidence_strength=WEAK (正常) 或 NOT_JUDGABLE (数据缺失)
  - key_numbers: `{"posts": <total>, "active_days": <distinct dates>}`
  - caveats: `["样本量和对照上下文有限，这个基线只能做描述性判断。"]`
  - 无 recommended_action（正常路径）
- **Missing path Finding**: title="发布基线不可计算"
  - caveats: `["基线数据缺失应视为导入缺口。"]`
  - recommended_action: "导出包含 publish_time 和 reads 的 notes 数据，然后重新构建。"

## Sample output section

```markdown
## 账号基线

### 发布基线

当前数据包含 47 篇笔记，覆盖 23 个有发布记录的日期。

证据强度：弱

关键数字：
- `posts`: 47
- `active_days`: 23

表格 `daily_posts`：23 行

| date | posts | avg_reads |
| --- | --- | --- |
| 2026-05-10 | 3 | 1842.33 |
| 2026-05-11 | 2 | 2105.00 |
| 2026-05-12 | 1 | 956.00 |
| 2026-05-13 | 4 | 1320.75 |
| 2026-05-14 | 2 | 2480.50 |

注意事项：样本量和对照上下文有限，这个基线只能做描述性判断。
```

## Common failure modes

- notes 表不存在 -> 返回 NOT_JUDGABLE，limitations=["缺少 notes 表。"] -> 建议导出 notes 数据
- notes 表存在但无 publish_time 列 -> 返回 NOT_JUDGABLE，limitations=["notes 表缺少 publish_time 字段。"] -> 检查导出模板是否包含发布时间字段
- notes 表非空但所有行 publish_time=NULL -> SQL WHERE 过滤后零行，sample_size=0 -> NOT_JUDGABLE via evidence.py -> 检查数据源发布时间是否正确导入
- reads 列不存在 -> avg_reads 全部为 NULL，不影响 posts 计数和 active_days，Finding 仍正常返回 -> 建议补充 reads 列以获得完整基线

## Fixtures

- `tests/fixtures/notes.csv` — columns: note_id, publish_time, title, body, note_type, cover_image_path, impressions, reads, likes, collects, comments, shares, followers_gained

Minimum viable fixture set for this task: `notes.csv`（至少包含 `publish_time` 列即可运行）。

## Cross-links

- Depends on: none (此任务为独立入口任务，不依赖其他分析任务的输出)
- Feeds: [weekly_business_review](./weekly_business_review.md) (weekly_review.py 的 _baseline_section 复用了相同的基线统计逻辑)
- Reference: [../references/data_contract.md](../references/data_contract.md)
