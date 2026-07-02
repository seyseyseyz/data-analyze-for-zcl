# paid_traffic_efficiency

**Slug**: `paid_traffic_efficiency`  |  **Module**: `xhs_ceramics_analytics/analysis/paid_traffic.py`  |  **Registry**: registry.py:29

## Purpose

回答"投放预算该怎么调"这个问题：对聚光/薯条/商家后台导出的日维度投放数据做分组聚合，产出每组的消耗、点击效率和投产比（ROAS），并给出预算动作标签（increase/reduce/hold/needs_data）。本任务不做因果推断，不判断投放对内容自然流量的溢出效应，也不拆分投放内各转化环节归因。

## Required tables & fields

- `ad_performance_daily` (required) — key columns: `date`, `spend`, `impressions`, `clicks`, `gmv_optional`
  - Chinese header hints: `日期/投放日期/数据日期 -> date`, `消耗/花费/广告消耗 -> spend`, `曝光/曝光量/展现量 -> impressions`, `点击/点击量 -> clicks`, `成交金额/GMV/支付金额 -> gmv_optional`
  - Optional dimension columns: `campaign_name_optional`(计划名称), `creative_name_optional`(创意名称/素材名称), `note_id_optional`(笔记ID), `sku_id_optional`(SKU ID), `platform_source`(投放平台)
- `ad_metrics` (optional, drop-in override) — same schema as `ad_performance_daily`; if present,优先作为 SQL 查询源 (paid_traffic.py:48)

## Method

1. 打开 DuckDB 连接；如果 `ad_performance_daily` 表不存在，立即返回 NOT_JUDGABLE 并带 limitation (paid_traffic.py:46-47)。
2. 选择数据源：若 `ad_metrics` 表存在则用它，否则用 `ad_performance_daily` (paid_traffic.py:48)。
3. 通过 `PRAGMA table_info` 探测可用列；按优先级选择分组维度：campaign_name_optional > creative_name_optional > note_id_optional > sku_id_optional；若均不存在则尝试 platform_source；再不存在则全局聚合 (paid_traffic.py:98-114)。
4. 对选定维度执行一条聚合 SQL：计算 paid_active_days、spend、impressions、clicks、gmv_optional、roas_calc、ctr_calc、cpc_calc，按 roas_calc DESC / spend DESC 排序，LIMIT 20 (paid_traffic.py:121-144)。
5. 对每行调用 `classify_budget_action` 打上预算动作标签 (paid_traffic.py:53-60)。
6. 汇总 total_spend / total_gmv；根据 has_return 和总 paid_active_days 计算证据强度 (paid_traffic.py:62-69)。
7. 返回 AnalysisResult，含一个 Finding 和 `tables={'paid_traffic_efficiency': rows}` (paid_traffic.py:71-94)。

## Key formulas

- `paid_active_days = COUNT(DISTINCT CAST(date AS DATE)) per group`  (paid_traffic.py:125)
- `spend / impressions / clicks / gmv_optional = SUM(CAST(<col> AS DOUBLE))`, absent columns resolve to SQL `NULL`  (paid_traffic.py:126-129, sql_helpers.py:10-12)
- `roas_calc = SUM(gmv_optional) * 1.0 / SUM(spend)  WHEN SUM(spend) > 0 ELSE NULL`  (paid_traffic.py:130-132)
- `ctr_calc = SUM(clicks) * 1.0 / SUM(impressions)  WHEN SUM(impressions) > 0 ELSE NULL`  (paid_traffic.py:133-135)
- `cpc_calc = SUM(spend) * 1.0 / SUM(clicks)  WHEN SUM(clicks) > 0 ELSE NULL`  (paid_traffic.py:136-138)
- `evidence.sample_size = sum(row.paid_active_days for all rows)`  (paid_traffic.py:66)
- `evidence.confounder_count = 1 if has_return else 3`  (paid_traffic.py:68)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|----------|----------|
| `ad_performance_daily` 表缺失 | Not-judgable | paid_traffic.py:46-47 |
| sample_size >= 10 AND has_return AND confounder_count <= 1 | Medium | evidence.py:18-19 |
| 以上条件不满足 (has_return=False 或天数 <10) | Weak | evidence.py:20 |
| Strong (需 confounder_count=0) | 不可达 (paid_traffic 始终传 confounder_count>=1) | evidence.py:17 |

