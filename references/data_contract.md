## Standard Data Contract

The user may provide messy exports. The skill normalizes them into the following standard tables.

### `notes`

One row per Xiaohongshu note.

Core fields, with graceful degradation if the source export lacks them:

- `note_id`
- `publish_time`
- `title`
- `body`
- `note_type`
- `cover_image_path`
- `impressions`
- `reads`
- `likes`
- `collects`
- `comments`
- `shares`
- `followers_gained`

Optional:

- `author_account`
- `topic_tags`
- `post_status`
- `platform_url`
- `raw_file`
- `raw_row_id`

### `products`

One row per product.

- `product_id`
- `product_name`
- `category`
- `vessel_type`
- `series`
- `color_family`
- `pattern_style`
- `price_band`
- `launch_date`
- `status`

Optional:

- `margin_band`
- `inventory_strategy`
- `product_page_url`

### `skus`

One row per SKU.

- `sku_id`
- `product_id`
- `sku_name`
- `price`
- `inventory_optional`
- `cost_optional`

### `orders`

One row per order line or SKU line. Order-level exports must be exploded into order lines when SKU lists are nested.

- `order_id`
- `paid_time`
- `sku_id`
- `quantity`
- `paid_amount`
- `refund_status_optional`

Optional:

- `buyer_id_hash`
- `order_status`
- `channel_field_raw`

The design must not assume `channel_field_raw` can map to a Xiaohongshu note.

### `daily_sku_sales`

Derived from orders or imported directly.

- `date`
- `sku_id`
- `units`
- `gmv`
- `order_count`

### `note_sku_links`

Links notes to candidate products or SKUs.

- `note_id`
- `sku_id`
- `link_type`
- `confidence`
- `evidence`

Allowed `link_type` values:

- `explicit`: source file provides the relationship.
- `manual`: user confirms the relationship.
- `inferred`: title, body, SKU name, product name, image filename, publish plan, or timing suggests a relationship.

### `content_features`

One row per note, optionally split into cover and copy feature groups. If cover and copy features are split into separate files, each row still carries `note_id`.

- `note_id`

Cover features:

- `vessel_type_visible`
- `composition_type`
- `product_area_ratio_band`
- `shooting_angle`
- `background_material`
- `lighting_style`
- `color_temperature`
- `saturation_band`
- `contrast_band`
- `scene_hint`
- `human_hand_visible`
- `food_drink_visible`
- `text_overlay_present`
- `text_overlay_length_band`
- `aesthetic_semantics`

Copy features:

- `copy_angle`
- `purchase_motive`
- `craft_terms_present`
- `scene_terms_present`
- `gift_terms_present`
- `scarcity_terms_present`
- `price_explanation_present`
- `title_length_band`
- `specific_noun_density_band`
- `emotional_intensity_band`
- `call_to_action_type`

### `comments`

One row per comment when comment-level exports are available.

- `note_id`
- `comment_time`
- `comment_text`

Optional:

- `comment_id`
- `parent_comment_id`
- `comment_like_count`
- `author_id_hash`
- `raw_file`
- `raw_row_id`

### `calendar_events`

One row per date/event.

- `date`
- `event_type`
- `event_name`
- `affected_sku_id_optional`
- `affected_product_id_optional`
- `severity`
- `notes`

Examples:

- new product launch
- promotion
- holiday
- stockout
- restock
- shipping disruption
- platform campaign

### `experiments`

One row per planned or completed test cell.

- `experiment_id`
- `week`
- `hypothesis`
- `planned_publish_time`
- `note_id_optional`
- `sku_id`
- `controlled_variables`
- `changed_variable`
- `success_metric`
- `decision_rule`
- `status`
- `result_summary`

### `hypotheses`

Persistent knowledge base.

- `hypothesis_id`
- `statement`
- `status`
- `evidence_strength`
- `supporting_runs`
- `contradicting_runs`
- `next_test`
- `last_updated`
