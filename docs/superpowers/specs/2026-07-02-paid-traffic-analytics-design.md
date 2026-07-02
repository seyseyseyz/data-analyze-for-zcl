# Xiaohongshu Paid Traffic Analytics Design

## Background

The current `xiaohongshu-ceramics-analytics` implementation is built around a fixed local data contract, DuckDB import, analysis tasks, and Markdown/HTML reports. It already handles content performance, SKU sales response, product opportunities, content portfolio decisions, and weekly business review.

The missing capability is paid traffic analysis for Xiaohongshu effect-ad data from platforms such as 聚光, 薯条, or merchant backend exports. These exports usually include spend, impressions, clicks, conversions, GMV, and plan or creative identifiers, but the exact export grain is uncertain. The first design must therefore accept common grains without pretending every row can be attributed to a note or SKU.

## Goals

- Add first-class support for effect-ad performance exports.
- Keep the design compatible with uncertain backend export grains.
- Reuse the current build, DuckDB, task registry, evidence, and report architecture.
- Produce operator-readable recommendations about budget efficiency, inefficient spend, and next-week allocation.
- Avoid over-claiming attribution when the export cannot link to `note_id`, `sku_id`, or orders.

## Non-Goals

- Do not implement 蒲公英达人合作 analysis in this first version.
- Do not build a complete ad-platform warehouse with every campaign, ad group, creative, and attribution event as separate required dimensions.
- Do not require browser automation or live Xiaohongshu backend access.
- Do not infer paid attribution from order timing alone when no paid traffic identifier or business metric exists.
- Do not replace the existing content and SKU response tasks.

## Current Architecture Fit

The new capability should follow the existing pipeline:

1. `xhs-ca build <files>` profiles CSV or Excel exports.
2. `importing.mapping` guesses a table type and normalizes known columns.
3. `db.build` writes DuckDB tables and derived marts.
4. `analysis.registry` exposes task IDs.
5. Analysis modules return `AnalysisResult` and `Finding`.
6. Markdown and HTML renderers display findings, tables, caveats, and recommended actions.

This design adds a new standard table and new analysis tasks instead of introducing a parallel reporting path.

## Standard Table

Add one flexible fact table:

```text
ad_performance_daily
```

One row represents paid traffic performance at the most detailed grain available in the export. Common grains include:

- date x campaign
- date x ad unit
- date x creative or promoted note
- date x product or SKU
- date x mixed backend row where only names are available

Required fields:

- `date`
- `platform_source`
- `spend`

Recommended performance fields:

- `impressions`
- `clicks`
- `ctr`
- `cpc`
- `cpm`
- `conversions_optional`
- `orders_optional`
- `gmv_optional`
- `roi_optional`
- `roas_optional`

Optional identifiers:

- `campaign_id_optional`
- `campaign_name_optional`
- `unit_id_optional`
- `unit_name_optional`
- `creative_id_optional`
- `creative_name_optional`
- `note_id_optional`
- `note_url_optional`
- `product_id_optional`
- `sku_id_optional`

Optional raw trace fields:

- `raw_file`
- `raw_row_id`
- `raw_grain_hint`

## Import And Mapping

Add `ad_performance_daily` to `TABLE_SIGNATURES`.

Suggested signature:

```python
{
    "date",
    "spend",
    "impressions",
    "clicks",
    "campaign_name_optional",
}
```

Add field aliases for Chinese exports. Initial aliases should include:

```text
date: 日期, 时间, 投放日期, 数据日期
platform_source: 平台, 来源, 投放平台
campaign_id_optional: 计划ID, 计划id, 推广计划ID
campaign_name_optional: 计划名称, 推广计划, 投放计划
unit_id_optional: 单元ID, 广告单元ID
unit_name_optional: 单元名称, 广告单元
creative_id_optional: 创意ID, 素材ID
creative_name_optional: 创意名称, 素材名称, 笔记标题
note_id_optional: 笔记ID, 笔记id
note_url_optional: 笔记链接, 推广链接, 落地页链接
product_id_optional: 商品ID, 商品id
sku_id_optional: SKU ID, sku_id, 规格ID
spend: 消耗, 花费, 广告消耗, 投放消耗
impressions: 曝光, 展现, 展现量, 曝光量
clicks: 点击, 点击量
ctr: 点击率, CTR
cpc: 平均点击成本, CPC
cpm: 千次曝光成本, CPM
conversions_optional: 转化数, 成交人数, 转化人数
orders_optional: 成交订单数, 订单数, 支付订单数
gmv_optional: 成交金额, GMV, 支付金额
roi_optional: ROI, 投产比
roas_optional: ROAS, 广告投产比
```

Unknown source columns should continue to be preserved with safe column names, matching current import behavior.

## Derived Metrics

Add a derived view:

```text
ad_metrics
```

The view should compute missing rate metrics when denominators exist:

- `ctr_calc = clicks / impressions`
- `cpc_calc = spend / clicks`
- `cpm_calc = spend / impressions * 1000`
- `cvr_calc = conversions_optional / clicks`
- `cost_per_order_calc = spend / orders_optional`
- `roas_calc = gmv_optional / spend`

If the export already includes `ctr`, `cpc`, `cpm`, `roi`, or `roas`, keep both raw and calculated values. Reports should prefer calculated values when the underlying numerator and denominator are available, because formulas are easier to audit.

All divide-by-zero cases return null in machine outputs and reader-friendly "分母不足" language in reports.