budget_action 判定阈值 (非证据强度，属行级标签):

| 条件 | 动作 | 代码位置 |
|------|------|----------|
| spend<=0 OR clicks=None OR gmv=None OR roas=None | needs_data | paid_traffic.py:22-25 |
| active_days < 2 AND roas >= 3 | hold | paid_traffic.py:26-27 |
| spend >= 100 AND roas >= 3 AND gmv > 0 | increase | paid_traffic.py:28-33 |
| spend >= 100 AND (clicks < 20 OR gmv <= 0 OR roas < 1) | reduce | paid_traffic.py:34-39 |
| otherwise | hold | paid_traffic.py:40 |

## Output

- Result frame `paid_traffic_efficiency`: 最多 20 行，含列 `[dimension columns]`, `paid_active_days`, `spend`, `impressions`, `clicks`, `gmv_optional`, `roas_calc`, `ctr_calc`, `cpc_calc`, `budget_action`
- Finding title: `投放消耗和投产效率已汇总`
- evidence_strength: Medium / Weak / Not-judgable
- caveats:
  - "投放效率来自后台导出，不等同于内容或商品的因果影响。" (always)
  - "缺少成交金额或投产字段，不能判断 ROAS。" (when has_return=False)
  - "部分对象只有单日数据，预算动作需要保守执行。" (when any paid_active_days<2)
- recommended_action: 根据 rows 中 increase/reduce 分布选择建议文案

## Sample output section

```markdown
## 投放效率分析

### 投放消耗和投产效率已汇总

已汇总 5 个投放对象，总消耗 2834.50，可见成交金额 9215.80。

证据强度：Medium

关键数字：
- `rows`: 5
- `spend`: 2834.50
- `gmv_optional`: 9215.80

注意事项：
- 投放效率来自后台导出，不等同于内容或商品的因果影响。
- 部分对象只有单日数据，预算动作需要保守执行。

建议动作：
优先小幅增加高投产对象预算，同时保留日级观察，避免只凭单日波动放量。

表格 `paid_traffic_efficiency`：5 行

| campaign_name_optional | paid_active_days | spend | impressions | clicks | gmv_optional | roas_calc | ctr_calc | cpc_calc | budget_action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 素白拉丝盖碗-精准 | 7 | 1200.00 | 48320 | 812 | 5400.00 | 4.5 | 0.0168 | 1.4778 | increase |
| 青釉杯投放 | 3 | 860.50 | 31200 | 423 | 2580.80 | 3.0 | 0.0136 | 2.0343 | hold |
| 柴烧壶-泛兴趣 | 5 | 534.00 | 22100 | 98 | 235.00 | 0.44 | 0.0044 | 5.449 | reduce |
```

## Common failure modes

- `ad_performance_daily` 表不存在 -> 返回 NOT_JUDGABLE，Finding title 变为"投放效率不可判断"，tables 为空列表。建议下一步：导入含日期/消耗/曝光或点击字段的投放导出。
- 表存在但无数据行 -> rows=[], sample_size=0, 证据 NOT_JUDGABLE；Finding conclusion 显示"已汇总 0 个投放对象"。建议：确认导出文件非空或日期筛选范围正确。
- 维度列全部缺失 -> 退化为全局聚合（一行结果），无法区分不同计划或创意的效率差异。建议：下次导出包含计划名称或创意名称列。
- 数值列缺失（如无 clicks） -> `numeric_expr` 返回 SQL `NULL`，SUM(NULL)=NULL；相关行 classify_budget_action 返回 needs_data。建议：补充点击量字段。
- paid_active_days < 2 且 roas 高 -> budget_action 强制为 hold 而非 increase，防止单日波动误判。

## Fixtures

- `tests/fixtures/ads_campaign.csv` — Campaign 粒度，含 GMV+ROAS，两天 '青釉杯投放' 数据
- `tests/fixtures/ads_creative.csv` — Creative 粒度，含 note_id_optional 和 sku_id_optional 维度
- `tests/fixtures/ads_weak.csv` — 最低信号：仅 date/campaign/spend/impressions，无 clicks，exercises needs_data path

Minimum viable fixture set for this task: ads_campaign.csv, ads_weak.csv.

## Cross-links

- Depends on: [ad_data_quality_check](./ad_data_quality_check.md) (该任务先检测投放表的可用性和字段完备性)
- Feeds: 无直接下游任务（结果作为报告独立章节）
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
