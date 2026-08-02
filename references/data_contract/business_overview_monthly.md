# business_overview_monthly

- **Grain / Primary Key:** `period_month` (`YYYY-MM`) — one row per calendar month represented in `business_overview_daily`.
- **Source:** derived from `business_overview_daily`; never imported directly.
- **Additive totals:** `gmv`, `paid_orders`, `paid_units`, `refund_amount_pay`, `net_gmv_pay`.
- **Daily-distinct person-days:** `paid_buyer_days`, `product_visitor_days`. These are sums of daily-distinct counts, not monthly unique people.
- **Daily averages:** `avg_daily_paid_buyers`, `avg_daily_product_visitors`, `avg_daily_aov`.
- **Recomputed ratio:** `refund_rate_pay = SUM(refund_amount_pay) / SUM(gmv)`.
- **Forbidden aliases:** do not expose `paid_buyers` or `product_visitors` at monthly grain unless a genuine period-deduplicated source is added.
- **Attribution limit:** this mart cannot support a period-level traffic × conversion × AOV bridge because it contains no period-unique visitors or buyers.
