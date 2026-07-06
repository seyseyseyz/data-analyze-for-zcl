# Narrative Workflow Runbook

This runbook is the control loop the host agent follows to drive the narrative
workflow. The controller is passive: it prepares briefs and durable state and
ingests results, but never spawns. You (the host) own spawning.

## One-time authorization (authorize first)

Before spawning any sub-agent, ask the user once for permission to authorize the
multi-agent narrative writer. If the user declines, skip straight to the
deterministic fallback (see "Degradation").

## The loop

1. **prepare** — run `xhs-ca narrative prepare --run-dir <dir> --name <report>`
   (add `--force` only to intentionally overwrite an unfinished run). This
   writes `state.json` and the seed brief.
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

Route to the deterministic skeleton whenever the LLM path cannot finish:

- **User denied** spawning → run
  `xhs-ca narrative finalize-deterministic --run-dir <dir> --reason denied`.
- **Host cannot spawn sub-agents at all** → same command, `--reason unsupported`.
- **Gate never passes / orchestration exhausted** → `advance` itself routes to
  the deterministic skeleton and sets stage `blocked`; just deliver it.

In every degraded path the deliverable still exists: a "确定性骨架版" report
built from the same L1/L2 data, with module caveats preserved and unanswerable
questions listed explicitly.
