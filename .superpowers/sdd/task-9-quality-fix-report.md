# Task 9 Quality Fix Report

## Scope

- `xhs_ceramics_analytics/analysis/sku_lift.py`
- `xhs_ceramics_analytics/analysis/response_curve.py`
- `tests/test_task9_regressions.py`

## What Changed

- Removed hard-coded `n1` / `s1` / `2026-06-01` seed logic from `sku_lift`.
- Removed fixed `2026-06-01` calendar anchor from `response_curve`.
- Added guarded table/column checks so both tasks degrade to `AnalysisResult` with:
  - one `Finding`
  - `EvidenceStrength.NOT_JUDGABLE`
  - empty table payloads under the original keys
  - limitations, caveats, and recommended next action
- Preferred real `note_sku_links` joined to `notes.publish_time`.
- Added conservative fallback when `note_sku_links` is absent but `notes(note_id, publish_time)` and `skus(sku_id)` exist:
  - uses each eligible note crossed with the first SKU
  - capped at 25 notes
  - explicitly marked as weak attribution
- Anchored windows to each linked note's `publish_time`.
- Added long-tail `d8_14` window.
- Expanded `sku_lift` rows to include:
  - `window`
  - `pre_units`
  - `post_units`
  - `absolute_lift`
  - `relative_lift`
- Expanded `response_windows` rows to include:
  - `d0_1_units`
  - `d1_3_units`
  - `d4_7_units`
  - `d8_14_units`

## Regression Coverage

`tests/test_task9_regressions.py` covers:

- missing `daily_sku_sales` does not crash
- missing required `daily_sku_sales` columns does not crash
- no links / no notes returns `NOT_JUDGABLE`
- publish-time anchored window math on constructed fixtures
- `pre_units = 0` yields `relative_lift is None`
- `d8_14` fields exist in both task outputs

## Verification

- `pytest -q tests/test_task9_regressions.py`
- `pytest -q tests/test_task9_regressions.py tests/test_analysis_tasks.py -k "sku_lift or response_curve"`
- `ruff check xhs_ceramics_analytics/analysis/sku_lift.py xhs_ceramics_analytics/analysis/response_curve.py tests/test_task9_regressions.py`
- `pytest -q`

All passed in the final verification run.

## Residual Concerns

- Candidate fallback remains intentionally weak and should not be read as causal evidence.
- Overlapping notes for the same SKU can still make descriptive windows noisy until explicit linking and better experimental controls exist.
