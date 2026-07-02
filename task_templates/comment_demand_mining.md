# comment_demand_mining

**Slug**: `comment_demand_mining`  |  **Module**: `xhs_ceramics_analytics/analysis/comment_demand.py`  |  **Registry**: registry.py:38

## Purpose

从评论文本中挖掘用户需求信号，将每条评论归入 5 个固定需求分组（capacity / price / link / gift / other），统计各组的评论量、关联笔记数、占比，并输出示例文本。该任务仅做关键词匹配分组，不做语义理解、情感分析或购买意图建模。

## Required tables & fields

- `comments` (optional — 若缺失则跳过并输出 limitation) — key columns: `comment_text` (hard-required), `note_id` (optional), `comment_time` (optional)
  Chinese header hints: `comment_text` 无中文别名定义（依赖 fuzz match）; `note_id` → `笔记id` / `笔记ID`; `comment_time` 无中文别名定义

## Method

1. 打开 DuckDB，通过 `SHOW TABLES` 检查 `comments` 表是否存在；若不存在，输出 limitation 并跳过后续步骤。(line 20, 135-136)
2. 通过 `PRAGMA table_info('comments')` 获取列集合；若缺少 `comment_text` 列则返回空列表。(lines 68-70, 139-140)
3. 查询非空评论：`WHERE comment_text IS NOT NULL AND TRIM(comment_text) <> ''`，按 comment_time / note_id / comment_text 中已存在的列排序。(lines 79-89)
4. 初始化 5 个固定需求桶：price, link, capacity, gift, other（`_GROUPS` 定义顺序）。(line 8)
5. 对每条评论 lowercase 文本，按 capacity -> price -> link -> gift 顺序检查关键词列表，首次命中即分组，否则归入 other。(lines 127-132)
6. 每个桶累计：评论数、去重 note_id 集合、前 3 条示例文本。(lines 101-109)
7. 计算 comment_share 并按评论数降序 + 分组名升序排列输出行。(lines 120, 124)
8. 取第一个 comments>0 的行作为 top_group；调用 score_evidence(total_comments, has_controls=False, confounder_count=1) 评估证据强度。(lines 46-48)

## Key formulas

- `comment_share = bucket_comments / total_comments` (rounded 4dp; 0.0 when total==0)  (comment_demand.py:120)
- `notes = |{note_id : classify(comment)=group AND note_id is not None}|`  (comment_demand.py:106-107, 119)
- `sort_key = (-comments, demand_group_name_asc)`  (comment_demand.py:124)
- `group = first g in [capacity, price, link, gift] s.t. any(keyword in lower(text) for keyword in _KEYWORDS[g]); else 'other'`  (comment_demand.py:127-132)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|----------|----------|
| total_comments == 0 (无评论数据) | Not-judgable | evidence.py:14-15; comment_demand.py:46-48 |
| total_comments < 10 | Weak + caveat "评论量较小，需求占比只能作为方向性参考。" | comment_demand.py:33-34; evidence.py:20 |
| total_comments >= 1 (一般情况) | Weak (has_controls=False 硬编码，Strong/Medium 分支不可达) | evidence.py:20; comment_demand.py:46-48 |
| sample_size >= 30 AND has_controls AND confounder_count == 0 | Strong (本任务不可达) | evidence.py:16 |
| sample_size >= 10 AND has_controls AND confounder_count <= 1 | Medium (本任务不可达) | evidence.py:18 |

## Output

- **Result frame** `comment_demands` (固定 5 行，每个分组一行):
  - `demand_group` — 分组标识: capacity | price | link | gift | other
  - `comments` — 该组评论数（整数）
  - `notes` — 该组去重 note_id 数量（仅非 NULL note_id 计入）
  - `comment_share` — 该组评论占总评论比例，4 位小数（总数为 0 时返回 0.0）
  - `example_comments` — 最多 3 条原始评论文本列表（按插入顺序）

- **Finding**: title="评论需求分组已提取", evidence_strength=Weak/Not-judgable
  - caveats: "评论意图基于关键词分组，调整商品文案前需要人工复核。" (always); "评论量较小，需求占比只能作为方向性参考。" (when total < 10)
  - recommended_action: "用排名靠前的需求分组更新笔记回复、商品详情文案和下周 FAQ 内容。" (when total > 0); "先收集更多评论，再调整需求假设。" (when total == 0)

## Sample output section

```markdown
## 评论需求挖掘

### 评论需求分组已提取

已将 47 条评论归入 4 个有观测数据的需求分组。

证据强度：弱

关键数字：
- `comments`: 47
- `observed_groups`: 4
- `top_group`: link

注意事项：
- 评论意图基于关键词分组，调整商品文案前需要人工复核。

建议动作：

用排名靠前的需求分组更新笔记回复、商品详情文案和下周 FAQ 内容。

表格 `comment_demands`：5 行

| demand_group | comments | notes | comment_share | example_comments |
| --- | --- | --- | --- | --- |
| link | 18 | 7 | 0.3830 | ["有链接吗", "怎么买这个盖碗", "橱窗在哪"] |
| capacity | 12 | 5 | 0.2553 | ["容量多少ml", "这个装多少茶汤", "尺寸多大"] |
| gift | 9 | 4 | 0.1915 | ["送朋友合适吗", "有礼盒装吗", "新婚礼物推荐"] |
| price | 8 | 6 | 0.1702 | ["多少钱", "价格贵吗", "预算200内有吗"] |
| other | 0 | 0 | 0.0000 | [] |
```

## Common failure modes

- `comments` 表完全缺失 — `_table_exists` 返回 False，输出 limitation "没有可用于需求挖掘的评论数据。"，evidence 为 Not-judgable，recommended_action 切换为收集评论建议。建议: 确认导入流程是否包含评论数据源。
- `comments` 表存在但无 `comment_text` 列 — `_fetch_comments` 返回空列表，触发同样的 Not-judgable 路径。建议: 检查 CSV 导入列映射。
- `comment_text` 列存在但所有行为 NULL 或空字符串 — SQL WHERE 过滤后 fetchall 为空，同 Not-judgable 路径。建议: 检查数据源是否正确抓取评论正文。
- 缺少 `note_id` 列 — SELECT 投射 `NULL AS note_id`，所有桶的 notes 计数均为 0，不影响分组逻辑。建议: 补充 note_id 可关联评论热度到具体笔记。
- 缺少 `comment_time` 列 — ORDER BY 中去掉该列，排序退化为 note_id + comment_text 或无排序。不影响分组结果。

## Fixtures

- `tests/fixtures/comments.csv` — 最小化 fixture（3 行: 覆盖 link/capacity/gift 分组）
- `tests/fixtures/notes.csv` — 非本任务直接使用（无 join），但测试环境中常共存

Minimum viable fixture set for this task: `comments.csv`.

## Cross-links

- Depends on: 无（独立任务，仅需 comments 表）
- Feeds: [hypothesis_knowledge_base](./hypothesis_knowledge_base.md) (hypothesis.py 使用 theme="comment_demand" 生成假设种子)
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
