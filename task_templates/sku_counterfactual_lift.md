# sku_counterfactual_lift

**Slug**: `sku_counterfactual_lift`  |  **Module**: `xhs_ceramics_analytics/analysis/sku_lift.py`  |  **Registry**: registry.py:32

## Purpose

本任务以笔记发布时间为锚点，在发布前后的固定时间窗口内观测关联 SKU 的销量变化（lift）。输出为描述性统计窗口数据，用于辅助判断笔记发布与销量波动之间是否存在方向性关联。

本任务不做因果推断——不含对照组逻辑（has_controls 始终为 False），因此证据强度上限为 WEAK。也不处理季节性、价格变动、缺货或其他营销活动的干扰因素。

## Required tables & fields

- `daily_sku_sales` (required) — key columns: `date`, `sku_id`, `units`
  派生表，由 db/build.py create_daily_sku_sales() 基于 orders 表聚合生成。
  上游 orders 导出列名: 支付时间 -> paid_time, 规格id -> sku_id, 商品数量 -> quantity, 支付金额 -> paid_amount

- `notes` (required) — key columns: `note_id`, `publish_time`
  Chinese header hints: 笔记id -> note_id, 发布时间/笔记发布时间 -> publish_time

- `note_sku_links` (optional) — key columns: `note_id`, `sku_id`
  无 FIELD_ALIASES 条目，需以英文列名导入。存在时使用显式归因路径 (confounder_count=1)。

- `skus` (optional) — key columns: `sku_id`
  Chinese header hints: 规格id -> sku_id
  仅当 note_sku_links 不可用时参与候选兜底 (CROSS JOIN first SKU)。

## Method

1. 打开 DuckDB 连接，检查 daily_sku_sales 表是否存在且包含 {date, sku_id, units}；缺失则返回 NOT_JUDGABLE。(L303-310)
2. 解析 note-SKU 关联来源：优先使用 note_sku_links INNER JOIN notes（取 publish_time）；否则用 notes 前 25 条 CROSS JOIN skus 首条 SKU 的候选兜底；均不可用则返回 NOT_JUDGABLE。(L217-300)
3. 为每组 (note_id, sku_id, publish_time) CROSS JOIN 四组固定窗口规格，LEFT JOIN daily_sku_sales 按 sku_id（VARCHAR cast）匹配。(L102-163)
4. 按窗口对 units 分别聚合 pre_units 和 post_units；同时统计 matched_sales_days 用于判断数据完整性。(L124-157)
5. 计算 absolute_lift 和 relative_lift；结果按 note_id, sku_id, 窗口顺序排列。(L164-187)
6. 若无结果行或所有行 matched_sales_days == 0，返回 NOT_JUDGABLE。(L52-65)
7. 去除内部列 matched_sales_days，调用 score_evidence 评估证据强度，生成 Finding 并返回 AnalysisResult。(L66-99)

## Key formulas

- `pre_units = COALESCE(SUM(units WHERE date IN [publish_date + pre_start_day, publish_date + pre_end_day)), 0.0)` (sku_lift.py:124-134)
- `post_units = COALESCE(SUM(units WHERE date IN [publish_date + post_start_day, publish_date + post_end_day)), 0.0)` (sku_lift.py:135-145)
- `matched_sales_days = COUNT(DISTINCT date IF date falls in pre OR post interval)` (sku_lift.py:146-157)
- `absolute_lift = post_units - pre_units` (sku_lift.py:172)
- `relative_lift = (post_units - pre_units) / pre_units WHEN pre_units > 0 ELSE NULL` (sku_lift.py:173-175)
- Window specs (day offsets): d0_1:[pre=-1..0, post=0..1); d1_3:[pre=-3..0, post=1..4); d4_7:[pre=-4..0, post=4..8); d8_14:[pre=-7..0, post=8..15) (sku_lift.py:7-12)
- `sample_size = |{(note_id, sku_id) distinct pairs}|` (sku_lift.py:68-69)
- `confounder_count = 1 if source == 'note_sku_links' else 3` (sku_lift.py:71)

## Thresholds & evidence

| 条件 | 证据强度 | 代码位置 |
|------|---------|---------|
| has_controls=False (本任务硬编码)，任何 sample_size | WEAK | evidence.py:20; sku_lift.py:70 |
| daily_sku_sales 缺失或缺少 {date, sku_id, units} | NOT_JUDGABLE | sku_lift.py:303-310 |
| note_sku_links 存在但缺 note_id/sku_id，或 notes 缺 publish_time | NOT_JUDGABLE | sku_lift.py:242-253 |
| 无 note_sku_links 且 notes/skus 不足以兜底 | NOT_JUDGABLE | sku_lift.py:255-300 |
| 产出行的 matched_sales_days 全为 0 | NOT_JUDGABLE | sku_lift.py:60-65 |

