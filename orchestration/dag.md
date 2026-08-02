# Quality-first narrative orchestration DAG (host-neutral)

This is the source contract for turning deterministic analysis results into one
merchant-facing report. Quality is the optimization target. Agent count and inference cost do not
justify removing an independent challenge, adjudication, review, or final-quality step.

The controller is passive: it freezes inputs, writes immutable task briefs, ingests schema-validated
results, reduces events into state, runs deterministic gates, and writes artifacts. The host asks for
authorization and dispatches the named tasks. No agent owns a business number or metric definition.

pipeline: authorization → spine_candidates → spine_adjudication → domain_writer → domain_challenge → domain_adjudication → cross_domain_synthesis → visual_curation → gate → review → targeted_revision → continuity → candidate_html → merchant_final_review → finalized → blocked

## Authority boundaries

| Layer | Owns | Must not do |
|---|---|---|
| deterministic facts | values, rendered number strings, fact identity, direction, evidence strength | accept an agent-authored magnitude |
| registry | metric name, unit, caliber, period, aggregation, formula, grain, tooltip text | let narrative prose redefine semantics |
| deterministic tables | table identity, columns, rows, calculations and source lineage | accept agent-authored cells or re-aggregation |
| agents | judgment, selection, order, ID binding, prose around opaque tokens | author values, units, metric labels, caliber, period or aggregation |
| renderer | token substitution, registry labels, charts, tooltips, candidate and final HTML | expose internal catalogs as report content |

Agent outputs may bind only existing `fact_id`, `claim_id`, `table_id`, `view_id`, `action_id` and
task-local structural IDs. Every business magnitude in prose is an opaque `{tN}` backed by a
`number_token`; the deterministic layer resolves it. Field explanations never become an inline
glossary. A concise tooltip may be rendered from registry metadata when it materially helps reading.

## Role policy

- **judgment/high** — strongest reasoning tier exposed by the host; used for competing hypotheses,
  challenge, adjudication, synthesis, curation, continuity and final review.
- **draft/medium** — standard drafting tier; permitted for initial domain writing when followed by an
  independent judgment/high challenger and adjudicator.

Role tiers are stable contract data. Model identities are host-local and never enter prompts, state,
schema hashes, or cache keys.

## Stages and outputs

| Stage | Tasks | Tier | Consumes | Emits |
|---|---:|---|---|---|
| authorization | user decision | — | explicit distinct question | authorized / denied / no answer yet; denied enters deterministic-v2 without agents |
| spine_candidates | **2 independent** tasks using `seed.md` | judgment/high | frozen facts, registry validation, table catalog | two `spine_brief` objects |
| spine_adjudication | one independent adjudicator | judgment/high | both candidates + deterministic precheck | `spine_adjudication` |
| domain_writer | one per producible domain, parallel | draft/medium | domain slice + resolved callback + allowed IDs | `section_bundle` |
| domain_challenge | one per domain, independent of writer | judgment/high | writer output + same immutable evidence | `challenge_report` |
| domain_adjudication | one per domain | judgment/high | draft + challenge + resolved spine | `domain_adjudication` |
| cross_domain_synthesis | one synthesizer | judgment/high | ready domains + blocked-domain ledger + spine | `narrative_bundle` |
| visual_curation | independent curator | judgment/high | locked claims + deterministic table catalog | `visual_curation` per section |
| gate | deterministic code | — | narrative, views, facts, registry, tables | `gate_report` |
| review | three independent lens tasks per reviewed section | judgment/high | gated views + their claim/table bindings | `review_verdict` |
| targeted_revision | one task per named blocker target | judgment/high | one target + blocker + immutable evidence | `targeted_revision` |
| continuity | one full-report reader | judgment/high | gated prose after review convergence | `continuity_edit[]` |
| candidate_html | deterministic renderer | — | re-gated narrative + retained views | internal candidate HTML |
| merchant_final_review | one independent merchant reviewer | judgment/high | actual candidate HTML + ID index | `merchant_final_review` |
| finalized | deterministic final gate and atomic delivery | — | accepted candidate + exact snapshot | one final HTML |
| blocked | fail-closed deterministic fallback | — | verified facts/tables + blocker ledger | one deterministic HTML |

Every schema in `schemas/` is closed at its object boundary. Any unknown key, unresolved ID, duplicate
task result, hash mismatch, malformed token, or out-of-snapshot reference is rejected before state
can advance.

