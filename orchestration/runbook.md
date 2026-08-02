# Quality-first narrative workflow runbook

This runbook is the host control loop for the passive narrative controller. It prioritizes the final
merchant report over inference cost. Independent challenge, adjudication, curation and final review are
required quality controls, not optional enhancements.

## Authorization — ask first (a blocking gate; asking is not spawning)

Before `prepare` or any agent dispatch, ask the user one **distinct question** requesting multi-agent
authorization for this report. Do not hide it in a progress update. Authorization is a **blocking gate**:
STOP and **wait** for the reply in a later turn.

Treat the three states separately:

- **authorized** — proceed with the complete quality-first loop.
- **denied** — prepare the deterministic-only state with `--multi-agent-declined`, then finalize it
  with `--reason denied`; do not dispatch any agent.
- **no answer yet** — keep waiting; this is neither denied nor unsupported.

Once authorized, reuse that decision for the same report through later turns, interruptions, retries
and concurrency limits; do not ask again. Ask for multi-agent authorization again only for a separate
report after the current run finishes or when the user explicitly revokes it. A required field-mapping
decision is a separate semantic question and does not reopen the authorization gate.

If the host genuinely has no sub-agent facility, use `--reason unsupported`. “Permission has not been
asked yet” is not unsupported. Asking is not spawning, so the question is still mandatory.

## Human decision boundary

Interrupt the user only when an unresolved field or metric meaning genuinely requires operator judgment
to proceed or would materially change a report conclusion. Missing data, weak evidence, a blocked optional
task or an available neutral fallback does not require a question; leave the field unmapped and continue
with Not-judgable plus exact next-data-needed.

When judgment is required, provide one complete decision packet: source file and sheet, source header and
representative sample values, candidate canonical fields and their official definitions, unit, grain,
aggregation, PV/UV and payment/refund-time differences, mapping method/score/conflict reason,
affected tasks and conclusions, and a recommended option with rationale. Always include `leave unmapped`; never ask
a bare field-mapping question.

## Freeze and prepare

Run:

```text
xhs-ca narrative prepare --run-dir <dir> --results <state-dir>/results.json --facts <state-dir>/facts.json --name <report> --multi-agent-authorized
```

`results.json` and `facts.json` come from the deterministic run/facts step. Never hand-build domain
slices and never pass facts as results. Prepare freezes and hashes:

- facts and deterministic result tables;
- registry snapshot and mapping overrides;
- entity and causal-license ledgers;
- prompts, schemas, role tiers, controller and renderer versions;
- authorization state and the single-HTML delivery contract.

It writes a snapshot manifest, durable task queue and the first pending briefs. `--force` is
only for an intentional replacement of an unfinished run.

## Passive control loop

1. Run `xhs-ca narrative status --run-dir <dir> --json`.
2. Read only the pending task briefs listed by status. Each task exposes `result_path`, `schema_path`,
   allowed enums, immutable `controller_fields`, `current_round`, run-scoped dynamic values and
   `contract_version`; do not reconstruct these from filenames or memory.
3. Reserve only available capacity with `xhs-ca narrative reserve --run-dir <dir> --capacity <n> --json`.
   After dispatch, persist its identity with `xhs-ca narrative record-dispatch --run-dir <dir> --task-id
   <task_id> --agent-id <agent_id> --result-path <file>`. Return an unassigned reservation with
   `xhs-ca narrative release`.
4. Persist completion or failure with `xhs-ca narrative record-agent-state --status
   result_ready|failed|closed`. The ledger is the scheduling truth after an interruption; never redispatch
   an already reserved or dispatched task under another identity. Ingest is allowed only after the recorded
   agent reaches `result_ready`, and its source must match its registered `result_path`.
5. Before ingest, run `xhs-ca narrative validate --run-dir <dir> --stage <stage> --task-id <task_id>
   --source <file>`. Validation fills absent controller-owned IDs/rounds, rejects conflicts and does not
   mutate task state.
6. For every valid result run `xhs-ca narrative ingest --run-dir <dir> --stage <stage> --task-id <task_id>
   --source <file>`. Ingest rejects stale/wrong-stage tasks, missing required envelope fields and duplicate
   review identities before recording completion.
7. Run `xhs-ca narrative advance --run-dir <dir>`. Advance refuses while required tasks are pending and
   runs deterministic gates at their declared stages.
8. Re-run `status --json`; never infer the next stage from memory or filenames.

The controller may prepare briefs and reduce state, but it never pretends a missing agent result exists.

