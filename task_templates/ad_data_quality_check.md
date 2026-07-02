# ad_data_quality_check

**Slug**: `ad_data_quality_check`  |  **Module**: `xhs_ceramics_analytics/analysis/ad_quality.py`  |  **Registry**: registry.py:28

## Purpose

判断小红书千帆投放后台导出的数据在当前数据库中是否可用、字段完整度如何、以及识别出的投放粒度。该任务只做结构检查和字段覆盖度诊断，不判断投放效果好坏，也不计算 ROI/ROAS 等业务指标。

## Required tables & fields

- `ad_performance_daily` (required) — key columns: `date`, `spend`
  - 中文导出列名提示: `日期/投放日期/数据日期 -> date`, `消耗/花费/广告消耗 -> spend`, `曝光量/展现量 -> impressions`, `点击量 -> clicks`, `成交金额/GMV -> gmv_optional`, `广告投产比/ROAS -> roas_optional`, `笔记ID -> note_id_optional`, `SKU ID -> sku_id_optional`, `计划名称 -> campaign_name_optional`, `创意名称 -> creative_name_optional`
  - 其余 optional 列 (unit_id_optional, product_id_optional, note_url_optional 等) 由代码按是否存在决定行为

注意: 当前模板历史上列出了 notes/skus/products/daily_sku_sales 为 optional，但代码从不查询这些表。link coverage 完全通过 ad_performance_daily 自身的 *_optional 列计算。

## Method

1. 打开 DuckDB 并检查 `ad_performance_daily` 表是否存在；不存在则返回 NOT_JUDGABLE 结果 (ad_quality.py:11-12)。
2. 通过 `PRAGMA table_info` 读取该表所有列名 (ad_quality.py:160-161)，后续据此决定哪些 SUM / COUNT 是安全的。
3. 执行聚合查询: `COUNT(*)`, `MIN/MAX(CAST(date AS DATE))`, `SUM(CAST(spend AS DOUBLE))` (ad_quality.py:56-65)。
4. 按优先级检测粒度: sku > product > note > creative > unit > campaign > unknown (ad_quality.py:85-98)。
5. 设置指标可用性布尔值: has_exposure_metrics / has_click_metrics / has_conversion_metrics / has_gmv_metrics (ad_quality.py:73-76)。
6. 对 note_id_optional / sku_id_optional / campaign_name_optional / creative_name_optional 执行 `COUNT(*) WHERE col IS NOT NULL` 得到 link coverage (ad_quality.py:126-132)。
7. 调用 `score_evidence(sample_size=rows, has_controls=has_gmv_metrics, confounder_count=1 if has_gmv else 2)` 评估证据强度 (ad_quality.py:20-24)。
8. 组装 Finding 并输出 caveats 和 recommended_action (ad_quality.py:26-50)。

## Key formulas

- `rows = COUNT(*) FROM ad_performance_daily`  (ad_quality.py:59)
- `total_spend = round(SUM(CAST(spend AS DOUBLE)), 4); NULL when spend column absent`  (ad_quality.py:62,71)
- `detected_grain = priority: sku_id_optional -> 'sku'; product_id_optional -> 'product'; note_id_optional|note_url_optional -> 'note'; creative_id_optional|creative_name_optional -> 'creative'; unit_id_optional|unit_name_optional -> 'unit'; campaign_id_optional|campaign_name_optional -> 'campaign'; else 'unknown'`  (ad_quality.py:85-98)
- `has_click_metrics = {'impressions','clicks'} <= columns`  (ad_quality.py:74)
- `has_gmv_metrics = {'gmv_optional','roi_optional','roas_optional'} & columns != empty`  (ad_quality.py:76)
- `evidence_strength = score_evidence(sample_size=n, has_controls=has_gmv_metrics, confounder_count=1 if has_gmv else 2)`  (ad_quality.py:20)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|----------|----------|
| ad_performance_daily 表不存在 | Not-judgable | ad_quality.py:144 |
| rows=0 或 confounder_count<0 | Not-judgable | evidence.py:14 |
| rows>=10 且 has_gmv_metrics=True (confounder_count=1) | Medium | evidence.py:18 |
| 其他 (has_gmv=False -> confounder_count=2, 或 rows<10) | Weak | evidence.py:20 |
| Strong 在此任务中不可达 (confounder_count 始终>=1) | Strong (unreachable) | evidence.py:16 |

