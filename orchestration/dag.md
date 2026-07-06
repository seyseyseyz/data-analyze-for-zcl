# L3 orchestration DAG (host-neutral)

This is the source of truth for the merchant-narrative writer. Any host that can spawn sub-agents
runs this same DAG; a host without sub-agents runs the stages as sequential in-session role-passes.
The deterministic Python layer (`xhs-ca facts / gate / render-draft / finalize / render-frozen /
skeleton`) brackets the agents and is identical on every host.

## Model policy — role tier + reasoning effort, NEVER a model id

- **judgment/high** — the strongest model the host exposes, high reasoning effort.
- **draft/medium** — the host's standard model, medium reasoning effort.

Each host maps a tier to its own model at dispatch. `narrative_schema_version` hashes the
prompts + schemas + tiers (not model ids), so the same contract is one cache key across hosts.

## Stages

| Stage | Role | Agents | Tier / effort | Consumes | Emits (schema) |
|---|---|---|---|---|---|
| Seed | 主线假设器 | 1 | judgment/high | facts.json 数字与结构 only (never module prose) | `spine_brief` |
| Fan | 域写手 | ≤6 (parallel) | draft/medium | 本域 domain_slice ∪ broadcast_facts ∪ 本域 callback | `section_bundle` |
| Confirm | 综合器 | 1 | judgment/high | 全部 section_bundle + spine_brief + dissents + blocked_modules | `narrative_bundle` |
| Gate | factcheck_gate.py | 0 (Python) | — | narrative_bundle + facts + registries/ledgers | `gate_report` |
| Patch | 定向补丁 | 0–2 | draft/medium | gate_report.hard_failures + 出错 claim + 该 fact 的 rendered | fixed `claim` spliced back |
| Continuity | 全篇连读 | 1 | judgment/high | render-draft 之后已填数字的成稿 | `continuity_edit[]` |

## Flow

1. `xhs-ca facts auto` → facts.json → cache-check `(facts_hash, narrative_schema_version,
   renderer_version)`. HIT → `xhs-ca render-frozen` (0 agents). MISS → run the DAG.
2. **Seed** emits `spine_brief`. Spine-sanity precheck (Python, before the fan): every backbone
   anchor fact-grounded and all four pillars (大盘/退款/流量内容/商品或用户) present; 1 retry else degrade.
3. **Fan** — ≤6 writers in parallel, one per producible domain; each sees only its slice ∪
   `broadcast_facts` (read-only spine fact_ids). A writer whose observed direction exceeds its
   assigned node reports `spine_dissent`.
4. **Confirm** assembles `narrative_bundle`. If a spine link changed materially, re-dispatch only the
   affected writers with a revised `angle_hint` (≤3 writers, ≤1 round).
5. **Gate** — `xhs-ca gate narrative_bundle.json facts.json`. HARD-FAIL → ≤2 targeted patch rounds
   routed to the owning node. Confidence is capped deterministically (never an agent). WARN never
   triggers a rewrite.
6. `xhs-ca render-draft` fills every `{tN}` from `fact.rendered`. **Continuity** reads the filled
   9-section draft and emits prose-only `continuity_edit[]` (digit + `{tN}` multisets invariant).
7. `xhs-ca finalize` applies the edits, re-gates, and freezes `frozen_narrative` beside
   `mapping_overrides.yaml`. `xhs-ca render-frozen` writes md+html (re-gates at render time).
8. **Exhaustion** (gate ≤2 rounds fail / spine precheck fails twice / agent layer unavailable) →
   `xhs-ca skeleton` — deterministic 0-agent floor (facts + real-name tables + charts + 强/中/弱 tags
   + CANNOT-SAY), banner「本报告为确定性骨架版」. Every run appends a record to `report_runs.jsonl`.

## Bounds

~9 base agents per fresh report (1 Seed + ≤6 writers + 1 Synthesizer + 1 Continuity), ~10–11 with one
patch/re-dispatch, ~14–16 worst-case. Cache-hit re-runs = 0 agents. Not mid-DAG resumable; the only
persistent checkpoint is the post-gate freeze.
