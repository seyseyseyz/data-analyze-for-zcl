# refund_overview

- **Grain / Primary Key:** (`stat_period`, `account_name`, `carrier`) — one row per stat period per account per carrier (载体).
- **Source file:** `6.退款分析概览`.
- **Required:** `carrier, pre_ship_refund_amount, return_refund_amount, refund_users`.
- **Optional:** `stat_period, account_type, account_name, refund_amount_pay, post_ship_refund_amount, shipped_refundonly_amount, refund_orders_pay, post_ship_refund_orders, shipped_refundonly_orders, pre_ship_refund_orders, return_refund_orders, refund_rate_pay, post_ship_refund_rate_pay, pre_ship_refund_rate_pay, return_refund_rate_pay`.
- **Chinese aliases:** see `FIELD_ALIASES["refund_overview"]` in `importing/mapping.py`.
- **Caliber:** amounts/orders/rates are all 支付时间 (pay-time) caliber; split by ship stage (`pre_ship_`/`post_ship_`) and by refund type (`return_refund_*` = 退货退款, `shipped_refundonly_*` = 发货后仅退款).
- **Note:** single-row period aggregate — feeds refund **structure** (stage/type split) analysis, not per-SKU attribution.