## Output

- **Result frame** `ad_data_quality` (list, 0 or 1 row):
  - `rows`: 行数 (int)
  - `first_date` / `last_date`: 日期范围 (ISO str 或 None)
  - `total_spend`: 总消耗 (float, 4 位小数; None 若 spend 列缺失)
  - `detected_grain`: 粒度 {sku, product, note, creative, unit, campaign, unknown}
  - `has_exposure_metrics` / `has_click_metrics` / `has_conversion_metrics` / `has_gmv_metrics`: 布尔
  - `note_link_rows` / `sku_link_rows` / `campaign_link_rows` / `creative_link_rows`: 非空关联行数 (int)

- **Finding**: title=`投放导出已完成结构检查` (正常路径) 或 `投放数据不可判断` (缺表路径)
  - evidence_strength: Medium / Weak / Not-judgable
  - caveats: `缺少 GMV/ROI/ROAS 字段，不能判断投产。` / `缺少笔记或 SKU 关联，只能做投放平台侧效率分析。`
  - recommended_action: 按字段缺失情况给出下一步导出建议

## Sample output section

```markdown
## 投放数据可用性检查

### 投放导出已完成结构检查

当前投放表有 186 行，识别为 sku 粒度。

证据强度：中

关键数字：
- `rows`: 186
- `total_spend`: 8523.6700
- `detected_grain`: sku

注意事项：
- 缺少笔记或 SKU 关联，只能做投放平台侧效率分析。

建议动作：

当前投放导出可用于投放效率分析；后续可继续补充更细的创意或 SKU 维度。

表格 `ad_data_quality`：1 行

| rows | first_date | last_date | total_spend | detected_grain | has_exposure_metrics | has_click_metrics | has_conversion_metrics | has_gmv_metrics | note_link_rows | sku_link_rows | campaign_link_rows | creative_link_rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 186 | 2026-06-01 | 2026-06-28 | 8523.67 | sku | True | True | False | True | 0 | 186 | 186 | 186 |
```

## Common failure modes

- ad_performance_daily 表不存在 -> 返回 NOT_JUDGABLE，limitations=['缺少 ad_performance_daily 表。']，tables={'ad_data_quality': []}。建议补数据: 导入含日期+消耗+曝光/点击的投放导出。
- 表存在但为空 (rows=0) -> score_evidence 收到 sample_size=0 返回 NOT_JUDGABLE；first_date/last_date/total_spend 均为 None。
- spend 列缺失 -> _sum_expr 返回字面 'NULL'，DuckDB 返回 total_spend=None；不报错。
- *_optional link 列缺失 -> _non_null_count 短路返回 0，不执行 SQL。
- 无 click/GMV 列 -> has_click_metrics/has_gmv_metrics=False；caveats 增加相应提示；confounder_count=2 强制 WEAK 证据。
- spend 行含非数字字符串 -> `CAST(spend AS DOUBLE)` 在查询时抛出 DuckDB 类型错误。

## Fixtures

- `tests/fixtures/ads_campaign.csv` — campaign 粒度、完整指标 (has_click + has_gmv)
- `tests/fixtures/ads_creative.csv` — creative+SKU 粒度、带 note_id/sku_id 关联
- `tests/fixtures/ads_weak.csv` — 最简导出 (仅 spend+impressions)，触发 WEAK 证据路径

Minimum viable fixture set for this task: ads_campaign.csv, ads_creative.csv, ads_weak.csv.

## Cross-links

- Depends on: none (独立任务，不依赖其他任务输出)
- Feeds: [paid_traffic_efficiency](./paid_traffic_efficiency.md) (共用 ad_performance_daily 表；ad_data_quality_check 的粒度和字段诊断结果指导用户补数据后运行 paid_traffic_efficiency)
- Reference: [../references/evidence_strength.md](../references/evidence_strength.md), [../references/data_contract.md](../references/data_contract.md)
