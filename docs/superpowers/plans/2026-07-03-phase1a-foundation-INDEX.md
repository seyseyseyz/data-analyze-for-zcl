# Phase 1a Foundation — Plan Index

> Source spec: [`docs/superpowers/specs/2026-07-03-content-sku-diagnosis-foundation-design.md`](../specs/2026-07-03-content-sku-diagnosis-foundation-design.md)

Phase 1a is split into **three independently executable plans**. Each produces
working, tested software on its own and can be reviewed/merged separately.

| # | Plan | Spec sections | Depends on | Notes |
|---|------|---------------|------------|-------|
| 1 | [Report Contract & Renderer](./2026-07-03-phase1a-1-report-contract.md) | C | — | Ship first. Also holds **Task 0** (commit pre-existing WIP) — a shared prerequisite for all three. |
| 2 | [Analytic Helpers](./2026-07-03-phase1a-2-analytic-helpers.md) | D | — | Pure functions, no I/O. Fully parallel with Plan 1. |
| 3 | [Real Export Ingestion](./2026-07-03-phase1a-3-real-export-ingestion.md) | A, B, E, F | Plan 2 (marts import `analytics/`) | The bulk: table-scoped classification, merge-on-grain-key (+ conflict/provenance logging), 9 table types, marts, needs-data, fixtures, docs, sync. |

## Recommended execution order

1. **Plan 1 Task 0** first (commit the pre-existing WIP so every plan starts from a clean tree).
2. Plans **1 and 2** in parallel (renderer track + helper track — no shared files).
3. **Plan 3** after Plan 2 lands (its marts in Section E import `xhs_ceramics_analytics.analytics.periods`).

## Global constraints (apply to all three plans)

- Python **3.11+** (`match`, `X | Y` unions, `StrEnum`). ruff **line-length = 100**.
- Tests: pytest, `pythonpath=["."]`, `testpaths=["tests"]`. Run a single test with
  `pytest tests/<file>.py::<test> -v`; the full suite with `pytest`.
- Attribution disabled globally — **no `Co-Authored-By` trailer** on commits.
- Named constants (copy verbatim where used):
  `MIN_TABLE_CONFIDENCE = 0.25`, `MIN_FIELD_CONFIDENCE = 80`, `MARGIN = 0.15`,
  `MIN_ORDERS_FOR_RATE = 30`, `LOW_JOIN_COVERAGE = 0.70`,
  `MERGE_CONFLICT_TOLERANCE = 0.05` (Plan 3 Task 3), `REFUND_RECONCILE_TOLERANCE = 0.05` (Plan 3 Task 12).
- **Runtime mirror:** the package is mirrored at
  `skills/data-analyze-for-zcl/assets/xhs-ca/`. After source changes, run the
  project's **sync-runtime** step to regenerate the mirror (Plan 3's final task
  does this once for the whole phase; if you land Plan 1/2 separately, run it there too).
- **Do not touch** the read-only source data: the WeChat export dir
  `小红书千帆4-7月数据` and the reference HTML report.
