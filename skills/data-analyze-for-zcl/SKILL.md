---
name: data-analyze-for-zcl
description: "Xiaohongshu/小红书/千帆 ceramics/tableware export analysis. DuckDB + evidence-scored tasks: weekly_business_review, sku_counterfactual_lift, comment_demand_mining, paid_traffic_efficiency, cover_style_effect, copy_angle_effect, note_funnel, product_opportunity_matrix. Triggers on 笔记数据_/订单数据_/SKU销售_ or columns 笔记ID/曝光量/note_sku_links. Not for generic data analysis or non-XHS platforms unless explicitly invoked."
---

# Xiaohongshu Ceramics Analytics

## When to use

Use this skill when the user provides Xiaohongshu (小红书 / 千帆) exported data files for a ceramics or tableware shop and wants analysis — weekly reviews, content performance, SKU lift, comment mining, paid traffic efficiency, or any task in the menu below. Also use when the user explicitly invokes `data-analyze-for-zcl`. Do not activate for generic data analysis or non-Xiaohongshu platforms.

## Workflow

1. **Resolve skill directory** — locate the bundled runtime under `assets/xhs-ca/`. Do not assume the user has a separate repo checkout.

2. **Bootstrap** — run `scripts/bootstrap`. If it fails, read `assets/xhs-ca/references/troubleshooting.md`, surface the relevant fix to the user, and stop until the environment is repaired.

3. **Ask for exports** — request the user's Excel/CSV files (e.g. 笔记数据, 订单数据, SKU销售, 投放数据) and an optional cover-image folder. Clarify which date range and which shop account the files cover.

4. **Task selection — coverage-driven, NOT hand-picked (REQUIRED)** — after the build, run `scripts/xhs-ca coverage`. It runs every registered task against the built DB and prints which are **producible** (yield a real, above-not-judgable finding) vs **blocked** (with the exact missing table/column that unlocks each). This exists because manual selection systematically under-picks — the report was thin because tasks were chosen by guesswork, not by what the data can actually support. Default to running **every producible task** so the report mines the data to its full depth; read `assets/xhs-ca/references/task_menu.md` only to describe each producible task to the user and to explain the blocked ones' next-data-needed. Confirm the producible set with the user, then run them together in step 7 (or let step 7's `run auto` select them). `run all` is still the exception — it also emits degraded/not-judgable modules; prefer the producible set.

5. **Build** — run `scripts/xhs-ca build <files...>`. If header-mapping fails, read `assets/xhs-ca/references/xhs_glossary.md` and `assets/xhs-ca/references/data_contract/_index.md`, then negotiate unmapped columns with the user before retrying. After the build, follow the **字段映射自愈** section below to resolve any `mapping_diagnostics` rows before analysis.

6. **Data quality (inspect, then fold in)** — run `xhs-ca run data_quality_check` on its own once to inspect the export and drive the **字段映射自愈** gate below; if paid-traffic data was provided, also inspect `ad_data_quality_check`. Resolve empty tables / missing columns *before* building the final report. Do NOT deliver this inspection run as a separate artifact — `data_quality_check` is folded into the single integrated report in step 7, where the compositor renders it as the **closing appendix (附录：数据质量与口径说明)**, not a separate file.

