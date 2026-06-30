## Metrics

Metrics must be defined in `references/metric_definitions.md`.

Core content metrics:

- `read_rate = reads / impressions`, only when impressions exist.
- `like_rate = likes / reads`.
- `collect_rate = collects / reads`.
- `comment_rate = comments / reads`.
- `share_rate = shares / reads`.
- `engagement_rate = (likes + collects + comments + shares) / reads`.
- `follower_conversion = followers_gained / reads`.

Core sales metrics:

- `units`
- `gmv`
- `order_count`
- `average_order_value`
- `sku_daily_units`
- `sku_daily_gmv`

Weak lift metrics:

- `baseline_units`: expected units from pre-period or model baseline.
- `observed_units`: units in post window.
- `absolute_lift = observed_units - baseline_units`.
- `relative_lift = observed_units / baseline_units - 1`.
- `z_score` or model residual score.
- `window`: 0-24h, 1-3d, 4-7d, 7-14d.

Portfolio metrics:

- `content_efficiency = reads or collects per post`.
- `sales_response = SKU lift or sales residual after publish`.
- `content_sales_alignment`: whether high attention coincides with sales response.
- `fatigue_signal`: declining response under similar repeated content.

All divide-by-zero cases must return null in machine outputs and "not enough denominator data" in reports.
