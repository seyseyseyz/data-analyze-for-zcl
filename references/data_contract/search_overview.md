# search_overview

- **Grain / Primary Key:** (`date`, `carrier`) — one row per day per search carrier (载体).
- **Source file:** `7.搜索总览`.
- **Required:** `date, carrier, card_impression_users, product_click_rate, pay_conversion`.
- **Optional:** `gmv, paid_orders, paid_buyers, product_click_users`.
- **Chinese aliases:** see `FIELD_ALIASES["search_overview"]` in `importing/mapping.py`.
