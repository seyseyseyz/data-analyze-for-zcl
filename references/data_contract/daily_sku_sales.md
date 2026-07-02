# daily_sku_sales

Derived from orders or imported directly.

## Primary Key

(`date`, `sku_id`)

## Required Columns

| Column | Type | Description |
|--------|------|-------------|
| `date` | date | Calendar date |
| `sku_id` | str | SKU identifier |
| `units` | int | Units sold |
| `gmv` | float | Gross merchandise value |
| `order_count` | int | Number of orders |

## Optional Columns

None defined.

## Join Keys

- `sku_id` references `skus.sku_id`

## Chinese Aliases (from mapping.py FIELD_ALIASES)

No dedicated aliases for `daily_sku_sales` in FIELD_ALIASES (this table is typically derived from orders programmatically).

## Sample Row

```json
{"date": "2025-01-16", "sku_id": "S001", "units": 3, "gmv": 387.0, "order_count": 2}
```