If dispatch reports a concurrency limit, first inspect all already-dispatched agents. Ingest finished
results and close completed agents to release capacity, then retry pending tasks with a smaller batch or
serially. Concurrency limits are transient scheduling pressure: they must not trigger `unsupported`,
deterministic fallback, report degradation, or another user prompt.

## Dispatch map

### Spine candidates and adjudication

Dispatch **2 independent** `seed` tasks in parallel. They share the same frozen evidence but cannot see
one another's output. After both valid `spine_brief` results arrive, dispatch one
`spine_adjudicator`. Do not advance if either candidate is missing, duplicated, schema-invalid or
references facts outside the snapshot.

The adjudicator must resolve accounting closure, evidence coverage and semantic conflicts. Any unresolved
accounting or semantic blocker stops domain writing rather than being buried in prose.

### Domain writer, challenger and adjudicator

For every producible domain, dispatch:

1. one `domain_writer` using the resolved callback and domain evidence;
2. one independent `domain_challenge` after its writer result;
3. one `domain_adjudication` using both artifacts.

Do not reuse the writer as its challenger or adjudicator. There is no cost-based role skipping and no
domain folding. A domain with unresolved blockers is recorded as blocked and excluded from confident
cross-domain conclusions; its data gaps remain visible internally.

### Cross-domain synthesis

Dispatch one `cross_domain_synthesis` task after all domain adjudications finish. It preserves canonical
`claim_id`, `action_id`, full `number_tokens`, callbacks and dissent. It must not turn blocked-domain
material into a confident claim or create a new business number.

### Independent visual curation

Dispatch `visual_curation` only after the narrative structure is stable. The curator receives locked
claims plus the deterministic table catalog, not raw authoring control over table cells. Every runtime
view must bind a real claim through `supports_claim` and a deterministic table ID through `source.table`.

Every `decision-critical claim` listed in the brief must have exactly one `visual_coverage` record:
either `retained` with matching `view_ids`, or `omitted` with an allowed reason code and a concrete
reason. If a gate or review removes the last matching view, record `dropped_by_gate` or
`dropped_by_review`; never silently erase the coverage gap.

There is **no per-domain cap** on tables or charts and no quota. Keep every view that earns its place,
but prefer prose-only over a low-value or raw-data view. Registry labels and units are filled later; the
curator must not author them.

The final single HTML also carries a deterministic **经营诊断明细** layer. It preserves available,
non-empty high-value tables for search terms, notes/content, SKU opportunities, channels, audiences and
refunds even when an adversarial review drops every agent-curated view. Long tables stay compact and
numeric columns are sortable in the browser from deterministic sort ranks. This layer is evidence detail,
not permission to expose raw technical tables, bypass metric semantics or duplicate every intermediate.

The final report ends with deterministic **data gaps and unlocked analyses** derived from the frozen
`blocked_modules`, not from agent prose. Merge tasks that need the same data package and show exactly
three reader-facing fields: the data package to provide, its minimum recommended fields/content, and the
analyses unlocked after it is supplied. Never expose internal task slugs or raw table identifiers. Keep
the wording understandable to a non-specialist merchant: prefer everyday Chinese and explain unavoidable
abbreviations on first use. Keep `cannot_say` as an internal safety boundary only; do not render it as a
vague open-questions section.

Split this module into **required current gaps** and **optional capability upgrades**. Required gaps come
from blocked tasks. Optional upgrades come only from registered analysis capabilities whose deterministic
result fields or source-table inventory prove that an optional input is absent. Do not report a field as
missing when the field exists with a real zero. State capability boundaries explicitly: note-to-livestream
visits and payment are supported when their note fields exist, but a standalone livestream overview is
outside the current skill scope and must not be promised as an unlocked analysis.

## Gate and three independent reviews

Advance runs the deterministic gate before review. Any evidence or semantic mismatch is a hard failure:
invented number, wrong fact binding, direction conflict, illegal pool sum, unlicensed causal magnitude,
unknown entity, missing table, invalid column, re-aggregation, or displayed value mismatch.

For each gated section with views, dispatch exactly three review tasks, one per lens:

- `evidence_semantics`
- `merchant_decision`
- `editorial_visual`

Each task returns `review_verdict`. Ingest is idempotent by section + lens, so one lens cannot vote twice.
Reviewers cannot change numbers, claims, actions or views; they only return keep/revise/drop plus named
blockers. A real `supports_claim` anchor is mandatory for every retained view. A section with no strong
view remains prose-only without blocking the report.

## Quality blocker policy

