# Narrative Workflow DAG

The narrative workflow turns deterministic Findings (L1) and the single number
source `facts.json` (L2) into a merchant-facing report (L3) through a fixed
sequence of stages. The controller only prepares briefs and durable state; the
host agent spawns sub-agents and feeds their JSON back.

## Stages

1. **seed** — one sub-agent drafts the report skeleton bundle (section shells,
   titles, ordering) from the domain slices. Output: a draft bundle.
2. **fan** — up to six sub-agents (MAX_FAN_AGENTS = 6), one per domain slice,
   write their section prose grounded in the slice facts. Slices beyond the cap
   are losslessly folded into a single "综合参考" slice before fan-out — never
   dropped.
3. **synth** — one sub-agent merges the fan sections into a coherent bundle,
   reusing each fan section's canonical `section_id`.
4. **gate** — deterministic fact-check (no sub-agent). Numbers must trace to
   `facts.json`; causal wording and over-claims are capped. Emits PASS/FAIL.
5. **patch** — on gate FAIL, one sub-agent repairs only the flagged sections;
   the gate re-runs.
6. **continuity** — one sub-agent smooths cross-section transitions; the gate
   runs once more as the final guard.
7. **finalized** — terminal success: `<name>.md` + `<name>.html` written.
8. **blocked** — terminal degraded: orchestration could not complete (host
   declined, gate exhausted, or an unrecoverable state). The controller writes a
   deterministic skeleton report so the deliverable still exists.

## Host neutrality

Briefs and prompts never name a model or vendor. A host that cannot spawn
sub-agents does not attempt the LLM stages at all — it routes directly to the
deterministic skeleton via `finalize-deterministic`. There is no in-session
role-passing substitute for real sub-agents.
