---
name: xiaohongshu-ceramics-analytics
description: Use when analyzing exported Xiaohongshu content, cover, product, SKU, order, comment, or experiment data for a ceramics ecommerce account. Produces evidence-scored local reports and weekly experiment matrices.
---

# Xiaohongshu Ceramics Analytics

Use this skill for local Xiaohongshu ceramics ecommerce analysis.

## Workflow

1. Ask the user for exported CSV files and any cover image folders they want to reference.
2. Let the local importer profile CSV headers and apply the closest standard table mapping.
3. Build the local DuckDB database under `.xhs-ceramics-analytics/`.
4. Run the requested task, or run `all` for the full V1 report menu.
5. Present conclusions with evidence strength, caveats, and next actions.

## Commands

```bash
xhs-ca build path/to/notes.csv path/to/orders.csv path/to/skus.csv
xhs-ca run all
xhs-ca run sku_counterfactual_lift
```

## Rules

- Do not claim deterministic note-to-order attribution unless explicit source data supports it.
- If data is missing, produce a limitation report and next-data-needed list.
- Prefer DuckDB and upstream analytics workflows over custom one-off scripts.
