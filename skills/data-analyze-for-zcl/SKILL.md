---
name: data-analyze-for-zcl
description: Use only when the user explicitly invokes data-analyze-for-zcl, or when the request clearly says Xiaohongshu/小红书/千帆 ceramics/tableware ecommerce exports. Do not auto-trigger for generic data analysis, generic ecommerce, spreadsheets, SKUs, orders, comments, or other platforms unless the user explicitly asks for this skill. It builds a local DuckDB database and evidence-scored reports for notes, cover/copy tags, products/SKUs, orders, comments, weekly reviews, experiment matrices, and SKU 销量响应.
---

# Xiaohongshu Ceramics Analytics

Use this skill for local Xiaohongshu ceramics ecommerce analysis. This is not a generic data-analysis skill; if the user has not clearly named Xiaohongshu/小红书/千帆 or explicitly invoked `data-analyze-for-zcl`, do not use it.

## Workflow

1. Resolve this skill directory first. Use the bundled runtime under `assets/xhs-ca/`; do not assume the user has cloned the source repo separately.
2. On first use, run this skill's `scripts/bootstrap`. It creates or repairs `assets/xhs-ca/.venv`, installs the bundled Python package, verifies the environment, and prints a Terminal repair command if the runtime cannot be prepared automatically.
3. Ask the user for exported Excel/CSV files and any cover image folders they want to reference.
4. Run this skill's `scripts/xhs-ca build ...` from the user's project/data directory to profile file headers, apply the closest standard table mapping, and build the local DuckDB database under that directory's `.xhs-ceramics-analytics/`.
5. Run this skill's `scripts/xhs-ca run <task>` or `scripts/xhs-ca run all` for the full V1 report menu.
6. Before summarizing generated reports, read `assets/xhs-ca/references/report_contract.md`. For a single-task report, also read the matching `assets/xhs-ca/task_templates/<task>.md`.
7. Present conclusions with evidence strength, caveats, and next actions.

## Commands

```bash
<skill-dir>/scripts/bootstrap
<skill-dir>/scripts/xhs-ca doctor
<skill-dir>/scripts/xhs-ca build path/to/notes.xlsx path/to/orders.xlsx path/to/skus.xlsx
<skill-dir>/scripts/xhs-ca run all
<skill-dir>/scripts/xhs-ca run sku_counterfactual_lift
```

If an older installed copy keeps selecting macOS Python 3.9, refresh the global skill before rerunning bootstrap:

```bash
rm -rf "$HOME/.agents/skills/data-analyze-for-zcl"
npx skills add seyseyseyz/data-analyze-for-zcl -g -y --skill data-analyze-for-zcl
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

## Bundled Runtime

- `assets/xhs-ca/xhs_ceramics_analytics/` contains the full Python analysis package.
- `assets/xhs-ca/references/` contains the data contracts, metric definitions, evidence rules, and report contract.
- `assets/xhs-ca/task_templates/` contains the task-level report and analysis templates.
- `assets/xhs-ca/tests/` contains fixtures and regression tests for validating the bundled runtime.
- `scripts/sync-runtime` is for maintainers: run it from the repo checkout before publishing the skill so the bundled runtime matches the current source tree.

Load reference files only when they are needed for the user's task. For task selection, start with `assets/xhs-ca/references/task_menu.md`; for schema questions, read `assets/xhs-ca/references/data_contract.md`; for metric semantics, read `assets/xhs-ca/references/metric_definitions.md`; for evidence scoring, read `assets/xhs-ca/references/evidence_strength.md`; before final report summarization, read `assets/xhs-ca/references/report_contract.md`.

## Rules

- Do not claim deterministic note-to-order attribution unless explicit source data supports it.
- If data is missing, produce a limitation report and next-data-needed list.
- Prefer DuckDB and upstream analytics workflows over custom one-off scripts.
