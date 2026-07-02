# ad_performance_daily

One row per paid traffic performance record at the most detailed export grain available.

Paid exports may be campaign-level, unit-level, creative-level, note-level, product-level, or SKU-level. The analysis must not force note or SKU attribution when those identifiers are missing.

## Primary Key

(`date`, `platform_source`) + whichever granularity identifiers are present (campaign/unit/creative/note/product/SKU).

## Required Columns

| Column | Type | Description |
|--------|------|-------------|
| `date` | date | Reporting date |
| `platform_source` | str | Traffic platform source |
| `spend` | float | Ad spend amount |

## Recommended Columns

| Column | Type | Description |
|--------|------|-------------|
| `impressions` | int \| None | Impression count |
| `clicks` | int \| None | Click count |
| `ctr` | float \| None | Click-through rate |
| `cpc` | float \| None | Cost per click |
| `cpm` | float \| None | Cost per mille (thousand impressions) |
| `conversions_optional` | int \| None | Conversion count |
| `orders_optional` | int \| None | Order count |
| `gmv_optional` | float \| None | GMV from paid traffic |
| `roi_optional` | float \| None | ROI |
| `roas_optional` | float \| None | ROAS |

## Optional Identifiers

| Column | Type | Description |
|--------|------|-------------|
| `campaign_id_optional` | str \| None | Campaign ID |
| `campaign_name_optional` | str \| None | Campaign name |
| `unit_id_optional` | str \| None | Ad unit ID |
| `unit_name_optional` | str \| None | Ad unit name |
| `creative_id_optional` | str \| None | Creative ID |
| `creative_name_optional` | str \| None | Creative name |
| `note_id_optional` | str \| None | Note ID (if note-level grain) |
| `note_url_optional` | str \| None | Note URL |
| `product_id_optional` | str \| None | Product ID |
| `sku_id_optional` | str \| None | SKU ID |

## Join Keys

- `note_id_optional` references `notes.note_id` (when present)
- `product_id_optional` references `products.product_id` (when present)
- `sku_id_optional` references `skus.sku_id` (when present)

## Chinese Aliases (from mapping.py FIELD_ALIASES)

| English Column | Chinese Aliases |
|----------------|-----------------|
| `date` | 日期, 时间, 投放日期, 数据日期 |
| `platform_source` | 平台, 来源, 投放平台 |
| `campaign_id_optional` | 计划ID, 计划id, 推广计划ID |
| `campaign_name_optional` | 计划名称, 推广计划, 投放计划 |
| `unit_id_optional` | 单元ID, 广告单元ID |
| `unit_name_optional` | 单元名称, 广告单元 |
| `creative_id_optional` | 创意ID, 素材ID |
| `creative_name_optional` | 创意名称, 素材名称, 笔记标题 |
| `note_id_optional` | 笔记ID, 笔记id |
| `note_url_optional` | 笔记链接, 推广链接, 落地页链接 |
| `product_id_optional` | 商品ID, 商品id |
| `sku_id_optional` | SKU ID, sku_id, 规格ID |
| `spend` | 消耗, 花费, 广告消耗, 投放消耗 |
| `impressions` | 曝光, 展现, 展现量, 曝光量 |
| `clicks` | 点击, 点击量 |
| `ctr` | 点击率, CTR |
| `cpc` | 平均点击成本, CPC |
| `cpm` | 千次曝光成本, CPM |
| `conversions_optional` | 转化数, 成交人数, 转化人数 |
| `orders_optional` | 成交订单数, 订单数, 支付订单数 |
| `gmv_optional` | 成交金额, GMV, 支付金额 |
| `roi_optional` | ROI, 投产比 |
| `roas_optional` | ROAS, 广告投产比 |

## Sample Row

```json
{"date": "2025-01-16", "platform_source": "聚光", "spend": 200.0, "impressions": 5000, "clicks": 150, "ctr": 0.03, "cpc": 1.33, "cpm": 40.0, "conversions_optional": 5, "orders_optional": 3, "gmv_optional": 450.0, "roi_optional": 2.25, "roas_optional": 2.25, "campaign_name_optional": "春节杯子推广", "note_id_optional": "N001"}
```
