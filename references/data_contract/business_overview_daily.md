# business_overview_daily

- **Grain / Primary Key:** `date` (int `YYYYMMDD`) — one row per day.
- **Source files:** `1.核心数据汇总` (21 col) + `成交/经营概览-all` (58 col), merged on `date` (column-view coalesce).
- **Required:** `date, gmv, paid_orders, paid_buyers, aov`.
- **Optional:** channel split (`note_gmv/card_gmv`, `note_paid_orders/card_paid_orders`, buyers, visitors, conversion, AOV, net GMV, refund orders/rates and pre/post-ship rates), `product_visitors, paid_units, pay_conversion(_pv/_uv), add_to_cart_users/units, new_wishlist_users, net_gmv_pay, refund_amount_pay, refund_rate_pay, refund_orders_pay, pre_ship_refund_rate_pay, post_ship_refund_rate_pay, refund_amount_refundtime, total_visitors, total_pv, product_click_rate_pv, new_add_to_cart_users, refund_order_share_refundtime`.
- **Join keys:** `date` → `business_overview_monthly` (rolled up).
- **Chinese aliases:** see `FIELD_ALIASES["business_overview_daily"]` in `importing/mapping.py`.
- **Caliber:** amounts carry both `_pay` (支付时间) and `_refundtime` (退款时间); rates only `_pay`.
- **Distinct-user rule:** `paid_buyers`, `product_visitors`, `add_to_cart_users`, and `new_wishlist_users` are distinct only within each day. Never sum them and label the result as period-unique people. Across dates, report a daily average or an explicitly named person-day field such as `paid_buyer_days`.
- **Period attribution gate:** a month-level traffic × conversion × AOV bridge requires period-unique visitors/buyers or user-level IDs. Daily distinct counts are insufficient and must degrade rather than be summed.
