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

4. **Task selection (REQUIRED)** — read `assets/xhs-ca/references/task_menu.md`. Based on the files the user provided, list which tasks are runnable and which lack required data. Confirm with the user which task(s) to run. `run all` is the exception, not the default — only use it when the user explicitly asks for a full operating review.

5. **Build** — run `scripts/xhs-ca build <files...>`. If header-mapping fails, read `assets/xhs-ca/references/xhs_glossary.md` and `assets/xhs-ca/references/data_contract/_index.md`, then negotiate unmapped columns with the user before retrying.

6. **Data quality** — always run `xhs-ca run data_quality_check` first. If paid-traffic data was provided, also run `ad_data_quality_check`. Surface any empty tables or missing required columns before proceeding to analysis tasks.

7. **Run selected task(s)** — execute `scripts/xhs-ca run <slug>` for each confirmed task. Built-in tasks write both `<slug>.md` and `<slug>.html` under `.xhs-ceramics-analytics/outputs/`. Before summarizing each report, read the matching `assets/xhs-ca/task_templates/<slug>.md` and `assets/xhs-ca/references/cheatsheet.md` for metric definitions, evidence rules, and report structure.

8. **Custom integrated reports** — if you create any report outside the built-in task registry (for example a 千帆经营诊断 that combines non-standard sheets such as 经营总览、退款、搜索、店铺漏斗), write the Markdown report first, then immediately run `scripts/xhs-ca render-html <report.md>` or `scripts/xhs-ca render-html <report.md> --output <report.html>`. Keep any Excel/CSV companion tables, but they do not replace the HTML report.

9. **Delivery verification (REQUIRED)** — before the final response, verify every delivered Markdown report has a matching single-file HTML report. For built-in tasks, check the generated `<slug>.html`; for custom integrated reports, check the `render-html` output. If HTML rendering fails, keep the Markdown report, report the error path/message, and do not imply HTML was delivered.

10. **Summarize** — present findings with: evidence tier (Strong/Medium/Weak/Not-judgable), key numbers, caveats verbatim from the report, next-data-needed, recommended action, and the Markdown + HTML file paths. NEVER claim deterministic note-to-order attribution.

## Commands

```bash
# Check environment health
<skill-dir>/scripts/xhs-ca doctor

# Build database from multiple export files
<skill-dir>/scripts/xhs-ca build notes.xlsx orders.xlsx skus.xlsx

# Build with comments only
<skill-dir>/scripts/xhs-ca build comments.xlsx

# Run a single analysis task
<skill-dir>/scripts/xhs-ca run note_funnel

# Run paid traffic analysis
<skill-dir>/scripts/xhs-ca run paid_traffic_efficiency

# Run data quality check
<skill-dir>/scripts/xhs-ca run data_quality_check

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
