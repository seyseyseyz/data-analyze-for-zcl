# cover_style_effect

**Slug**: `cover_style_effect`  |  **Module**: `xhs_ceramics_analytics/analysis/cover_effect.py`  |  **Registry**: registry.py:34

## Purpose

按封面构图类型（composition_type）对笔记进行分组，统计每组平均阅读数和收藏数，输出排序后的描述性排名表。用于识别哪类封面风格在流量指标上表现更好。本任务不涉及 SKU 销量响应、因果归因或 A/B 测试设计——仅提供描述性排序，证据强度上限为 WEAK。

## Required tables & fields

- `content_features` (required) — key columns: `composition_type`, `note_id`
  Chinese header hints: 无中文别名定义于 mapping.py；TABLE_SIGNATURES 要求 {note_id, composition_type, scene_hint, copy_angle}。
- `notes` (optional) — key columns: `note_id`, `reads`, `collects`
  Chinese header hints: `笔记id/笔记ID → note_id`, `阅读次数/笔记阅读数/阅读数 → reads`, `收藏数/收藏次数 → collects`

## Method

1. 打开 DuckDB 连接（cover_effect.py:10）。
2. 守卫检查：若 content_features 表不存在，返回空行并附 limitation "缺少 content_features 表。"（L39-40）。
3. 内省 content_features 列；若缺少 composition_type 字段，返回空行并附 limitation（L42-44）。
4. 判断是否可 JOIN notes：需要 content_features.note_id、notes 表存在、且 notes.note_id 存在（L46-50）。
5. 回退路径（无法 JOIN）：按 composition_type 分组仅计算 COUNT(*)，avg_reads/avg_collects 置 NULL；按 notes DESC 排序；附 limitation "笔记指标不可用，封面排序仅使用特征计数。"（L51-65）。
6. JOIN 路径：LEFT JOIN notes on CAST(note_id AS VARCHAR)，计算 AVG(reads)、AVG(collects)；按 avg_reads DESC NULLS LAST, notes DESC, composition_type 排序（L67-84）。
7. 评分证据：若 rows 非空且存在非 NULL 的 avg_reads/avg_collects，调用 score_evidence(n=len(rows), has_controls=False, confounder_count=1)；否则 NOT_JUDGABLE（L16-20）。
8. 封装为 AnalysisResult，Finding 标题 "封面类型已排序"，tables={'cover_effects': rows}（L21-35）。

## Key formulas

- `avg_reads = AVG(CAST(n.reads AS DOUBLE))` grouped by composition_type  (cover_effect.py:68, 78)
- `avg_collects = AVG(CAST(n.collects AS DOUBLE))` grouped by composition_type  (cover_effect.py:69-71, 79)
- `notes = COUNT(*)` per composition_type group  (cover_effect.py:57, 77)
- `composition_type = COALESCE(NULLIF(TRIM(CAST(composition_type AS VARCHAR)), ''), 'unknown')`  (cover_effect.py:55-56, 75-76)
- JOIN path ordering: `ORDER BY avg_reads DESC NULLS LAST, notes DESC, composition_type`  (cover_effect.py:83)
- Fallback ordering: `ORDER BY notes DESC, composition_type`  (cover_effect.py:62)
- `evidence = score_evidence(sample_size=len(rows), has_controls=False, confounder_count=1)` — has_controls 固定 False，最高只能到 WEAK  (cover_effect.py:16-20; evidence.py:14-20)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|---------|---------|
| rows 为空 OR 无任何 avg_reads/avg_collects 非 NULL | NOT_JUDGABLE | cover_effect.py:16-20, L100-104 |
| sample_size<=0 OR confounder_count<0 | NOT_JUDGABLE | evidence.py:14-15 |
| has_controls=False（本任务硬编码），任何 n 值 | WEAK（最高可达） | evidence.py:20; cover_effect.py:17 |
| STRONG 需 has_controls=True + n>=30 + confounder_count==0 | Strong（本任务不可达） | evidence.py:16-17 |
| MEDIUM 需 has_controls=True + n>=10 + confounder_count<=1 | Medium（本任务不可达） | evidence.py:18-19 |

## Output

- Result frame `cover_effects`:
  - `composition_type` — 封面构图类型（VARCHAR），空值归为 'unknown'
  - `notes` — 该类型下 content_features 行数（COUNT(*)）
  - `avg_reads` — 关联笔记平均阅读数（DOUBLE）；回退路径或列缺失时为 NULL
  - `avg_collects` — 关联笔记平均收藏数（DOUBLE）；回退路径或列缺失时为 NULL

- Finding: title="封面类型已排序", evidence_strength=WEAK (最高), caveats=["在加入 SKU 和发布时间控制前，这个排序仍是描述性结果。"], key_numbers={cover_groups: n}

## Sample output section

```markdown
## 封面风格效果

### 封面类型已排序

已按平均阅读数和收藏数对封面构图类型进行排序。

证据强度：弱

关键数字：
- `cover_groups`: 4

注意事项：
- 在加入 SKU 和发布时间控制前，这个排序仍是描述性结果。

表格 `cover_effects`：4 行

| composition_type | notes | avg_reads | avg_collects |
| --- | --- | --- | --- |
| single_product | 12 | 1840.0 | 67.5 |
| gift_box | 8 | 1420.0 | 52.0 |
| table_setting | 6 | 980.0 | 31.2 |
| unknown | 3 | 540.0 | 18.0 |
```

## Common failure modes

- content_features 表缺失 → 返回空 cover_effects，evidence NOT_JUDGABLE，limitation "缺少 content_features 表。" → 确认数据导入是否包含内容特征文件。
- composition_type 字段缺失 → 返回空结果，limitation "content_features 表缺少 composition_type 字段。" → 检查导入映射或 CSV 列名。
- notes 表不存在或无 note_id → 回退到仅计数路径，avg_reads/avg_collects 全 NULL，evidence NOT_JUDGABLE → 补充 notes 数据导入。
- notes 表存在但缺 reads 或 collects 列 → 对应 avg 列输出 NULL，limitation "notes 表的阅读/收藏指标不完整。" → 检查笔记导出是否包含阅读/收藏字段。
- JOIN 后所有指标均为 NULL（note_id 不匹配等） → limitation "没有匹配的笔记指标，封面效果不可判断。"，evidence NOT_JUDGABLE → 检查 note_id 格式一致性（VARCHAR cast）。
- reads/collects 含非数字文本 → CAST AS DOUBLE 在 DuckDB SQL 执行时抛错（代码未显式捕获） → 预清洗数据或加 TRY_CAST。

## Fixtures

- `tests/fixtures/content_features.csv` (columns: note_id, composition_type, scene_hint, copy_angle, purchase_motive, text_overlay_present, aesthetic_semantics — 3 rows)
- `tests/fixtures/notes.csv` (columns include: note_id, reads, collects — 3 rows matching n1/n2/n3)

Minimum viable fixture set for this task: content_features.csv (含 composition_type), notes.csv (含 reads, collects)。

## Cross-links

- Depends on: 无直接上游任务依赖（独立读取 content_features + notes）
- Feeds: [product_content_interaction](./product_content_interaction.md)（该任务同样使用 content_features.composition_type，可结合本任务结果做交叉分析）
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
