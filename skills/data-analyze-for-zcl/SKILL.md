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

7. **Run selected task(s) — ONE integrated report, exactly TWO artifacts** — the simplest correct path is `scripts/xhs-ca run auto --name <表意名称>`: `auto` runs exactly the producible set from step 4's coverage (including `data_quality_check`) in one shot, so the report is as deep as the data allows without hand-listing slugs. To curate, instead pass every confirmed slug plus `data_quality_check` to a **single** `scripts/xhs-ca run <slug1> <slug2> … data_quality_check --name <表意名称>` invocation. Either way this composes ONE integrated report written as exactly two files — `<name>.md` + `<name>.html` — under `.xhs-ceramics-analytics/outputs/`. **Section order is enforced by the compositor, not by argument order:** business modules lead (executive summary → 经营诊断 → 商品/内容/用户需求/实验 → 基础参考), and `data_quality_check`/`ad_data_quality_check` always sink to the end as the **附录：数据质量与口径说明** — the reader meets conclusions first and the data caveats close the report. Always pass a meaningful `--name` (e.g. `--name 千帆经营诊断报告`); without it the combined default is `经营诊断报告`. Do NOT run one slug at a time — that fragments the deliverable into a file per task, which is exactly what to avoid. Before summarizing, read each module's `assets/xhs-ca/task_templates/<slug>.md` and `assets/xhs-ca/references/cheatsheet.md` for metric definitions, evidence rules, and report structure.

8. **Custom integrated reports** — only when you need a report outside the built-in task registry (non-standard sheets a task does not cover): write the Markdown report first, then immediately run `scripts/xhs-ca render-html <report.md>` or `scripts/xhs-ca render-html <report.md> --output <report.html>`. For any combination of built-in tasks, prefer the single multi-slug `run` in step 7 over hand-authoring. Keep any Excel/CSV companion tables, but they do not replace the HTML report.

9. **Delivery verification (REQUIRED)** — the user must receive exactly TWO artifacts: the integrated `<name>.md` and its matching single-file `<name>.html`. Before the final response, confirm both exist under `.xhs-ceramics-analytics/outputs/` and that no stray per-slug `data_quality_check.md`/`.html` were delivered. If HTML rendering fails, keep the Markdown report, report the error path/message, and do not imply HTML was delivered.

10. **Summarize** — present findings with: evidence tier (Strong/Medium/Weak/Not-judgable), key numbers, caveats verbatim from the report, next-data-needed, recommended action, and the Markdown + HTML file paths. NEVER claim deterministic note-to-order attribution.

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

# THE STANDARD DELIVERABLE — auto-select every producible task (deepest report),
# data quality folded in as the closing appendix, exactly TWO files.
<skill-dir>/scripts/xhs-ca run auto --name 千帆经营诊断报告

# Same deliverable, explicitly curated. Argument order is free: the compositor
# always sinks data_quality_check to the end.
<skill-dir>/scripts/xhs-ca run core_business_diagnosis demand_funnel_diagnosis search_efficiency_diagnosis channel_structure_diagnosis audience_structure_diagnosis refund_root_cause_diagnosis note_commercial_diagnosis sku_structure_diagnosis data_quality_check --name 千帆经营诊断报告

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
8. **HTML is part of the deliverable** — Markdown-only delivery is incomplete unless HTML rendering failed and the failure was explicitly reported.