7. **Run fact layer — REQUIRED, first HTML deliverable** — the simplest correct path is `scripts/xhs-ca run auto --name <店铺名><日期范围>事实层经营诊断报告`: `auto` runs exactly the producible set from step 4's coverage (including `data_quality_check`) in one shot, so the report mines the data to its full depth and writes the deterministic fact layer plus `facts.json`. To curate, instead pass every confirmed slug plus `data_quality_check` to a **single** `scripts/xhs-ca run <slug1> <slug2> … data_quality_check --name <店铺名><日期范围>事实层经营诊断报告` invocation. This fact-layer HTML is a required deliverable alongside the final narrative HTML, because it preserves the full deterministic module detail available before narrative rewriting. **Name reports from the shop/store name, not the platform/export source**: prefer `<店铺名><日期范围>事实层经营诊断报告`; never use `千帆`, `小红书`, `XHS`, `Qianfan`, or another platform name as the leading report name unless it is literally part of the shop name. If the shop name is unavailable from files or prior context, ask once; if the user does not provide it, use a neutral `店铺<日期范围>事实层经营诊断报告` fallback and state the missing shop-name caveat. **Section order is enforced by the compositor, not by argument order:** business modules lead (executive summary → 经营诊断 → 商品/内容/用户需求/实验 → 基础参考), and `data_quality_check`/`ad_data_quality_check` always sink to the end as the **附录：数据质量与口径说明**. Do NOT run one slug at a time — that fragments the evidence base. Before summarizing, read each module's `assets/xhs-ca/task_templates/<slug>.md` and `assets/xhs-ca/references/cheatsheet.md` for metric definitions, evidence rules, and report structure.

### 7b. Required (auto-degrading): multi-agent narrative report (host with sub-agents)

Step 7 produced the deterministic **fact layer**, which is delivered as the first HTML report but is not the final merchant-facing narrative report.
The merchant-facing report is produced here, by the narrative workflow — this
is the required final-delivery path, not an optional extra. It degrades
automatically so it can never fail open:

1. Produce the deterministic fact layer as usual (step 7). Besides the report,
   `run`/`facts` write two state-dir sidecars: `facts.json` and the domain-sliced
   `results.json`. The narrative's `prepare` consumes `results.json` as `--results`
   (and `facts.json` as `--facts`) — never hand-build `results.json`.
2. **Ask the user once to authorize the narrative writer — this is required, and
   asking is not spawning.** Even if your host policy forbids spawning
   sub-agents without an explicit user request, you must still ask: the user's
   "yes" IS that request. Do not skip the question, and do not treat "the user
   has not asked for sub-agents" as "this host cannot spawn" and silently
   degrade — ask first. **This is a blocking gate:** put it as its own distinct
   question that expects an explicit yes/no — never smuggle it into a progress
   update and run past it. After asking, STOP and wait for the reply — it comes
   in a *later* turn. Do not run `prepare`, `advance`, or `finalize-deterministic`
   in the same turn you ask. "No answer yet" is not a decline; only branch once
   the user has actually answered.
3. **If authorized**, drive the narrative workflow instead of composing
   directly. Follow `assets/xhs-ca/orchestration/runbook.md` exactly:
   `prepare` → `status --json` → map briefs to spawns → `ingest` each result →
   `advance` → loop until stage is `finalized` or `blocked`. A `finalized` run
   writes the two narrative artifacts.
4. **If the user declines** (`--reason denied`), **the host truly has no
   sub-agent capability at all** (`--reason unsupported`), **or the gate never
   passes**, run `xhs-ca narrative finalize-deterministic --run-dir <dir>
   --reason <reason>` (or let `advance` route there automatically).
   A "确定性骨架版" report is always delivered — the deliverable never fails open.

Both paths are valid narrative deliveries and each yields exactly two artifacts
(`<name>.md` + `<name>.html`). Name this second report
`<店铺名><日期范围>叙事版经营诊断报告`. The run directory is durable scratch, not a
deliverable.

The narrative report carries **agent-curated deterministic visuals**, and it must
actually carry them: every core domain whose fact layer has a chartable table
(生意大盘 / 流量与内容 / 商品结构 / 用户与需求 / 退款与售后) is expected to show
**1–2 tables plus at least one chart** alongside its prose. The agent only curates
the *view* — which source table, which columns/rows, and the captions; a
deterministic engine fills every displayed number from the already-computed fact
layer, so the values stay reproducible and trustworthy while the agent decides only
what the visual looks like. If an agent leaves a core domain chart-less, a
deterministic fallback auto-injects one chart for that domain from the fact layer
(captioned 自动补图), so the narrative reliably ships charts rather than prose-only.
The only honest chart-less outcome is when the fact layer genuinely has no chartable
table; if chartable data existed yet no chart reached the HTML, `finalize` records
`degradation_reason=visuals_missing` — surface that in the step-10 summary rather
than presenting a silently prose-only narrative as complete.

