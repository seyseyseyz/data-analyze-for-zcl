# Changelog

## 0.2.0 (2026-07-02)

### Reporting
- HTML report gains hand-built inline-SVG charts (no runtime charting
  dependency): evidence-distribution, cover/copy small multiples, comment-demand
  shares, content-response curves, and product-opportunity / paid-traffic
  scatters. Charts follow an evidence-honesty grammar (weak samples de-emphasized,
  not-judgable results draw no chart). Markdown report stays chart-free.
- Dropped the `plotly` runtime dependency; charts are rendered as static SVG.

### Skill contract rewrite
- SKILL.md rewritten with positive-first trigger description
- Reference-load points inlined directly in skill contract

### Task templates
- 16 task templates rewritten as full standalone references with formulas,
  thresholds, output columns, fixture bindings, and sample SQL/code

### References restructured
- data_contract split into per-table schema files
- Added cheatsheet.md, troubleshooting.md, xhs_glossary.md

### Evals
- evals.json upgraded to v2 schema with fixture binding, assertions,
  negative-trigger coverage, and per-task eval mapping

### Runtime UX
- Launcher auto-bootstrap on first invocation
- scripts/sync-runtime canonical guard (top-level is source of truth)
- `xhs-ca --version` prints package version
- `xhs-ca tasks` lists available analysis tasks

### Maintainer tooling
- Maintainer docs moved to docs/maintainers/
- scripts/run-evals driver for eval checklist
- CI workflow (.github/workflows/skill.yml) with lint, pytest, sync-check
- `xhs-ca doctor --strict` as CI-safe validation entry point

## 0.1.0 (2025-06-01)

- Initial release: DuckDB build pipeline, CLI skeleton, doctor checks,
  basic task registry, markdown/HTML reporting.