## New Tasks

### `ad_data_quality_check`

Purpose: tell the operator whether the paid traffic export is usable and what it can support.

Inputs:

- required: `ad_performance_daily`
- optional: `notes`, `skus`, `products`, `orders`, `daily_sku_sales`

Outputs:

- detected row count
- date range
- total spend
- available metric groups: exposure, click, conversion, GMV
- detected grain: campaign, unit, creative, note, product, SKU, or unknown
- link coverage: percent of rows with note, SKU, product, campaign, or creative identifiers
- missing field limitations
- recommended next import action

Example recommendation:

```text
当前投放表能做计划级消耗和点击效率分析，但缺少 GMV/订单字段，不能判断投产。下一次导出请勾选成交金额、成交订单数或 ROI 字段。
```

### `paid_traffic_efficiency`

Purpose: evaluate paid traffic spend efficiency and produce budget recommendations.

Inputs:

- required: `ad_performance_daily`
- optional: `notes`, `skus`, `products`, `daily_sku_sales`, `note_sku_links`

Outputs:

- total spend, impressions, clicks, GMV, ROAS
- campaign or creative rows ranked by spend and ROAS
- high-spend low-return candidates
- low-spend high-signal candidates
- rows with strong click efficiency but weak conversion
- rows with weak click efficiency but meaningful conversion
- next-week budget action: increase, hold, reduce, or needs-data

Recommended action logic should be conservative:

- Increase budget only when spend is non-trivial, ROAS or GMV is available, and the row is not an isolated one-day result.
- Hold budget when click quality is good but conversion or GMV is missing.
- Reduce or pause when spend is high and clicks, conversions, or GMV are weak.
- Mark as needs-data when the export lacks spend, click, or conversion denominators.

## Linkage Rules

The analysis should not force attribution. Use the strongest available link:

1. `note_id_optional` or normalized `note_url_optional` links paid traffic to `notes`.
2. `sku_id_optional` links paid traffic to `skus` and `daily_sku_sales`.
3. `product_id_optional` links paid traffic to `products`.
4. Campaign, unit, or creative IDs support paid-platform-only analysis.
5. Names can be displayed but should not be used as strong joins unless manually confirmed later.

The first version does not need a separate `ad_note_links` table. If future exports are too messy for direct IDs, add a manual link table later instead of hiding fuzzy joins inside the task.

## Evidence Strength

Use the existing `EvidenceStrength` model.

- Strong: multiple days, spend and GMV available, identifiers are stable, and the pattern repeats across campaigns or creatives.
- Medium: spend and click/conversion data are available, but GMV or SKU linkage is partial.
- Weak: only exposure/click metrics exist, identifiers are names, or the signal appears on one day.
- Not judgable: spend is missing, the table cannot be recognized, or denominators are incompatible.

Reports must separate "投放效率" from "内容/商品因果影响". Paid data can support budget decisions, but it should not claim a note caused sales unless the export provides a credible attribution field.

## Report Changes

Add paid traffic fields to reporting labels:

- `spend`: 投放消耗
- `impressions`: 曝光量
- `clicks`: 点击量
- `ctr_calc`: 点击率
- `cpc_calc`: 点击成本
- `cpm_calc`: 千次曝光成本
- `orders_optional`: 成交订单数
- `gmv_optional`: 成交金额
- `roas_calc`: 投产比
- `budget_action`: 预算动作

HTML and Markdown reports should show:

- a concise paid traffic summary
- top efficient rows
- inefficient spend rows
- missing data caveats
- next import suggestion when evidence is weak

## CLI And Task Menu

Keep the public command shape unchanged:

```bash
xhs-ca build <exports...>
xhs-ca run ad_data_quality_check
xhs-ca run paid_traffic_efficiency
xhs-ca run all
```

Add task menu rows:

```text
看投放数据能不能分析 -> ad_data_quality_check
看投放消耗和投产效率 -> paid_traffic_efficiency
```

`all` should include both tasks after the core data quality task, but reports should tolerate missing `ad_performance_daily`.

## Testing Strategy

Add focused tests for:

- table type detection for Chinese ad exports
- field mapping for spend, impressions, clicks, GMV, ROAS, campaign name, creative name, note ID, and SKU ID
- DuckDB build preserving unknown ad export columns
- `ad_metrics` null-safe metric calculations
- `ad_data_quality_check` missing-data messaging
- `paid_traffic_efficiency` budget action classification
- report rendering of paid traffic labels and caveats
- `all` still succeeds when no ad table exists

Fixtures should include at least:

- campaign-level export with spend, impressions, clicks, GMV
- creative-level export with note ID or note URL
- weak export with spend and impressions only

## Rollout Plan

1. Extend data contract and metric definitions.
2. Add table signature and aliases.
3. Add normalization support for numeric ad fields where needed.
4. Add `ad_metrics` derived view.
5. Implement `ad_data_quality_check`.
6. Implement `paid_traffic_efficiency`.
7. Register tasks and task templates.
8. Update Markdown and HTML field labels.
9. Add fixtures and regression tests.
10. Sync bundled skill assets after source changes.

## First-Version Boundary

The first version should be useful even when the export only has campaign-level rows. The output should answer:

- Can this paid traffic export be analyzed?
- How much was spent?
- Which rows are efficient or inefficient?
- Do we have enough evidence to recommend increasing, holding, or reducing budget?
- What should be exported next to make the conclusion stronger?

It should not attempt a full multi-touch attribution model.