8. **Custom integrated reports** — only when you need a report outside the built-in task registry (non-standard sheets a task does not cover): write the Markdown source first, then immediately run `scripts/xhs-ca render-html <report.md>` or `scripts/xhs-ca render-html <report.md> --output <report.html>`. For any combination of built-in tasks, prefer the single multi-slug `run` in step 7 over hand-authoring. Keep any Excel/CSV companion tables, but they do not replace the HTML report.

9. **Delivery verification (REQUIRED, HTML-only final deliverables)** — the user must receive exactly two single-file HTML reports: the fact-layer HTML from step 7 (`<店铺名><日期范围>事实层经营诊断报告.html`) and the narrative HTML from step 7b (`<店铺名><日期范围>叙事版经营诊断报告.html`). Markdown may exist as internal source/intermediate, but do not present it as a deliverable unless the user explicitly asks for source Markdown. Before the final response, confirm both HTML files exist under `.xhs-ceramics-analytics/outputs/`, both filenames start with the shop/store name or the neutral `店铺` fallback, no platform name leads either filename, and no stray per-slug `data_quality_check.md`/`.html` were delivered. Also verify the narrative artifact came from `finalize`, `render-frozen`, or explicit skeleton fallback, not merely from step 7's deterministic `run auto`. **Visual audit of the narrative HTML:** unless the run recorded `degradation_reason=visuals_missing` (fact layer had no chartable table), confirm the narrative HTML actually contains charts — e.g. `grep -c "<svg" <叙事版>.html` should be ≥1 (aim for ≥1 per core domain that had chartable data). A prose-only narrative that finalized without a `visuals_missing` reason is a defect, not a delivery. If either HTML rendering fails, report the error path/message and state clearly which delivery failed; do not substitute Markdown as a deliverable.

10. **Summarize** — present findings with: evidence tier (Strong/Medium/Weak/Not-judgable), key numbers, caveats verbatim from the report, next-data-needed, recommended action, narrative workflow status, and the two final HTML file paths (事实层 + 叙事版) only. If the narrative run recorded `degradation_reason=visuals_missing` (chartable data existed but no chart reached the HTML), state that plainly as a caveat — the narrative shipped without its expected visuals. NEVER claim deterministic note-to-order attribution.

## 字段映射自愈 (Field-mapping self-heal)

The build never rejects a file for a drifted Chinese header — it degrades and records the gap. After every `xhs-ca build`, adjudicate the gaps before analysis:

1. **Read the diagnostics.** Query the `mapping_diagnostics` table (`table_name, file, required_column, status, candidate_sources, reason, action`). If it is empty, mapping is clean — proceed.
2. **Judge each row, caliber-aware.** Open the named file's headers and decide which raw header (if any) is the missing `required_column`. **口径不可混淆:** `（支付时间）`/`_pay` and `（退款时间）`/`_refundtime` are different calibers that map to different canonical columns — never map a 退款时间 header onto a `_pay` column or vice-versa. `status="missing"` (empty `candidate_sources`) means no unmatched header exists — the column is genuinely absent; do NOT invent a mapping, report it as next-data-needed. `status="ambiguous"` means the header in `candidate_sources` is present but unmatched — a wording drift you can adjudicate.
3. **Risk gate (hybrid).**
   - *Obvious + unique* — exactly one plausible header in `candidate_sources`, same caliber, high confidence → append the alias to `mapping_overrides.yaml` and re-run `xhs-ca build`.
   - *Ambiguous / caliber-uncertain / multiple candidates* → present the candidate header(s) to the operator, get confirmation, then write.
4. **`mapping_overrides.yaml` format** (lives in the state dir next to `analytics.duckdb`; overrides only ADD aliases, never remove a shipped one):
   ```yaml
   refund_overview:
     refund_users:
       - 退款人数合计
   business_overview_daily:
     net_gmv_pay:
       - 退款后金额
   ```
