Task 11 quality fix report

Changed files:
- `xhs_ceramics_analytics/analysis/experiment_matrix.py`
- `xhs_ceramics_analytics/analysis/portfolio.py`
- `xhs_ceramics_analytics/analysis/hypothesis.py`
- `xhs_ceramics_analytics/analysis/reshoot.py`
- `xhs_ceramics_analytics/analysis/weekly_review.py`
- `tests/test_task11_regressions.py`

What changed:
- Hardened Task 11 modules against partial tables and missing columns by checking table schemas before column-dependent SQL, then falling back to null metrics or fallback rows with limitations instead of crashing.
- Added `DEFAULT_PLANNING_START = date(2026, 7, 1)` and stopped experiment planning from emitting past dates when `notes.publish_time` is missing or stale.
- Made weekly review summaries None-safe so null SKU metrics render as `unknown` instead of raising during string formatting.
- Changed reshoot ranking to conservatively shrink tiny-sample collect rates, added `needs_more_data`, and prevented 1-read / 1-collect notes from leading the queue.
- Stopped hypothesis demand seeding from inventing concrete demand themes when comment evidence is absent; it now returns `unknown` / `needs_data` with a data-collection next step.
- Added focused regression coverage for partial-table fallbacks, null weekly summaries, tiny-sample reshoot ranking, no-comment hypotheses, and future planning dates.

Tests:
- `. .venv/bin/activate && pytest -q tests/test_task11_regressions.py`
  - Result: passed, `8 passed`.
- `. .venv/bin/activate && pytest -q tests/test_task11_regressions.py tests/test_analysis_tasks.py -k "decision_and_knowledge or portfolio or experiment or reshoot or hypothesis or weekly"`
  - Result: passed, `9 passed, 8 deselected`.
- `. .venv/bin/activate && ruff check xhs_ceramics_analytics/analysis/experiment_matrix.py xhs_ceramics_analytics/analysis/portfolio.py xhs_ceramics_analytics/analysis/hypothesis.py xhs_ceramics_analytics/analysis/reshoot.py xhs_ceramics_analytics/analysis/weekly_review.py tests/test_task11_regressions.py`
  - Result: passed, `All checks passed!`
- `. .venv/bin/activate && pytest -q`
  - Result: passed, `74 passed`.

Concerns:
- The reshoot shrinkage uses a fixed 50-read confidence threshold. It is conservative for early accounts, but the threshold may be worth calibrating later if real note volumes cluster much lower or much higher.
