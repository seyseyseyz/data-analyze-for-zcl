# skus

One row per SKU.

## Primary Key

`sku_id`

## Required Columns

| Column | Type | Description |
|--------|------|-------------|
| `sku_id` | str (non-empty, stripped) | Unique SKU identifier |

## Optional Columns

| Column | Type | Description |
|--------|------|-------------|
| `product_id` | str \| None | Foreign key to products.product_id |
| `sku_name` | str \| None | SKU display name |
| `price` | float >= 0, finite \| None | SKU list price (non-negative, finite) |
| `inventory_optional` | int >= 0 \| None | Optional inventory count |
| `cost_optional` | float >= 0, finite \| None | Optional unit cost |

## Join Keys

- `product_id` references `products.product_id` (many-to-one, optional)
- `sku_id` is referenced by `orders.sku_id`, `note_sku_links.sku_id`, `daily_sku_sales.sku_id`, `calendar_events.affected_sku_id_optional`

## Chinese Aliases (from mapping.py FIELD_ALIASES)

| English Column | Chinese Aliases |
|----------------|-----------------|
| `sku_id` | 规格id, 规格ID, skuid |
| `product_id` | 商品id, 商品ID |
| `sku_name` | 规格名称, sku名称 |
| `price` | 价格, 售价, 销售价格, 规格价格 |
| `inventory_optional` | 库存, 可售库存 |

## Sample Row

```json
{"sku_id": "S001", "product_id": "P001", "sku_name": "example", "price": 129.0, "inventory_optional": null, "cost_optional": null}
```
