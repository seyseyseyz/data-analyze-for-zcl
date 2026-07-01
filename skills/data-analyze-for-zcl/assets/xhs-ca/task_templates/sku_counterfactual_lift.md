# SKU Sales Response

## Purpose

Compare linked SKU sales before and after note publication as a directional response signal.

## Required Data

Uses notes, orders, daily_sku_sales, skus, note_sku_links when available, and calendar_events.

## Output Contract

Returns 0-24h, 1-3d, 4-7d, and 7-14d sales windows with weak-attribution language and evidence strength.
