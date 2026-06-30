# SKU Counterfactual Lift

## Purpose

Estimate whether linked SKU sales after note publication exceed expected baseline.

## Required Data

Uses notes, orders, daily_sku_sales, skus, note_sku_links when available, and calendar_events.

## Output Contract

Returns 0-24h, 1-3d, 4-7d, and 7-14d lift estimates with weak-attribution language and evidence strength.
