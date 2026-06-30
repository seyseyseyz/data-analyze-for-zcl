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
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
pytest -q
```

## Core Principles

- Reuse mature upstream projects instead of building toy replacements.
- Treat note-to-order attribution as weak inference unless explicit source data exists.
- Report evidence strength and caveats for every conclusion.
- Make reports readable for non-technical operators.
