# shop_page_funnel

- **Grain / Primary Key:** (`date`, `audience_type`, `first_purchase_cycle`) — one row per day per audience type per first-purchase cycle.
- **Source file:** `8.店铺页转化漏斗`.
- **Required:** `shop_visitors, shop_payers, first_purchase_cycle`.
- **Optional:** `date, audience_type, product_click_users, visit_click_rate, click_pay_rate, visit_pay_rate`.
- **Chinese aliases:** see `FIELD_ALIASES["shop_page_funnel"]` in `importing/mapping.py`.
