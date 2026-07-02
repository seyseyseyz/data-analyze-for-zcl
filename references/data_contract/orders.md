# orders

One row per order line or SKU line. Order-level exports must be exploded into order lines when SKU lists are nested.

## Primary Key

(`order_id`, `sku_id`)

## Required Columns

| Column | Type | Description |
|--------|------|-------------|
| `order_id` | str (non-empty, stripped) | Order identifier |
| `sku_id` | str (non-empty, stripped) | SKU identifier for the order line |
| `quantity` | int > 0 | Positive integer quantity (default 1); rejects zero/negative/non-integer/bool |

## Optional Columns

| Column | Type | Description |
|--------|------|-------------|
| `paid_time` | datetime \| None | Timestamp when the order was paid |
| `paid_amount` | float >= 0, finite \| None | Paid amount in currency units (non-negative, finite) |
| `refund_status_optional` | str \| None | Optional refund status label |
| `buyer_id_hash` | str \| None | Hashed buyer identifier |
| `order_status` | str \| None | Order status |
| `channel_field_raw` | str \| None | Raw channel field (do not assume it maps to a note) |

## Join Keys

- `sku_id` references `skus.sku_id` (many-to-one, required)
- A single `order_id` may repeat across multiple `sku_id` rows

## Chinese Aliases (from mapping.py FIELD_ALIASES)

| English Column | Chinese Aliases |
|----------------|-----------------|
| `order_id` | 订单号, 订单编号, 订单id |
| `paid_time` | 支付时间, 付款时间, 成交时间 |
| `sku_id` | 规格id, sku id, skuid |
| `quantity` | 商品数量, 购买数量, 数量 |
| `paid_amount` | 支付金额, 实付金额, 成交金额, 订单金额 |
| `refund_status_optional` | 退款状态, 售后状态 |

## Sample Row

```json
{"order_id": "O001", "paid_time": "2025-01-16T12:34:56", "sku_id": "S001", "quantity": 1, "paid_amount": 129.0, "refund_status_optional": null}
```
