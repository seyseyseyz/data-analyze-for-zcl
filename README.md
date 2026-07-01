# Xiaohongshu Ceramics Analytics

Local Codex skill/plugin project for Xiaohongshu ceramics ecommerce analytics.

The project is designed to turn exported Xiaohongshu content data, product/SKU data, order data, and cover images into decision-first operating reports. It should reuse mature analytics tooling wherever possible, especially DuckDB and existing agent data-analysis workflows, while keeping custom code focused on the Xiaohongshu ceramics domain.

## Current Scope

- Design-first project scaffold.
- Python package foundation with editable local dev setup.
- Full V1 spec in `docs/specs/`.
- Feature implementation should follow the approved plan.

## Development Setup

```bash
./scripts/bootstrap
pytest -q
```

`./scripts/bootstrap` creates `.venv`, installs the editable package with dev
dependencies, and runs `xhs-ca doctor --strict`.

## Skill Install

List the published skill without installing:

```bash
npx skills add seyseyseyz/data-analyze-for-zcl -l
```

Install globally:

```bash
npx skills add seyseyseyz/data-analyze-for-zcl -g -y
```

## Quick Start

```bash
./scripts/bootstrap
xhs-ca build tests/fixtures/notes.csv tests/fixtures/products.csv tests/fixtures/skus.csv tests/fixtures/orders.csv tests/fixtures/content_features.csv tests/fixtures/comments.csv tests/fixtures/calendar_events.csv
xhs-ca run all
```

Reports are written under `.xhs-ceramics-analytics/outputs/`.

## Environment Check

Run this before analyzing real exports, especially on a new machine:

```bash
xhs-ca doctor
```

The doctor checks Python version, state/output root, virtual environment status,
required Python dependencies, the `xhs-ca` command, and whether the local state
directory is writable. Use strict mode in automation:

```bash
xhs-ca doctor --strict
```

## Your Own Exports

1. Export your Xiaohongshu notes, products, SKUs, orders, comments, and calendar data as CSV files.
2. Check the local environment:

```bash
xhs-ca doctor
```

3. Build the local DuckDB database:

```bash
xhs-ca build path/to/notes.csv path/to/products.csv path/to/skus.csv path/to/orders.csv
```

4. Run a single analysis task or the full report menu:

```bash
xhs-ca run weekly_business_review
xhs-ca run all
```

5. Open the generated Markdown or HTML report under `.xhs-ceramics-analytics/outputs/`.

You can also run the CLI without installation:

```bash
python -m xhs_ceramics_analytics.cli build path/to/notes.csv path/to/orders.csv
python -m xhs_ceramics_analytics.cli run all
```

## Analysis Menu

- `data_quality_check`
- `account_baseline`
- `note_funnel`
- `sku_counterfactual_lift`
- `content_response_curve`
- `cover_style_effect`
- `copy_angle_effect`
- `product_content_interaction`
- `product_opportunity_matrix`
- `comment_demand_mining`
- `content_portfolio_optimization`
- `weekly_experiment_matrix`
- `reshoot_repost_candidates`
- `hypothesis_knowledge_base`
- `weekly_business_review`

## What The Tool Produces

- A local DuckDB project state under `.xhs-ceramics-analytics/`
- Markdown reports that summarize findings, evidence strength, caveats, and suggested next actions
- A full `all` report that combines the current V1 task registry into one operating review

## Evidence Rule

The skill reports strong, medium, weak, or not-judgable evidence for every conclusion. Weak attribution is treated as a hypothesis, not a fact.

## Core Principles

- Reuse mature upstream projects instead of building toy replacements.
- Treat note-to-order attribution as weak inference unless explicit source data exists.
- Report evidence strength and caveats for every conclusion.
- Make reports readable for non-technical operators.
