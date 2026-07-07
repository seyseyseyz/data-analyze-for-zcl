# L3 orchestration DAG (host-neutral)

This is the source of truth for the merchant-narrative writer. It turns the
deterministic Findings (L1) and the single number source `facts.json` (L2) into a
merchant-facing report (L3) through a fixed sequence of stages. Any host that can
spawn sub-agents runs this same DAG; a host that cannot spawn sub-agents does not
attempt the agent stages at all — it routes directly to the deterministic skeleton
(see the terminal `blocked` state below). There is no in-session role-passing
substitute for real sub-agents. The deterministic Python layer (`xhs-ca facts /
gate / render-draft / finalize / render-frozen / skeleton`) brackets the agents and
is identical on every host.

The controller (`xhs-ca narrative …`) is passive: it prepares briefs and durable
state and ingests results, but never spawns. The host drives the control loop —
`prepare → status → ingest → advance` — documented in
[runbook.md](./runbook.md).

## Model policy — role tier + reasoning effort, NEVER a model id

- **judgment/high** — the strongest model the host exposes, high reasoning effort.
- **draft/medium** — the host's standard model, medium reasoning effort.

Each host maps a tier to its own model at dispatch. `narrative_schema_version` hashes the
prompts + schemas + tiers (not model ids), so the same contract is one cache key across hosts.

## Stages

| Stage | Role | Agents | Tier / effort | Consumes | Emits (schema) |
|---|---|---|---|---|---|
| seed | 主线假设器 | 1 | judgment/high | facts.json 数字与结构 only (never module prose) | `spine_brief` |
| fan | 域写手 | ≤6 (parallel) | draft/medium | 本域 domain_slice ∪ broadcast_facts ∪ 本域 callback | `section_bundle` |
| synth | 综合器 | 1 | judgment/high | 全部 section_bundle + spine_brief + dissents + blocked_modules | `narrative_bundle` |
| gate | factcheck_gate.py | 0 (Python) | — | narrative_bundle + facts + registries/ledgers | `gate_report` |
| patch | 定向补丁 | 0–2 | draft/medium | gate_report.hard_failures + 出错 claim + 该 fact 的 rendered | fixed `claim` spliced back |
| review | 域策展视图评审(价值/可读性/支撑 三视角) | ≤6×3 (parallel) | draft/medium | 本域 curated_views + supports_claim + 已锁定数值(只读) | `review_verdicts[]` |
| continuity | 全篇连读 | 1 | judgment/high | render-draft 之后已填数字的成稿 | `continuity_edit[]` |

Fan-out is bounded at six writers (MAX_FAN_AGENTS = 6): domain slices beyond the cap
are losslessly folded into a single "综合参考" slice before fan-out — never dropped.

### Terminal states

- **finalized** — success: the gate passed and `xhs-ca finalize` + `render-frozen`
  wrote the two narrative artifacts (`<name>.md` + `<name>.html`).
- **blocked** — degraded: orchestration could not complete (host declined, host
  cannot spawn, or the gate stayed exhausted). The controller writes a
  deterministic "确定性骨架版" report so the deliverable still exists.

## Flow

1. `xhs-ca facts auto` → facts.json → cache-check `(facts_hash, narrative_schema_version,
   renderer_version)`. HIT → `xhs-ca render-frozen` (0 agents). MISS → run the DAG.
2. **seed** emits `spine_brief`. Spine-sanity precheck (Python, before the fan): every backbone
   anchor fact-grounded and all four pillars (大盘/退款/流量内容/商品或用户) present; 1 retry else degrade.
3. **fan** — ≤6 writers in parallel, one per producible domain; each sees only its slice ∪
   `broadcast_facts` (read-only spine fact_ids). A writer whose observed direction exceeds its
   assigned node reports `spine_dissent`.
4. **synth** assembles `narrative_bundle`, reusing each fan section's canonical `section_id`. If a
   spine link changed materially, re-dispatch only the affected writers with a revised `angle_hint`
   (≤3 writers, ≤1 round).
5. **gate** — `xhs-ca gate narrative_bundle.json facts.json`. HARD-FAIL → ≤2 targeted **patch**
   rounds routed to the owning node. Confidence is capped deterministically (never an agent). WARN
   never triggers a rewrite.
6. **review** — after the gate PASSES (every displayed number already byte-verified), each producible
   domain's curated views enter the review stage: spawn 3 reviewers per domain, one per adversarial
   lens (价值 / 可读性 / 支撑), each defaulting to reject a trivial, hard-to-read, or unsupported view.
   Per view, tally the three verdicts by strict precedence — **drop ≥ 2 → drop**; else
   **keep ≥ 2 → keep**; else **patch ≤2 rounds, then drop**. Reviewers judge value/readability/support
   only and cannot change numbers (the gate already locked them); every retained view keeps its
   `supports_claim` and obeys the per-domain cap ≤2 tables + ≤1 chart. A section with zero surviving
   views degrades to prose-only, and a section with no curated views skips review entirely.
7. `xhs-ca render-draft` fills every `{tN}` from `fact.rendered`. **continuity** reads the filled
   9-section draft and emits prose-only `continuity_edit[]` (digit + `{tN}` multisets invariant).
8. `xhs-ca finalize` applies the edits, re-gates, and freezes `frozen_narrative` beside
   `mapping_overrides.yaml`. `xhs-ca render-frozen` writes md+html (re-gates at render time). Stage
   is now **finalized**.
9. **Exhaustion** (gate ≤2 rounds fail / spine precheck fails twice / agent layer unavailable) →
   `xhs-ca skeleton` — deterministic 0-agent floor (facts + real-name tables + charts + 强/中/弱 tags
   + CANNOT-SAY), banner「本报告为确定性骨架版」. Stage is now **blocked**. Every run appends a
   record to `report_runs.jsonl`.

## Bounds

~9 base agents per fresh report (1 seed + ≤6 writers + 1 synth + 1 continuity), ~10–11 with one
patch/re-dispatch, ~14–16 worst-case. When domains carry curated views the review stage adds ≤3
reviewers per producible domain (≤18) plus ≤1 review-patch agent per unconverged view (≤2 rounds);
reports with no curated views skip review and stay at the base count. Cache-hit re-runs = 0 agents.
Not mid-DAG resumable; the only persistent checkpoint is the post-gate freeze.