注意：由于 has_controls 始终为 False，STRONG 和 MEDIUM 在本任务中不可达。

## Output

- Result frame `sku_lift`: columns `note_id`, `sku_id`, `publish_time`, `window`, `pre_units`, `post_units`, `absolute_lift`, `relative_lift`
  - `window`: d0_1 / d1_3 / d4_7 / d8_14 四种标签
  - `relative_lift`: pre_units 为 0 时为 NULL

- Finding:
  - title: "笔记锚定的 SKU 销量响应窗口"
  - evidence_strength: WEAK (最高可达)
  - caveats: 始终包含 "观测到的销量变化只是笔记关联销售窗口的描述性结果，不能证明因果。"；候选兜底时额外附加 "缺少显式 note_sku_links 表，笔记到 SKU 的匹配使用首个 SKU 候选兜底，归因较弱。"
  - recommended_action: "先把这些结果当作弱方向信号；如果要做更强归因，需要补充显式 note-SKU 关联或留出对照逻辑。"

## Sample output section

```markdown
## SKU 销量响应

限制：
- 销量响应窗口是观测性结果，仍会受到季节性、价格、缺货和重叠营销活动影响。

### 笔记锚定的 SKU 销量响应窗口

已基于笔记发布时间，为 3 组 note-SKU 关联生成发布前后的销量观察窗口。

证据强度：弱

关键数字：
- `note_sku_links`: 3
- `windows`: 12
- `link_source`: candidate_first_sku
- `first_d8_14_post_units`: 18.0
- `first_d8_14_absolute_lift`: 11.0

注意事项：
- 观测到的销量变化只是笔记关联销售窗口的描述性结果，不能证明因果。
- 缺少显式 note_sku_links 表，笔记到 SKU 的匹配使用首个 SKU 候选兜底，归因较弱。

| note_id | sku_id | publish_time | window | pre_units | post_units | absolute_lift | relative_lift |
|---------|--------|--------------|--------|-----------|------------|---------------|---------------|
| n_20250601 | 8123 | 2025-06-01 10:30:00 | d0_1 | 3.0 | 5.0 | 2.0 | 0.667 |
| n_20250601 | 8123 | 2025-06-01 10:30:00 | d1_3 | 9.0 | 14.0 | 5.0 | 0.556 |
| n_20250601 | 8123 | 2025-06-01 10:30:00 | d4_7 | 12.0 | 16.0 | 4.0 | 0.333 |
| n_20250601 | 8123 | 2025-06-01 10:30:00 | d8_14 | 7.0 | 18.0 | 11.0 | 1.571 |
```

## Common failure modes

- daily_sku_sales 表完全缺失 -> 返回 NOT_JUDGABLE，recommended_action 提示先导入该表 -> 补充含 date/sku_id/units 的日销售数据
- daily_sku_sales 存在但缺字段 (如缺 units) -> 返回 NOT_JUDGABLE 并列出缺失字段名 -> 检查导出配置是否包含商品数量列
- note_sku_links 存在但列不全 -> 返回 NOT_JUDGABLE -> 确认导入时 note_id/sku_id 列名正确
- 候选兜底路径中 notes 缺少 publish_time -> 返回 NOT_JUDGABLE -> 确认笔记导出包含发布时间
- 窗口计算产出行但 matched_sales_days 全为 0（销售日期范围与笔记发布日期无交集）-> 返回 NOT_JUDGABLE -> 补齐观察窗口覆盖期间的日销售记录
- pre_units == 0 -> relative_lift 为 NULL，absolute_lift 仍正常计算 -> 业务上可能意味着新品首发或数据缺失
- units 含非数值 -> DuckDB CAST(units AS DOUBLE) 抛出错误，无 Python 端 NaN 防护 -> 确认源数据清洗

## Fixtures

- `tests/fixtures/orders.csv` — order_id, paid_time, sku_id, quantity, paid_amount (feeds derived daily_sku_sales)
- `tests/fixtures/notes.csv` — note_id, publish_time, ... (provides publish_time anchor)
- `tests/fixtures/skus.csv` — sku_id, product_id, sku_name, price, ... (enables candidate_first_sku fallback)

Minimum viable fixture set for this task: orders.csv, notes.csv, skus.csv.

注意：当前 fixture 集仅覆盖 candidate_first_sku 兜底路径；显式 note_sku_links 路径的覆盖在回归测试中通过 CREATE TABLE + INSERT 实现。

## Cross-links

- Depends on: [content_response_curve](./content_response_curve.md) (共享相同的 daily_sku_sales 派生表和类似的窗口逻辑)
- Feeds: [weekly_business_review](./weekly_business_review.md) (lift 数据可作为周报 SKU 维度的输入信号)
- Reference: [../references/data_contract.md](../references/data_contract.md), [../references/evidence_strength.md](../references/evidence_strength.md)
