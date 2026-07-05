# Hybrid Report Writer — Design Spec

**Date:** 2026-07-06
**Goal:** Make the auto-generated 经营诊断报告 read like a valuable analytical document a
merchant *understands their business* from — not a filler+data dump — while keeping every number
deterministically trustworthy. A deterministic analysis layer produces rigorous facts; an
**in-skill multi-agent orchestration** (a small agent DAG, not one writer) produces the merchant
narrative; a deterministic gate blocks fabricated numbers/entities/slices (but never muzzles a
tagged judgment).

## North Star

> **这份报告首先是一份把生意讲透的分析读物** —— 用商家的语言讲清「这三个月发生了什么、拆开是
> 什么结构、为什么(标几成把握)、值多少钱」。店主读完是**真正理解了自己的生意**,而不是只拿到
> 一串待办。行动建议是这份理解的**自然落点**,不是取代理解的清单。

Consequences that separate this from both the current bad report and the reference:

- **分析结论是正文,要被读的** —— 每个业务域是一段有解读、有结构、有洞察的叙事(像参考报告那样
  值得读),默认展开。渐进披露只藏**深层证据**(SQL / 置信区间 / 机器键 / 方法学 / 口径推导)。
- **首屏是导读/执行摘要,篇幅随实际结论而定**——主线该几句就几句(通常 1–2 句),盘面有几条**够格
  的真结论**就列几条(不硬凑成固定三行、也不为塞进模板而砍掉结论),本周重点只放真正够格的动作;
  是引子不是全部,读者被引着读完整份分析,而非「90 秒扫三张卡就关掉」。**内容驱动详略,不硬凑不硬删。**
- **大胆下结论,弱因果只贴标签**(见「结论与置信纪律」)。

---

## Grounding: real capability × data ceiling (verified 2026-07-06)

Against the real built DB `.xhs-ceramics-analytics/analytics.duckdb`:

**Producible (13, coverage-confirmed), all weak causal evidence except `data_quality` (strong):**
`data_quality_check, account_baseline, reshoot_repost_candidates, weekly_business_review,
refund_structure_diagnosis, core_business_diagnosis, demand_funnel_diagnosis,
search_efficiency_diagnosis, audience_structure_diagnosis, note_commercial_diagnosis,
sku_structure_diagnosis, channel_structure_diagnosis, refund_root_cause_diagnosis`.

**Blocked (13) — become the honest 解锁清单 (§7):** paid traffic & ad quality (缺 `ad_performance_daily`);
SKU counterfactual lift / response curve / product opportunity (缺 `daily_sku_sales`);
cover / copy / interaction / portfolio (缺 `content_features`); comment demand (无评论);
note_funnel (笔记表缺 `impressions`).

**Real tables:** `business_overview_daily`(91 行/日), `business_overview_monthly`(3 行),
`note_metrics`/`notes`(1272), `refund_overview`(**1 行** = 「全部」rollup),
`search_overview`(182)/`search_terms`(455), `shop_page_funnel`(150)/`shop_page_source`(390),
`sku_performance`(5250), `traffic_source`(62). **No** `daily_sku_sales` / `content_features` /
ad / comment tables.

**Two load-bearing facts, verified against the real data (not assumed):**

1. **Visitor caliber.** `business_overview_daily` carries BOTH `product_visitors` (商品访客 UV) and
   `total_visitors`. The reference report's 人均 GMV `¥2.39→¥1.90` and 流量 `+16.6%` use
   `total_visitors`, which does **not** reconcile with the shop's 4.6% pay conversion. Recomputed on
   `product_visitors` (verified): per-visitor GMV **¥10.01→¥8.68**, traffic **+6.9%**, and
   buyers/product_visitors = **4.63/4.74/4.45%** ≈ 后台 4.6% (self-consistent). This caliber is the
   report's #1 credibility foundation.

   | 5→6月 | 商品访客口径(采用) | 总访客口径(参考报告误用) |
   |---|---|---|
   | 访客环比 | **+6.9%** | +16.6% |
   | 人均GMV | **¥10.01→¥8.68** | ¥2.39→¥1.90 |
   | 客单价 | ¥211→¥195 | 同 |

2. **Refund slices.** `refund_overview` has only pre-ship / post-ship / return split
   (`pre_ship_refund_amount` **¥129,019** / `post_ship` ¥79,344 / `return` ¥57,660,
   total `refund_amount_pay` ¥208,364). There is **no 退款原因 column and no 30-min time column**.
   The reference report's 「多拍89% / ¥185,851」 and 「30分钟内49.3% / ¥102,083」 **do not exist in
   this data**. Refund money-sizing is therefore scoped to the pre-ship pool only.

The data supports rich **descriptive/structural** analysis but only **weak causal** evidence
(single window, no control group, no click→order link). This ceiling *justifies* the report's
honesty discipline — and equally justifies the North Star: the reading value is structural
understanding, and causal calls are made but tagged.

---

## Conclusion & confidence discipline (the core policy)

**大胆判断,数字必须为真.** Weak causality must NOT stop the writer from concluding.

**Give conclusions boldly (tag calibrates, never suppresses):**

- Every section ends on a decisive conclusion + recommendation, including causal/mechanism
  judgments ("6月客单价下滑主要来自高价礼盒占比走低" / "兴安岭内容大概率在带动鱼盘成交").