The controller recognizes six blocker classes:

- **evidence** — a conclusion, action or view lacks a valid fact/table anchor;
- **semantic** — name, unit, caliber, period, aggregation, denominator, formula or direction is misread;
- **decision** — the report lacks a clear priority or an action lacks owner, evidence, guardrail or stop rule;
- **visual** — the form is wrong, unreadable, duplicative, a raw dump, or does not prove its claim;
- **continuity** — sections contradict, repeat, lose the spine, or a prose edit changes tokens;
- **delivery** — candidate/final rendering fails, hashes drift, HTML is empty, or more than one report is exposed.

Warnings can remain internal, but a blocker cannot be downgraded because the draft looks polished.

## Targeted revision and convergence

Every repair brief names exactly one `claim_id`, `view_id`, or `action_id`. A patch may replace or drop
that object and cannot overwrite a section or full bundle. After ingest, rerun the affected deterministic
gate and the relevant independent review.

A targeted view replacement or drop must atomically update the view, `visual_coverage` and durable
section state. For an interrupted older run, automatic recovery is allowed only when every pending gate
failure is an orphaned retained view that was explicitly dropped by review. Convert that coverage to
`omitted + dropped_by_review`, preserve the claim, cancel the generated claim patches, and rerun the gate.
Any broader or ambiguous mismatch still requires the normal targeted-revision path.

Allow **at most 2 targeted revision rounds** per target. The bound enforces convergence and prevents
oscillation; it is not a cost optimization. After two failed rounds:

- drop a non-critical claim/view/action when the report remains truthful and useful;
- set the run `blocked` when the target is load-bearing or the remaining report would mislead.

Never fix a semantic blocker by rewriting a label, unit, caliber, period or aggregation in prose. Correct
the ID binding or drop the target.

## Continuity

Once evidence, semantic, decision and visual blockers converge, dispatch continuity over the complete
draft. Ingest only `continuity_edit[]` entries whose target substring is unique and whose digit and token
multisets are unchanged. Reject an edit that changes confidence, causality, action conditions or registry
semantics.

## Candidate HTML and merchant final review

The deterministic renderer writes **candidate HTML** as an internal artifact after continuity and a fresh
gate. Validate that it is non-empty, parseable, numerically identical to the frozen facts, and includes
all retained claims/actions/views. Every retained view must emit one escaped `data-view-id`; a missing or
duplicate marker is a delivery failure. Record the bundle, Markdown and candidate HTML hash before review.

Only then dispatch **merchant final review**. The reviewer reads the actual candidate HTML, evaluates it
as a merchant, and **cannot edit** the artifact. It returns pass/revise with concrete IDs. A revise
verdict returns only named targets to the bounded targeted-revision loop; the new candidate must be
re-gated and reviewed again. A delivery failure is always fail-closed.

## Finalization and delivery

On a merchant pass, run the final deterministic gate against the exact candidate hash and atomically
promote it. The final bundle hash and HTML bytes must match the merchant-reviewed candidate HTML hash.
Mark `finalized` only after the final file exists, is non-empty, parses, matches frozen hashes, has the
exact report `<title>` and unique `<h1>`, contains no unresolved `{tN}` or external dependency, passes
chart/number validation, and its production directory contains exactly one HTML.

The user receives **one final HTML**. Markdown, facts, tables, prompts, task briefs, gate reports, review
verdicts, revision logs, candidate HTML and frozen sidecars are **internal only**. Do not deliver a facts
edition, review appendix or second HTML beside the report.

The final HTML stays concise. It uses registry-validated names, numbers and units. It has no HAR catalog,
no field-definition appendix and no **inline field glossary**. A short registry-owned **tooltip** is
allowed when it improves understanding without cluttering the page.

## Degradation

After an explicit decline, first run the same `narrative prepare` command with
`--multi-agent-declined` instead of `--multi-agent-authorized`, then run
`xhs-ca narrative finalize-deterministic --run-dir <dir> --reason denied`. If the host truly lacks
sub-agent capability, prepare with `--multi-agent-unavailable` and finalize with `--reason unsupported`.
Gate exhaustion or unresolved load-bearing blockers
may route to the deterministic fallback. Stale hashes stop the run; renderer failure or a missing/invalid
final HTML sets `delivery_failed` and reports the exact error rather than claiming a fallback succeeded.

When its renderer succeeds, the fallback is built from verified facts and deterministic tables and
delivers one final HTML. It never exposes the fact layer as a second user-facing report and never labels
a failed candidate as finalized.
