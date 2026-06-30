### 12. Weekly Experiment Matrix

Purpose:

Generate a concrete 7-day posting plan.

Rules:

- 5 posts per day.
- Keep 20-30 percent exploration slots.
- Keep high-confidence winners in exploitation slots.
- Control SKU, vessel type, time slot, or copy angle where possible.
- Avoid testing too many variables at once.
- Avoid same-SKU overcrowding unless deliberately testing repetition.
- Include decision rule before running the experiment.

Output:

- day,
- time slot,
- SKU/product,
- cover style,
- copy angle,
- changed variable,
- controlled variables,
- success metric,
- evidence expected,
- stop/continue decision rule.

## First Version Implementation Decisions

These choices are part of the V1 design:

- Start as a full Codex plugin if practical, with one primary skill and supporting references/templates. If plugin packaging adds friction, keep the folder skill-compatible and add plugin packaging after the skill works.
- Use DuckDB directly and prefer installing or vendoring `duckdb/duckdb-skills` rather than rewriting equivalent behavior.
- Write Markdown and single-file HTML reports. Markdown is the guaranteed fallback.
- Start content feature extraction with manual tags plus Codex-assisted labeling. Add OpenCV/CLIP-assisted extraction only through an optional adapter, not as a hard dependency.
- Store project state under `.xhs-ceramics-analytics/` by default: mapping, DuckDB database, report outputs, experiment records, and hypothesis knowledge base.
- Keep upstream sources recorded in `references/upstream_sources.md` with repository URL, license, commit hash, copied paths, and local changes.
