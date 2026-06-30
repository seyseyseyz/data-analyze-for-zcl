Task 9 fix report

Changed files:
- `xhs_ceramics_analytics/analysis/sku_lift.py`

What changed:
- Renamed the SQL output alias from `lift_units` to `absolute_lift`.
- Renamed the corresponding `key_numbers` field from `lift_units` to `absolute_lift`.
- Kept the lift calculation unchanged.

Tests:
- `. .venv/bin/activate && pytest -q tests/test_analysis_tasks.py -k sku_lift`
  - Result: passed, `1 passed, 8 deselected`.
- `. .venv/bin/activate && ruff check xhs_ceramics_analytics/analysis/sku_lift.py`
  - Result: passed, `All checks passed!`