- Every conclusion carries a confidence tag **强 / 中 / 弱**, derived from the underlying fact's
  `evidence_strength` (causal) × `descriptive_reliability`:
  - **强** — 描述性事实 / 会计恒等式 (LMDI 桥) / 日级显著 (Welch t)
  - **中** — 结构性推断,样本尚可
  - **弱** — 单窗口因果推断 / 相关性 / 小样本 / 自选样本
- Weak conclusions are stated plainly in the body with a trailing 弱 tag. **No visual suppression**
  (no grey/dashed de-emphasis, no folding a conclusion into a drawer just for being weak).

**Hard-blocked by the gate (these are TRUTH violations, orthogonal to boldness):**

1. A magnitude number whose token is not byte-equal to a real `fact.rendered` → 编造/贴错 → hard fail.
2. A product/series/entity not present in facts → 发明实体 → hard fail.
3. Citing a data slice that does not exist (退款原因 / 30-min) → `fact_id` won't resolve → hard fail.
4. A **quantified** attribution stated as established fact where no link exists (e.g. "笔记X带来
   ¥Y成交") → hard fail. A **directional** judgment ("该系列大概率带动鱼盘,弱") is allowed. A
   co-occurrence number must be labeled correlational ("与该系列同期的鱼盘成交约¥X,相关非归因").
5. Summing incompatible recoverable pools into a single net total → hard fail (use 不可加横幅).

**Warn / auto-annotate (confidence, not truth):**

- A causal/mechanism claim missing its confidence tag → warn + require tag (never delete the claim).
- A sizing number missing its caliber/assumption label → warn.

This reconciles with the project hard rule "no deterministic note→order attribution": a *tagged weak
judgment* is not deterministic attribution; only a *quantified attributed number presented as fact*
is, and that stays hard-blocked.

---

## Architecture: deterministic facts → multi-agent writer → deterministic gate

```
[L1] Deterministic analysis (existing 13 modules, unchanged Finding/AnalysisResult contract)
   │      + new computed intelligence (money.py / guardrails / significance / concentration)
   ▼
[L2] facts_export.py → facts.json (the ONLY source of number strings)
   │      每 ¥/¥% carries {fact_id, value(raw,NOT hashed), rendered(取整串,Python-owned),
   │      metric_key, unit, caliber, denominator, assumption?, evidence_strength,
   │      descriptive_reliability, entity_type, direction(Python vs prior), pool_id?}
   │      + entity_registry(真名) + non_additive_ledger + absent_link_registry(退款原因/30-min/
   │      note→order) + module_reading{task→已被 merchant-voice 打磨的 conclusion/action/caveats}
   │      + blocked_modules[] + shared_spine_facts[] + domain_slices{}
   ▼
[cache] key=(facts_hash, narrative_schema_version, renderer_version)
   │      HIT → 跳过整个 agent 层,0 次 LLM 调用,纯 Python 重渲染冻结叙事
   ▼ (miss) ───────────────────────  L3 多 agent 编排(见下一节)  ───────────────────────
   │   [判断层] Seed 主线假设器 → [起草层×≤6] Fan 域写手(并行) → [判断层] Confirm 综合器
   ▼
[gate] factcheck_gate.py 一次性后置全量校验(纯 Python,非 agent)
   │      硬拦真假违规 / 自动封顶 confidence / 仅告警不压制;硬拦→定向补丁 agent(0–2,≤2轮)
   │
   ├─ pass → render-draft(Python 把 {tN} 逐字填 fact.rendered)→ [判断层] Continuity 全篇连读
   │         → finalize(套 edit-pairs 过机械契约 → 复校 → 冻结 frozen_narrative override)
   │         → render-frozen(md+html,render-time 复校)+ 审计底稿(独立字节确定性 .md)
   └─ exhaust → 确定性骨架(partial-first;降级段 body = 已打磨的 module_reading)
```

**Why structured claims + placeholder tokens:** the writer's sentences carry opaque `{t0}{t1}…`
(no digits); Python fills each from `number_tokens[i].fact_id → fact.rendered` at render time, so a
fabricated number-string is *unrepresentable*. This replaces the hardest, least-reliable gate
component (extract Chinese numbers from prose + tolerance-match) with structural checks on declared
tokens. **The writer owns wording; Python owns rounding; the gate owns truth.** This is the same
`{…}`-preservation contract already shipped in `merchant_voice_workflow.js` (verbatim-`old`, every
`{…}` interpolation preserved, no new numbers) — the `{tN}` gate is that contract, generalized.

---

## L3 orchestration: the in-skill multi-agent writer pipeline

Chosen by a 6-topology / 4-judge / 3-critic design pass (unanimous winner `section-parallel +
spine synthesis`, with `spine-first` grafted as the Seed stage; all three adversarial critics
returned *revise*, and their fixes are folded in below). **~9 base agents per fresh report**
(1 Seed + ≤6 writers + 1 Synthesizer + 1 Continuity), ~10–11 typical with one patch/re-dispatch,
~14–16 worst-case bounded; **cache-hit re-runs = 0 agents**.

### Agent DAG

Model column is **runtime-neutral role tier + reasoning effort**, never a hard-coded model id — see
「Harness portability」below. Judgment tier = strongest model the host exposes + high effort; draft
tier = standard model + medium effort.

| Stage | Role | Agents | Tier / effort | Consumes | Produces |
|---|---|---|---|---|---|
| Seed | 主线假设器 | 1 | judgment / high | facts.json **数字与结构 only** (never module prose) | `spine_brief`:会计骨架 `decomposition_backbone[{link_id,from,to,anchor_fact_ids,relation}]` + `headline_candidate` + `section_callbacks{domain:{must_connect_to,angle_hint}}` + `broadcast_facts[~6]` |
| Fan | 域写手 | ≤6 | draft / medium | 自己 `domain_slice`(facts+module_reading)∪ `broadcast_facts`(只读)+ 本域 callback | `section_bundle`:`claims[]` + `table_ref`/`chart_ref`(指向 L1/L2 产物,不重算)+ `spine_alignment` + 强制 `spine_dissent?` |
| Confirm | 综合器 | 1 | judgment / high | 全部 `section_bundle` + `spine_brief` + dissents + candidate_actions + blocked_modules | `narrative_bundle`:`spine_final` + 首屏(0)因果主线/盘面/本周重点**(篇幅内容驱动,不硬凑不硬删)** + CANNOT-SAY(7) + callbacks + `tag_provenance` |
| Gate | factcheck_gate.py | 0 (Python) | — | 装配后的 `narrative_bundle` + facts + ledgers/registries | `gate_report`(硬拦/封顶/告警) |
| Patch | 定向补丁 | 0–2 | draft / medium | `gate_report.hard_failures[]` + 出错 claim + 该 fact 的 copy-paste rendered | 修正后 claim splice 回 bundle,复校 |
| Continuity | 全篇连读+统一嗓音 | 1 | judgment / high | **已填好数字的 9 段成稿**(render-draft 之后) | `continuity_edit[]` edit-pairs(只改句子),过机械契约后复校 |

Deterministic Python steps (0 agents) bracket the agents: `facts_export` → cache-check →
`render-draft` → `finalize`/`render-frozen` → 审计底稿.

### Handoff atoms (schema-validated JSON, sorted keys, never free prose)

- **fact** (L2, immutable, only number-string source) — fields as in the L2 box above.
- **spine_brief** (Seed → writers+synthesizer) — the accounting backbone + broadcast set.
- **claim** (the atom) — `{claim_id, section_id, claim_kind∈measurement|mechanism|sizing,
  sentence(opaque {tN}, NO digits), number_tokens:[{token_id, fact_id, expected_metric_key,
  direction}], entity_refs[], confidence 强/中/弱, causal_link?:{from_entity_type, to_entity_type,
  quantified:bool}(mechanism only), next_test?, spine_ref?}`. Downstream invariants: Python fills
  `{tN}` from `fact.rendered`; gate asserts `fact.metric_key==expected_metric_key`,
  `fact.direction==token.direction`, `entity_refs⊆registry`, `confidence≤max(anchor
  evidence_strength)`.
- **section_bundle** (writer → synthesizer), **narrative_bundle** (synthesizer, what the gate
  validates & freezes), **gate_report**, **continuity_edit** `{claim_id, old, new}`,
  **frozen_narrative** = canonical `{schema_version, facts_hash, renderer_version, narrative_bundle}`
  stored beside `mapping_overrides.yaml` (the shipped frozen-judgment override pattern).

### Causal spine = descriptive-accounting backbone (not a causal chain)

The backbone facts are **arithmetic identities**, not causal claims: the LMDI GMV bridge and
per-visitor-GMV `¥10.01→¥8.68 = f(UV +6.9%, 客单价 ¥211→¥195, conversion)`, 客单价 as a ratio,
refund `¥129,019` as a sum — measurement facts with strong *descriptive* reliability, so the
load-bearing structure is defensible-by-construction. Causal arrows (退款→客单价, 内容→流量) ride
on top as `relation=weak_causal_overlay`, each a mechanism claim whose confidence is **Python-capped
at WEAK** — bold but honestly tagged, never the backbone. So the least-defensible claim class is
structurally **non-load-bearing** (this is the answer to the statistician-critic's "seeding
causation from numbers on no-control data").

- **Broadcast resolves the slicing-vs-callback tension:** every writer sees its `domain_slice ∪
  broadcast_facts` (~6 read-only spine fact_ids), so shared quantities are visible to all writers
  that must call them back, while fabrication-isolation still holds for every non-spine fact. Which
  fact_ids leak is *explicit and tested*, not undefined.
- **Spine-sanity precheck (Python, before the fan barrier):** every backbone anchor must be
  fact-grounded and all four report pillars (大盘/退款/流量内容/商品或用户) present; 1 retry of the
  Seed agent, else degrade — so the fan never runs against a malformed spine.
- **spine_dissent = bottom-up honesty valve:** a writer whose slice's observed direction exceeds its
  assigned node past a threshold *must* report it — a counterweight to seed anchoring.
- **Confirm re-dispatch, not bolt-on callbacks:** when a spine link changes materially the
  synthesizer re-dispatches *only* the affected writers with a revised `angle_hint`
  (emphasis-realignment, ≤3 writers, ≤1 round), closing the "story-B headline over story-A bodies"
  seam that pure callbacks leave open.
- **Coherence has three deterministic backstops** (MISSING_SPINE_CALLBACK presence,
  cross-section DIRECTION_CONFLICT, REDUNDANT_HEADLINE dedup) **plus the honest non-checkable
  remainder** (voice/flow/emphasis) delivered by the Continuity read. We explicitly do **not** claim
  "reads as ONE story" is machine-checkable — only presence/direction/redundancy are; true unity is
  *produced* by the Continuity pass, not asserted by a lint.

### Gate placement & the bounded rewrite loop

`factcheck_gate.py` is pure Python, **never an agent**, at two positions:
- **(a) full post-assembly pass** — one `xhs-ca gate narrative_bundle.json` computes section-local
  rules (MISSING_FACT, METRIC_MISBIND, INVENTED_ENTITY, NONEXISTENT_SLICE, MAGNITUDE_UNBOUND) *and*
  cross-section rules that only make sense globally (DIRECTION_CONFLICT vs Python-computed fact
  signs; SUMMED_POOLS vs `non_additive_ledger`; QUANTIFIED_ATTRIBUTION via the explicit
  `causal_link{from,to,quantified}` vs `absent_link_registry` — replacing the gameable note+order
  type-mixing heuristic, so a hedged dual-reference passes and a dropped-fact_id evasion can't hide
  the link; DANGLING_CALLBACK; REDUNDANT_HEADLINE). **Confidence is capped deterministically**
  (`claim.confidence ≤ max anchor evidence_strength`, CONFIDENCE_CAPPED logged) — the honesty
  mechanism that let us *delete* the nondeterministic "spine skeptic" agent the topologies proposed.
- **(b) render-time re-gate** — `xhs-ca render-frozen` refuses HTML unless the embedded gate_report
  is PASS and re-validates against the stored `facts_hash` (tamper-evidence). Continuity edits are
  re-gated after application.

HARD-FAIL blocks render; WARN attaches as a visible caveat, never suppressed (bold conclusions
survive; only truth violations block; weakness is only ever a 弱 tag). **Rewrite loop is bounded and
always targeted:** full-gate ≤2 rounds routed to the owning node (section→its writer;
section0/7/callback/summed-pool→synthesizer), spine-mismatch ≤1 round (affected writers only),
continuity ≤1 re-gate. **Warnings never trigger rewrites.** Hard exit: gate pass → freeze; budget
exhausted → degradation.

New WARN codes that fight *timidity* (the North Star's bold-judgment mandate): **MISSED_MECHANISM**
(a mechanism fact is available but no mechanism claim was made) and **UNTAGGED_MECHANISM** — both
nudge toward *making* the tagged call, never toward deleting it.

### Harness portability (Claude Code AND Codex — no hard model/primitive binding)

**The skill must run on any host that can spawn sub-agents (Claude Code, Codex, …), so nothing in the
per-report path may hard-bind an Anthropic model or a Claude-Code-only orchestration primitive.**
Portability is achieved by splitting the pipeline into a host-neutral core and a thin host adapter:

- **Host-neutral portable contract (the bulk of the work):**
  1. **All deterministic Python** — `facts_export` / `gate` / `render-draft` / `finalize` /
     `render-frozen` / `skeleton`, exposed as `xhs-ca` subcommands — is 0-agent CLI and runs
     **identically under any host**. This is >half the system and is fully portable by construction.
  2. **The agent DAG + handoff JSON schemas + the agent prompts** live in **host-neutral skill
     assets** (`assets/xhs-ca/orchestration/`: `dag.md`, `schemas/*.json`, `prompts/*.md`), NOT
     baked only into a `.js`. Any host reads the same contract.
  3. **Model selection = role tier + reasoning effort**, never a model id: `judgment/high` and
     `draft/medium`. Each host maps the tier to its own strongest/standard model at dispatch; effort
     (high/medium) is the portable knob both Claude Code and Codex expose. `narrative_schema_version`
     hashes the prompts+schemas+tiers (not model ids), so the same contract is one cache key across
     hosts.
- **Thin host adapter (the only host-specific part):**
  - **Claude Code** — an optional convenience `report_writer_workflow.js` beside
    `merchant_voice_workflow.js` = `pipeline(seed → parallel(≤6 writers) → synthesizer)` using the
    shipped `pipeline()/parallel()/agent({label,phase,effort,schema})/log()` primitive; patch +
    Continuity via the Task tool. `agent()` nodes run in-session (offline/no-key, as merchant_voice
    does). The `.js` merely reads the neutral prompts/schemas — it is an accelerator, not the source
    of truth.
  - **Codex** — the orchestrating agent drives the **same DAG** via Codex's own subagent mechanism
    (per `superpowers/using-superpowers/references/codex-tools.md`), reading the same neutral
    prompts/schemas. No `.js`, no Workflow tool required.
  - **Universal fallback** — a host with *no* subagent primitive runs the DAG as **sequential
    in-session role-passes** (same prompts, same schemas, same gate): correctness identical, latency
    up (≤6 writer passes serialize), agent-call count unchanged. And the deterministic **skeleton**
    always delivers a full artifact with **zero agents**, so even an agent-less host produces the
    two-file deliverable.

> **Not claimed:** a shipped per-report agent orchestration on *any* host — SKILL.md's `run auto` is
> pure Python / 0 agents today. We claim (a) a reusable, proven Claude-Code primitive, (b) a
> host-neutral contract, and (c) a degradation floor that needs no agents at all.

### Skill-runtime wiring

- **SKILL.md gains ONE step 7b「Compose merchant narrative」** between step 7 (`run auto` now also
  emits facts.json) and step 9, written host-neutrally: cache-check `(facts_hash,
  narrative_schema_version, renderer_version)` → on miss, **fan out the DAG using your host's
  subagent primitive** (Claude Code: the `.js`/Task; Codex: its subagents; else: sequential
  in-session) per `orchestration/dag.md` → `xhs-ca gate` → 0–2 targeted patch agents on hard-fail →
  `xhs-ca render-draft` → one Continuity agent → `xhs-ca finalize` → on exhaustion `xhs-ca skeleton`.
- New Python + `orchestration/` assets + the optional `report_writer_workflow.js` auto-mirror into
  `skills/data-analyze-for-zcl/assets/xhs-ca/` via the existing `scripts/bootstrap` rsync mirror set.
- **`merchant_voice_workflow.js` is retired from the delivery path** (kept as a dev-time,
  Claude-Code-only tool that polishes source prose = the skeleton floor + a writer voice-exemplar),
  so per-report cost is **not additive** — the honest figure is 0 → ~10 agents on every fresh report,
  ~0 on cached re-runs.

> **Precedent-honesty note.** The design leans on an "`apply_voice_edits` contract". Verified
> in-repo: the `{…}`-preservation *contract* is real and shipped inside `merchant_voice_workflow.js`
> (this is the direct precedent for the `{tN}` gate), **but there is no shipped `apply_voice_edits`
> Python function** — the emit-JSON → apply-verbatim-in-Python *applier* is **new** work. The spec
> treats the contract as proven and the Python applier (`finalize`'s edit-application + the mechanical
> `{tN}`/digit-multiset check) as a new component built to that proven contract.

---

## Report blueprint (9 sections)

Body = the analytical read (interpretation + ONE focused table with real names + chart + tagged
conclusion + action). Drill-down `<details>` = deep evidence only.

0. **首屏导读**(篇幅内容驱动,不硬凑不硬删)— 因果主线(单一 UV 口径,内联「(与后台4.6%转化同
   口径)」;通常 1–2 句,复杂就多说一句,别为字数硬缩)+ 盘面(有几条**够格结论**列几条,不锁死三行)
   + 本周重点(只放真正够格的动作,数量由结论定,不补位不截断)。指向下文,不是终点。无图。
1. **生意大盘·月对月** — 4/5/6月 GMV 与 商品访客UV/人均产出/客单/转化;LMDI 三因子拆解
   (流量+¥3.0万 / 转化−¥2.8万 / 客单−¥3.4万,残差=0);效率上限反事实 ≈¥6万/月(敏感带,标上限);
   剪刀差 hero 图。
2. **退款与售后** — 退款¥20.8万→发货前¥12.9万/发货后¥7.9万(退货¥5.8万)瀑布;误拍磁铁 SKU 真名短名单;
   发货前池=可拦上限、可挽回率未知(不估);原因/时点切片→§7 解锁。
3. **流量与内容** — 图文¥45.6万/1237篇 vs 视频¥7千/35篇(每篇视角破 base-rate,标「样本小、相关非归因」);
   搜索品牌词 vs 泛词象限。内容一律「相关」+ 置信标签,可下判断不可给归因数字。
4. **商品结构** — SKU 帕累托(前X%=Y% GMV);高GMV×高退款 SKU 交叉点名(真名+价格带,去机器键);
   价格带×(转化,退款)网格。
5. **用户与需求** — 新客/老客转化对比(先过 two_proportion,不显著就明说)+ 幸存者偏差标注;
   店铺页漏斗(明确仅6月);人群画像标「截图来源、未自动导入、仅供参考」,不支撑首屏动作。
6. **实验与下周行动** — 周×工作线,每格绑一个 7月导出可复核目标(人均产出¥8.7→朝¥10.0 等),
   标「向5月方向、基线是否正常待第二季验证」;每个待验证结论落成一条 next_test 实验。
7. **暂时答不了的问题** — CANNOT-SAY + 精确解锁,区分永久不可解(笔记→订单归因:平台无链路)vs
   补数据可解(退款原因/时点、人群、投放、SKU日销、内容特征、评论);blocked 的 13 模块归此。
8. **口径与方法** — 全报告唯一术语区(LMDI/Wilson/Welch/残差)+ 那句「单窗口无对照组不能断因果」
   只说一次 + 访客口径定义 + 阈值提示线取值(标「政策/经验线,非行业基准」)+ 审计底稿入口。

---

## Computed intelligence (grounded, mapped to real tables)

| 能力 | 来源表 | 可行 | 说明 |
|---|---|---|---|
| 访客口径对账台账 | business_overview_daily | ✅ | 效率¥只用 product_visitors,与4.6%对账,total_visitors 隔离 |
| 月历 LMDI GMV 桥 | business_overview_daily(日聚合) | ✅ | ΔGMV=流量+转化+客单,残差=0;弃前/后半程 |
| 6月效率上限反事实 | 月度 UV + 人均GMV | ✅ | ≈¥6万,=桥的转化+客单负贡献之和;标「上限/乐观」+ corr(访客,人均)=−0.40 |
| 日级效率显著性 | business_overview_daily(91日) | ✅ | Welch t(5月 vs 6月人均GMV);显著才让主线=强 |
| 发货前退款可拦池 | refund_overview.pre_ship_refund_amount | ✅ | ¥12.9万边际,不乘不存在的切片,不估恢复率 |
| 非叠加可回收台账 | 上述各¥ | ✅ | 按¥中位数排序 + 可控度分列 + 不可加横幅,无净总额 |
| 阈值提示条 | 退款率/人均GMV环比/复购占比/搜索份额 | ✅ | 显示实测值+提示线,仅测量指标,per-visitor 挂显著性 |
| 置信标签路由 | fact 双轴 + claim_kind | ✅ | 强/中/弱,挂 claim 对象,不改 Finding 契约 |
| 图文/视频对比 | note_metrics | ✅ | base-rate 诚实(每篇视角) |
| SKU 帕累托集中度 | sku_performance(5250) | ✅ | concentration.py 加 cumulative_curve() |
| 下期目标反算 | 当前值 | ✅ | 绑7月可复核,标季节性未知 |
| 复购缺口 | demand_funnel/shop_page(需核列) | ⚠️ | 先过 two_proportion 才 sizing,标幸存者偏差+结构天花板,不上首屏 |
| 泛词可捕获¥ | search_terms | ❌ | 删除¥头条数(意图≠承接页),只留承接页 A/B 解锁项 |
| 跨周押注追踪 | 需历史快照 | ❌(deferred) | 单次导出管线不具备 |

---

## Writing constitution (revised)

1. **单口径铁律** — 人均/效率¥只用 product_visitors,与4.6%对账;total_visitors 禁入效率计算。
2. **先钱后机制** — 句子以¥和方向开头,不以指标定义开头。
3. **大胆下判断 + 置信标签** — 每段给决断性结论(含因果),挂 强/中/弱;弱不等于不说,只是贴标签。
4. **测量 vs 估算排版隔离** — 计数/份额=硬样式;效率上限/退款池等 sizing=浅色/虚框/「估」角标,
   首屏不与硬数据相邻显得同等确定。(注:这是**排版**区分,不是把弱结论藏起来。)
5. **不乘边际、不加不同口径池** — 只用 marts 可算单元;不存在的切片进解锁清单;可回收池并列不相加。
6. **动词先行、每段落在动作** — 平台能力相关动作先写「确认千帆是否支持X」+ 净ROI 提醒。
7. **日历不统计** — 一律 4/5/6月,绝不前/后半程/split-half。
8. **真名不哈希、取整由 Python 做** — 兴安岭之夜/鱼盘/抹茶碗;¥208,364→¥20.8万 由 Python 预渲染,
   写作者逐字采用、禁止再取整(保字节一致)。
9. **一数一义、内联、只说一次** — 「人均产出¥10.0→¥8.7」,杀掉每数字自带定义的词典 style。
10. **相关性硬约束** — 内容/笔记类可下方向判断(带 弱标签),但不得给具体归因数字当既成事实。
11. **base-rate 与幸存者偏差诚实** — 小样本(视频35篇)判「没测够」非「没用」;自选样本(老客)标偏差。
12. **目标不锚死基线** — 7月目标写「向5月方向回收」+「5月本身可能非正常基线」。
13. **术语只进 §8 与底稿** — 正文/卡片零术语;每个待验证结论带 next_test。

---

## Format decision

- **两产物不合并.** Byte-identical 作用域收窄到**确定性产物**(facts JSON / 审计底稿 / SVG 快照)
  与「HTML from (facts + frozen_narrative override)」。frozen_narrative = 通过门禁的结构化叙事,
  以三元键 **(facts_hash, narrative_schema_version, renderer_version)** 持久化在
  `mapping_overrides.yaml` 旁。**不再宣称 HTML 从裸导出可复现.**
  - `facts_hash` = sha256(仅 Python-owned `rendered` 串 + 结构/枚举字段 + registries/ledgers,排序
    键;**裸 float `value` 完全排除**,否则 8.68 vs 8.6800001 浮点噪声会让缓存反复失效重烧 agent 层)。
    golden-hash 单测钉住规范化字节、跨两个解释器版本、作为合并门。
  - `narrative_schema_version` = hash(写手/综合/Continuity 提示词 + 所有 handoff schema + 共享嗓音块
    + 门禁规则集);`renderer_version` = hash(charts/html/markdown/formatting/field_labels/labels)。
    二者变更即使旧叙事失效、绝不静默发旧字节。命中三元键 → 跳过整个 agent 层、0 次 LLM。
- **渐进披露** = 原生 `<details>/<summary>`,全静态(无时间戳/随机id/JS 排序);一个 state-free
  「审计视图」全局展开开关。图表内联 SVG,`<title>` 悬停数值,零 JS 图表库。
- **图表**:复用现有 SVG 库,两处真代码改动 + 新快照 —— (a) 剪刀差 hero 用 `_line`,须加
  `suppress_aggregate` 关掉无意义的粗体均值线;(b) 退款瀑布用 `_vbar` 浮动柱(真·重定位标签)。
  只画可算口径(hero 用 UV;瀑布只到发货前/后可算切段)。拒绝四个全新 builder(快照成本不值)。

---

## Changes to previously-locked decisions

1. **Byte-identical 作用域收窄**(见 Format)——冻结叙事成为持久化 override 输入。
2. **删除**原「单一净可回收总额 + 毛/净重叠对账」→ 改「不可加并列台账」(重叠系数无 ground truth)。
3. **退款可回收 sizing 降范围**到发货前可算池 ¥12.9万;原因/时点切片降为「导入即解锁」(数据不存在)。
4. **结论纪律放宽**(本 spec 核心)——弱因果不再压制/降级/灰化,改为大胆判断 + 置信标签;门禁只硬拦
   真假问题(编造数字/发明实体/引用不存在切片/相加异口径池/带数字的既成归因)。
5. **写作层从「单 in-session 写作者」改为「skill 内多 agent 编排」**(本轮核心变更)——见「L3
   orchestration」节。Seed(判断层)→Fan(≤6 起草层并行)→Confirm(判断层)→Gate(Python)→
   Continuity(判断层)。原设想的「主线怀疑者 agent」被**纯 Python 的 confidence 封顶规则替代**(对每条
   claim 生效、更便宜、不可绕过)。写手句子只含不透明 `{tN}`,数字由 Python 逐字填 `fact.rendered`。
6. **不绑定 Claude 模型,skill 须能在 Codex 运行**(本轮新增)——见「Harness portability」。模型选择
   一律「角色分层(判断层/起草层)+ reasoning effort(high/medium)」,由各 host 在派发时映射到自己
   的模型;DAG/schema/prompt 落在 host 中立的 `orchestration/` 资产里;`report_writer_workflow.js`
   降为 Claude Code 的可选加速器,Codex 用自己的 subagent 机制跑同一份 DAG,无 subagent 的 host 退化
   为顺序 in-session role-pass;确定性骨架永远 0 agent 兜底。
7. **首屏篇幅内容驱动**(本轮新增)——首屏主线/盘面/本周重点不锁死「一句话+三行」,由实际够格结论
   决定详略,不硬凑不硬删。

保留全部硬约束:无 note→order 归因数字、模块优雅降级不编造、中文非技术口径、每个正文数字可追溯
computed fact。

---

## New / modified files

- **New (deterministic Python, all under `reporting/`):** `facts_export.py` (facts.json +
  registries/ledgers + module_reading + facts_hash canonicalization), `money.py`,
  `money_ledger.py`, `guardrails.py`, `trust_routing.py`, `factcheck_gate.py` (the structural
  validator + confidence cap), `narrative_render.py` (render-draft / render-frozen / skeleton +
  `{tN}`→`fact.rendered` fill), `frozen_narrative.py` (override read/write + version keys),
  `first_screen.py`.
- **New (host-neutral orchestration contract):** `assets/xhs-ca/orchestration/` — `dag.md` (the
  Seed→Fan→Confirm→Gate→Continuity DAG, tiers as `judgment/high`·`draft/medium`), `schemas/*.json`
  (fact / spine_brief / claim / section_bundle / narrative_bundle / gate_report / continuity_edit),
  `prompts/*.md` (per-role, model-agnostic). This is the source of truth every host reads.
- **New (Claude Code adapter, optional accelerator):**
  `.xhs-ceramics-analytics/report_writer_workflow.js` = `pipeline(seed → parallel(≤6 writers) →
  synthesizer)` reusing the `merchant_voice_workflow.js` API; it **reads** the neutral prompts/schemas
  rather than embedding them. Codex/other hosts drive the same DAG via their own subagent mechanism;
  no `.js` required. Auto-mirrored by `scripts/bootstrap`.
- **New (skill glue):** `SKILL.md` step 7b「Compose merchant narrative」, written host-neutrally
  (cache-check → fan out DAG via host's subagent primitive → gate → patch → render-draft → Continuity
  → finalize → on-exhaust skeleton).
- **Modify:** `analytics/confidence.py` (+`mean_diff_test` Welch/CI, stdlib);
  `analytics/concentration.py` (+`cumulative_curve`);
  `reporting/charts.py` (`_line` +`suppress_aggregate`, `_vbar` +waterfall floating bars);
  `analysis/core_business.py` (`_growth_attribution_finding`: split-half → 日历月聚合 → `gmv_bridge`,
  分母锁 product_visitors UV);
  `cli.py` (+typer subcommands: `facts`, `gate`, `render-draft`, `finalize`, `render-frozen`,
  `skeleton`; `run auto` also emits facts.json).
- **Reuse (unchanged, degradation floor):** `reporting/domains.group_by_domain` + `section_order`
  (skeleton section ordering); `reporting/confidence.reader_confidence().de_emphasize` (chart-card
  greying — *descriptive* reliability only, NOT the causal 弱 tag, which renders at full weight);
  `evidence.py` enums (drive the confidence cap).
- `claim_kind`/confidence live on the **claim object**, not on `Finding` → no 30+ module migration.

---

## Error handling & degradation

- Every L1 module keeps its never-raise + graceful-degrade contract.
- **Partial-first degradation.** A single writer/section that exhausts its patch retries degrades
  **only that section** to a skeleton-section (its `module_reading` body + real-name table + chart +
  强/中/弱 chip + one `fact.rendered` caption) under a per-section banner, while the other five keep
  gate-passed narrative — still mostly a read.
- **Whole-report skeleton** only when the full-gate loop exhausts 2 rounds, the spine-sanity
  precheck fails twice, a DANGLING_CALLBACK would leave section0's headline pointing at a
  skeletonized section, or the agent layer is unavailable → deterministic skeleton (facts +
  real-name tables + charts + tags + CANNOT-SAY, section-ordered via `domains`/`section_order`)
  under「本报告为确定性骨架版:叙事层未通过事实校验,数字与表格仍完整可核」.
- **The skeleton body is already merchant-toned**: it reuses each module's
  merchant-voice-polished `module_reading`, so the `feat/merchant-voice-polish` investment becomes
  the deterministic floor rather than orphaned work. Degradation only ever strips *prose* — never
  numbers/tables/charts/tags — so step-9's exactly-two-artifacts check still passes.
- **Telemetry, not silent skeleton.** Per-run counters (degradation-rate, hash-miss,
  skeleton-fallback, per-rule hard-fail counts, degradation reason codes) append to
  `.xhs-ceramics-analytics/report_runs.jsonl` and surface in the skill's step-9 delivery note, so an
  over-strict SUMMED_POOLS/QUANTIFIED_ATTRIBUTION/confidence-cap rule cannot make skeleton the silent
  default; evals assert the counters.
- **Not mid-DAG resumable.** The in-session workflow returns only at the end and the harness exposes
  no checkpoint primitive, so a crash before freeze **re-runs the fresh (bounded ~9–16 agent) DAG**;
  the only persistent checkpoint is the post-gate freeze. Acceptable precisely because the DAG is
  short.
- `refund_overview` 「全部」rollup row → dedup on read. `business_overview_daily` verified rollup-free
  (91 rows = 1/day; daily agg reconciles to monthly). Any newly-ingested table: verify caliber first.

## Testing strategy

- **Deterministic units:** `mean_diff_test`, `cumulative_curve`, `gmv_bridge` calendar-month path
  (residual=0), caliber ledger (UV vs 4.6% reconciliation), pre-ship pool sizing, non-additive ledger
  (no net total), `suppress_aggregate`, waterfall renderer + snapshots.
- **facts_export / determinism:** `facts_hash` **golden-hash** test (canonical bytes stable across
  two interpreter versions; raw `value` float excluded so 8.68≈8.6800001 does not thrash the hash) —
  a merge gate; `narrative_schema_version` / `renderer_version` bump when their hashed inputs change.
- **Gate rule matrix** (each HARD-FAIL + each WARN, one focused case):
  MISSING_FACT / METRIC_MISBIND / DIRECTION_CONFLICT / INVENTED_ENTITY / NONEXISTENT_SLICE /
  QUANTIFIED_ATTRIBUTION (explicit `causal_link` vs `absent_link_registry`) / SUMMED_POOLS /
  MAGNITUDE_UNBOUND / DANGLING_CALLBACK; and WARN-not-block:
  UNTAGGED_MECHANISM / MISSED_MECHANISM / UNLABELED_SIZING / MISSING_SPINE_CALLBACK /
  REDUNDANT_HEADLINE / CONFIDENCE_CAPPED. **A tagged-weak causal judgment must PASS** (bold ≠ blocked).
- **Confidence cap:** `claim.confidence ≤ max(anchor evidence_strength)` capping + `tag_provenance`
  logging; a weak *mechanism* claim renders at full sentence weight while a low-*descriptive*-
  reliability chart card still greys (`reader_confidence.de_emphasize` unchanged) — asserts the two
  axes stay separate.
- **`{tN}` / edit-pair mechanical contract:** render-draft fills every `{tN}` from `fact.rendered`
  with zero numeric derivation; `continuity_edit` application preserves the `{tN}` multiset, adds no
  new digits, and locates `old` exactly once (the shipped merchant_voice `{…}` contract, generalized).
- **Degradation:** partial-section skeleton uses `module_reading` body; whole-report skeleton is
  section-ordered and byte-deterministic; two-file + 底稿 deliverable holds; `report_runs.jsonl`
  counters populated.
- **Determinism (suite-level):** mirror suite stays green (runtime mirror 278 passed + 3 skipped by
  design; main ~619). Same `(facts + frozen_narrative)` → byte-identical HTML+底稿 replay
  (cache-hit = 0 agents).
- TDD throughout: failing test → minimal impl → green; preserve all existing green tests.

## Non-goals / out of scope

- Building blocked modules or their source tables (ad / daily_sku_sales / content_features / comments).
- Cross-period bet tracking (needs persisted history — deferred).
- Any note→order attribution number; any seasonality verdict from 3 months; any recovery-rate estimate
  on refunds; any 泛词 captured-¥ headline number.

## Global constraints

- Python 3.14; `.venv/bin/python` is THE interpreter. Ruff line-length 100.
- Modules never raise; degrade + record. Emoji is real merchant content — never strip.
- No Co-Authored-By trailer. Commit/push/发布 only on explicit user request.
- After code: sync skill mirror (`scripts/sync-runtime`), regen real-data demo, verify two artifacts.
