Maintainer note — not loaded by the skill at runtime.

# First Version Implementation Decisions

These choices are part of the V1 design:

- Start as a full Codex plugin if practical, with one primary skill and supporting references/templates. If plugin packaging adds friction, keep the folder skill-compatible and add plugin packaging after the skill works.
- Use DuckDB directly and prefer installing or vendoring `duckdb/duckdb-skills` rather than rewriting equivalent behavior.
- Write Markdown and single-file HTML reports. Markdown is the guaranteed fallback.
- Start content feature extraction with manual tags plus Codex-assisted labeling. Add OpenCV/CLIP-assisted extraction only through an optional adapter, not as a hard dependency.
- Store project state under `.xhs-ceramics-analytics/` by default: mapping, DuckDB database, report outputs, experiment records, and hypothesis knowledge base.
- Keep upstream sources recorded in `references/upstream_sources.md` with repository URL, license, commit hash, copied paths, and local changes.

## 2026-07-10 Decision compiler direction

- Adopt DecisionBrief as the mid-pipeline compile target (L2.5) so narrative and
  fact-layer HTML are two views of one decision object, not two module dumps.
- Metric identity is global via `references/metrics/registry.yaml` (`metric_id`),
  not `{module}.{local_key}` alone.
- Reader epistemics: 描述置信 + 行动许可 only; stop dual headline labels that
  fight (事实层「高」vs 叙事「弱」vs 视图「强」).
- ActionCard is first-class; free-text `recommended_action` is compatibility-only
  and cannot enter Top actions without schema fields.
- Full design: `docs/superpowers/specs/2026-07-10-decision-compiler-architecture-design.md`.
