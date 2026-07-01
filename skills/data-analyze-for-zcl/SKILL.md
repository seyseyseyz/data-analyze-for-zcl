---
name: data-analyze-for-zcl
description: Use when analyzing exported Xiaohongshu content, cover, product, SKU, order, comment, or experiment data for a ceramics ecommerce account. Produces evidence-scored local reports and weekly experiment matrices.
---

# Xiaohongshu Ceramics Analytics

Use this skill for local Xiaohongshu ceramics ecommerce analysis.

## Workflow

1. Resolve this skill directory first. Use the bundled runtime under `assets/xhs-ca/`; do not assume the user has cloned the source repo separately.
2. On first use, run this skill's `scripts/bootstrap`. It creates `assets/xhs-ca/.venv`, installs the bundled Python package, and verifies the environment.
3. Ask the user for exported CSV files and any cover image folders they want to reference.
4. Run this skill's `scripts/xhs-ca build ...` to profile CSV headers, apply the closest standard table mapping, and build the local DuckDB database.
5. Run this skill's `scripts/xhs-ca run <task>` or `scripts/xhs-ca run all` for the full V1 report menu.
6. Present conclusions with evidence strength, caveats, and next actions.

## Commands

```bash
<skill-dir>/scripts/bootstrap
<skill-dir>/scripts/xhs-ca doctor
<skill-dir>/scripts/xhs-ca build path/to/notes.csv path/to/orders.csv path/to/skus.csv
<skill-dir>/scripts/xhs-ca run all
<skill-dir>/scripts/xhs-ca run sku_counterfactual_lift
```

## Bundled Runtime

- `assets/xhs-ca/xhs_ceramics_analytics/` contains the full Python analysis package.
- `assets/xhs-ca/references/` contains the data contracts, metric definitions, evidence rules, and report contract.
- `assets/xhs-ca/task_templates/` contains the task-level report and analysis templates.
- `assets/xhs-ca/tests/` contains fixtures and regression tests for validating the bundled runtime.
- `scripts/sync-runtime` is for maintainers: run it from the repo checkout before publishing the skill so the bundled runtime matches the current source tree.

Load reference files only when they are needed for the user's task. For task selection, start with `assets/xhs-ca/references/task_menu.md`; for schema questions, read `assets/xhs-ca/references/data_contract.md`; for metric semantics, read `assets/xhs-ca/references/metric_definitions.md`; for evidence scoring, read `assets/xhs-ca/references/evidence_strength.md`.

## Rules

- Do not claim deterministic note-to-order attribution unless explicit source data supports it.
- If data is missing, produce a limitation report and next-data-needed list.
- Prefer DuckDB and upstream analytics workflows over custom one-off scripts.
