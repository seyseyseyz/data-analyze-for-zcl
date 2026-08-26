# Changelog

## Unreleased

### Evidence & methodology

- Land the Decision Compiler action-license projection: findings project to a
  second reader label (可执行/可试点/仅观察/先补数据) via
  `reporting.confidence.action_license`, the factcheck gate caps an action card's
  stated license to what its primary fact's evidence allows (mechanism-supported
  actions cap at pilot), and fact-layer HTML actions carry the 行动许可 chip.
- Control multiple comparisons in content group scans: cover/copy/portfolio
  ranking tables gain a BH-FDR `read_rate_signal` verdict per group, so a leader
  that is merely lucky is no longer presented like a proven winner.

### Serial host workflow

- Add `xhs-ca narrative next` / `submit`: a two-command per-task loop for hosts
  that work one task at a time (no parallel sub-agent facility). `next` advances,
  reserves one task, and generates the dispatch identity; `submit` validates
  read-only, ingests, and releases capacity. The low-level ledger primitives stay
  available for parallel hosts and repair.
- Expose the recorded `authorization_decision` in `narrative status --json`, so a
  resuming host reads the stored answer instead of re-asking the user.

### Development hygiene

- Add a commit-time mirror guard (`scripts/git-hooks/pre-commit`, enable with
  `git config core.hooksPath scripts/git-hooks`) so a commit touching canonical
  sources carries the regenerated skill mirror.

### Design

- Add Decision Compiler architecture ADR (`docs/superpowers/specs/2026-07-10-decision-compiler-architecture-design.md`).
- Add a validated, observation-only metric ontology (`references/metrics/registry.yaml`),
  strict loader, and schemas for `decision_brief` / `action_card`.
- Separate daily-distinct primitives, person-days, daily means, and means of daily
  ratios so window-level user metrics cannot be mislabeled as period-unique people.
- Extend report/evidence contracts toward metric_id, period context, and action license projection.

### Metric runtime

- Move the FactBook to canonical v3: unique keys preserve `task.key`, while repeated
  keys receive a shared deterministic finding scope used by facts, narrative, and HTML.
- Validate exact registry bindings against producer owner and the pinned producer
  contract for unit, caliber, aggregation, and grain before exposing `metric_id`,
  display name, or formula; rejected and dynamic-dimension facts stay unmapped with
  deterministic diagnostics.
- Correct person-day and observed-day units, and remove fixed bindings for values whose
  carrier, refund stage, or audience member is selected dynamically at runtime.
- Publish `facts.json` and `results.json` as one active pair with `sidecar_status.json`;
  consumers accept only a hash-matched `ready` pair, while interrupted or failed
  rebuilds invalidate the old pair instead of silently reusing stale facts.

### HTML reporting

- Use registry-validated FactBook labels, rendered values, and units for mapped key
  numbers. Field explanations are accessible hover/focus tooltips and no longer occupy
  the normal report layout; HAR/platform field catalogs remain internal.
- Ask for multi-agent authorization as the first workflow gate, build deterministic
  evidence with `facts auto`, and deliver only the finalized merchant HTML by default;
  fact sidecars and Markdown remain internal unless explicitly requested.

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