5. **Re-build.** Re-running `xhs-ca build` applies the learned alias deterministically; the column becomes canonical and marts see it. The judgment is frozen — identical `(export, overrides)` always produces the identical build.

## Commands

```bash
# Check environment health
<skill-dir>/scripts/xhs-ca doctor

# Build database from multiple export files
<skill-dir>/scripts/xhs-ca build notes.xlsx orders.xlsx skus.xlsx

# Build with comments only
<skill-dir>/scripts/xhs-ca build comments.xlsx

# See which tasks the built data can actually produce vs what's blocked (+ why)
<skill-dir>/scripts/xhs-ca coverage

# Run a single analysis task (writes note_funnel.md + note_funnel.html)
<skill-dir>/scripts/xhs-ca run note_funnel

# Fact layer — auto-select every producible task. Use the shop/store name.
<skill-dir>/scripts/xhs-ca run auto --name 店铺名日期范围事实层经营诊断报告

# Same fact layer, explicitly curated. Argument order is free: the compositor
# always sinks data_quality_check to the end. Still run required step 7b after this.
<skill-dir>/scripts/xhs-ca run core_business_diagnosis demand_funnel_diagnosis search_efficiency_diagnosis channel_structure_diagnosis audience_structure_diagnosis refund_root_cause_diagnosis note_commercial_diagnosis sku_structure_diagnosis data_quality_check --name 店铺名日期范围事实层经营诊断报告

# Combined run without --name falls back to 经营诊断报告.md + 经营诊断报告.html
<skill-dir>/scripts/xhs-ca run core_business_diagnosis search_efficiency_diagnosis data_quality_check

# Inspect data quality on its own during the 字段映射自愈 gate (not a deliverable)
<skill-dir>/scripts/xhs-ca run data_quality_check

# Run paid traffic analysis
<skill-dir>/scripts/xhs-ca run paid_traffic_efficiency

# Run full report suite (only when user requests complete review)
<skill-dir>/scripts/xhs-ca run all

# Convert a custom Markdown/integrated report into single-file HTML
<skill-dir>/scripts/xhs-ca render-html .xhs-ceramics-analytics/outputs/经营诊断报告.md
```

## Files this skill loads on demand

- **cheatsheet.md** — always loaded before summarizing (evidence tiers, metrics, report contract).
- **task_menu.md** — loaded at step 4 to match user intent to available tasks.
- **xhs_glossary.md** — loaded at step 5 only when header mapping fails.
- **data_contract/\<table\>.md** — loaded only when a schema question arises or build reports missing columns.
- **task_templates/\<slug\>.md** — loaded before summarizing that specific task's output.
- **troubleshooting.md** — loaded only when bootstrap or doctor fails.

## Rules

1. **No deterministic attribution** — do not claim note-to-order causation unless explicit `note_sku_links` source data supports it. Inferred links produce at most Weak evidence.
2. **Every conclusion carries an evidence tier** — one of Strong, Medium, Weak, or Not-judgable with justification. Omitting the tier violates the report contract.
3. **Missing tables produce not-judgable + next-data-needed** — never fabricate numbers or force an analysis when required data is absent.
4. **Weak evidence = hypothesis, not recommendation** — Weak findings must not appear as "recommended action" without an explicit upgrade path stated.
5. **Prefer DuckDB and bundled tasks** — use `scripts/xhs-ca run` over ad-hoc Python/SQL scripts. The bundled tasks enforce evidence scoring, report structure, and metric definitions consistently.
6. **Never mention troubleshooting steps preemptively** — only surface repair commands from `references/troubleshooting.md` when bootstrap or doctor actually fails.
7. **Do not invent metrics** — all metrics in reports must trace back to `references/metric_definitions.md` (consolidated in cheatsheet). If a metric is needed but absent, flag it rather than fabricating a formula.
8. **HTML is the final deliverable surface** — deliver exactly two HTML reports (事实层 + 叙事版). Markdown is internal source/intermediate output unless the user explicitly asks for it. Markdown-only delivery is incomplete unless HTML rendering failed and the failure was explicitly reported.