## Quality flow

### Spine competition

The two spine candidates are produced without seeing one another. The adjudicator compares accounting
closure, evidence coverage, semantic consistency, merchant decision value and CANNOT-SAY honesty.
It may merge a stronger link from the non-selected candidate, but every resolution binds supporting
`fact_id` values. An accounting break or semantic conflict is a blocker, not an editorial preference.

### Domain adversarial loop

Each domain always receives a writer, a separate challenger and an adjudicator. The challenger defaults
to fail until evidence, meaning, direction, causal license, action executability and spine connection
are defensible. The adjudicator resolves every finding explicitly; unresolved blockers mark that domain
blocked and prevent its claims from silently entering synthesis. There is no cost-based domain folding
or role skipping.

### Synthesis and visual curation

Cross-domain synthesis removes duplication and resolves priority conflicts while preserving canonical
claims, actions, token bindings and dissent. Visual curation is separate from writing: it selects only
views whose runtime `supports_claim` contains a real `claim_id` and whose `source.table` contains an
existing deterministic `table_id`. There is **no per-domain cap**
on tables or charts, but there is also no quota: zero strong views is better than a raw dump.

### Deterministic gate and three-lens review

The gate verifies facts, token bytes, directions, entities, pools, registry semantics, view sources,
table columns and all displayed values. It runs before review so reviewers judge a numerically locked
candidate.

Each reviewed section receives exactly one task for each lens:

- `evidence_semantics` — support, direction, denominator, period, aggregation and causal license.
- `merchant_decision` — whether the view changes understanding, priority or action.
- `editorial_visual` — form choice, density, labels, accessibility and raw-dump avoidance.

Verdicts are recorded idempotently by section + lens + view. No duplicate lens can create a false
majority. Retained views keep a real `supports_claim` binding. Unsupported or semantically wrong views
are dropped; repairable decision/visual problems become targeted blockers.

### Targeted convergence

Revisions replace or drop exactly one `claim_id`, `view_id`, or `action_id`; they never overwrite an
entire section or bundle. After each revision, the affected deterministic gate and relevant independent
review rerun. There are at most two targeted revision rounds. This bound exists to force convergence
and prevent oscillating rewrites, not to reduce cost. After exhaustion, an unreliable target is dropped
when safe; a report-critical blocker moves the run to `blocked`.

### Continuity, candidate, merchant final review

Continuity is prose-only and preserves every digit and token multiset. The deterministic renderer then
writes candidate HTML for internal inspection. Merchant final review reads that actual artifact and
cannot edit it. Evidence, semantic, decision, visual, continuity or delivery failures return named
targets to the same bounded revision loop. A changed candidate must be re-gated and re-reviewed.

Only an accepted candidate whose final hashes match the frozen inputs is atomically promoted to the
single user-facing HTML.

## Quality blockers

| Class | Examples | Required outcome |
|---|---|---|
| evidence | missing fact/table, invented magnitude/entity, unsupported view | targeted repair or drop; block if report-critical |
| semantic | wrong unit/caliber/period/aggregation, denominator or direction conflict | deterministic failure; repair binding, never prose-override |
| decision | no clear priority, action lacks owner/metric/stop rule, recommendation exceeds evidence license | revise action/claim or block |
| visual | wrong form, unreadable density, raw dump, view does not prove claim | revise or drop view |
| continuity | contradictory sections, repeated conclusions, broken callbacks, token-changing edit | reject edit or targeted claim repair |
| delivery | renderer error, missing/empty HTML, stale hashes, two user-facing reports | fail closed; never mark finalized |

Warnings may annotate internal telemetry but never waive a blocker. A `finalized` state without a
non-empty, validated, atomically written final HTML is invalid.

## Artifact and delivery contract

Facts, tables, task briefs, prompts, schemas, candidate HTML, Markdown, gate reports, reviews, revision
logs and frozen narratives are internal artifacts. They are retained for traceability and cache
validation, not delivered as extra reports. The user receives exactly one final HTML, whether the run
finishes through the narrative path or the deterministic blocked fallback.

The final page uses only registry-validated names, values and units. It stays concise: no HAR catalog,
no field-definition appendix and no inline field glossary. Optional tooltip text is generated from the
registry and is not agent-authored.
