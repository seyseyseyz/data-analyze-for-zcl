# Narrative Workflow Runbook

This runbook is the control loop the host agent follows to drive the narrative
workflow. The controller is passive: it prepares briefs and durable state and
ingests results, but never spawns. You (the host) own spawning.

## Authorization — ask once, every run (asking is not spawning)

Asking the user to authorize the narrative writer is a **required first step**,
and **asking is not spawning**. A host whose policy forbids spawning sub-agents
without an explicit user request still MUST ask: the user's "yes" is that
explicit request. Never skip the question, and never treat "the user has not
asked for sub-agents yet" as "this host cannot spawn" — that is the mislabel to
avoid. Ask, then branch:

- **Authorized** → proceed to the loop below and spawn.
- **Declined** → deterministic fallback, `--reason denied` (see "Degradation").
- **Host genuinely has no sub-agent capability at all** (there is no spawn
  facility on this host) → deterministic fallback, `--reason unsupported`.
  "I must ask the user first" is NOT this case — ask.

## The loop

1. **prepare** — run `xhs-ca narrative prepare --run-dir <dir> --results
   <state-dir>/results.json --facts <state-dir>/facts.json --name <report>`
   (add `--force` only to intentionally overwrite an unfinished run). Both inputs
   are produced deterministically by the fact-layer step (`xhs-ca run …` or
   `xhs-ca facts …`), which writes `facts.json` **and** the domain-sliced
   `results.json` into the state dir. `results.json` is what the narrative
   consumes — never hand-fabricate it, and never pass `facts.json` as `--results`
   (its `domain_slices` is an always-empty cache field, which caps the run to
   zero sections). This writes `state.json`, `domain_slices.json`, and the seed
   brief.
2. **status** — run `xhs-ca narrative status --run-dir <dir> --json`. The JSON
   tells you the current `stage`, the `next_action`, and which brief files to
   read. Always consult it to decide what to do next; never guess the stage.
3. **map briefs to spawns** — read the brief file(s) named by `status`. For the
   seed/synth/patch/continuity stages spawn one sub-agent; for the fan stage
   spawn one sub-agent per brief (at most six). Give each sub-agent only its
   brief. Require it to return JSON.
4. **ingest** — for each returned result run
   `xhs-ca narrative ingest --run-dir <dir> --stage <stage> --source <file>`
   (or `--section-id <id>` for a single fan section). Ingestion tolerates JSON
   wrapped in code fences or surrounded by prose.
5. **advance** — run `xhs-ca narrative advance --run-dir <dir>`. This moves the
   stage forward (running the deterministic gate where the DAG requires it) and
   updates `state.json`.
6. **branch on status** — re-run `status --json`:
   - `stage == finalized` → done; deliver `<name>.md` + `<name>.html`.
   - `stage == blocked` → the controller already wrote the deterministic
     skeleton; deliver it and report the degradation reason.
   - otherwise → loop back to step 2.

## Degradation

Route to the deterministic skeleton whenever the LLM path cannot finish. Use the
reason that matches reality — the two are not interchangeable:

- **User declined** after being asked → run
  `xhs-ca narrative finalize-deterministic --run-dir <dir> --reason denied`.
- **Host has no sub-agent capability at all** (no spawn facility exists) → same
  command, `--reason unsupported`. Do not use this when you simply have not asked
  yet — asking is not spawning, so ask first.
- **Gate never passes / orchestration exhausted** → `advance` itself routes to
  the deterministic skeleton and sets stage `blocked`; just deliver it.

In every degraded path the deliverable still exists: a "确定性骨架版" report
built from the same L1/L2 data, with module caveats preserved and unanswerable
questions listed explicitly.
