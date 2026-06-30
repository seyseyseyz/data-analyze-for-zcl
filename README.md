# Xiaohongshu Ceramics Analytics

Local Codex skill/plugin project for Xiaohongshu ceramics ecommerce analytics.

The project is designed to turn exported Xiaohongshu content data, product/SKU data, order data, and cover images into decision-first operating reports. It should reuse mature analytics tooling wherever possible, especially DuckDB and existing agent data-analysis workflows, while keeping custom code focused on the Xiaohongshu ceramics domain.

## Current Scope

- Design-first project scaffold.
- Full V1 spec in `docs/specs/`.
- No implementation code yet; implementation should follow an approved plan.

## Core Principles

- Reuse mature upstream projects instead of building toy replacements.
- Treat note-to-order attribution as weak inference unless explicit source data exists.
- Report evidence strength and caveats for every conclusion.
- Make reports readable for non-technical operators.

