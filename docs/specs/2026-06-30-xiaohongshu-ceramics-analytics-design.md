# Xiaohongshu Ceramics Analytics Skill Design

Date: 2026-06-30

## Goal

Build a local Codex skill/plugin for a Xiaohongshu ceramics ecommerce account. The account sells visually refined ceramic products such as cups, plates, bowls, and related tableware. The skill turns exported Xiaohongshu content data, product data, SKU/order data, and cover images into repeatable operating decisions.

The first version is intentionally full-scope: it should include the complete analysis menu, not a toy subset. Each analysis task must have a working path, a clear data requirement check, a confidence level, and a report section that a non-technical operator can read without knowing SQL, statistics, or data modeling.

The skill should answer:

- Which content patterns are associated with higher reading, collecting, interaction, and SKU sales response?
- Which cover, copy, product, and timing patterns are credible enough to act on?
- Which conclusions are only hypotheses because the data is weak or confounded?
- What should the account post next week, given 5 posts per day and a willingness to follow an experiment matrix?

## Product Positioning

This is not a generic data analysis skill. It is a domain-specific analysis layer for Xiaohongshu ceramics ecommerce, built on top of mature open-source analytics workflows and tools.

The skill should feel like a local operating analyst:

1. The user provides exported CSV/Excel files and cover images.
2. The skill maps messy files into a standard local data model.
3. The skill runs a full task menu.
4. The skill writes a decision-first HTML/Markdown report.
5. The skill updates a hypothesis and experiment knowledge base for future runs.

Codex is the interaction and reasoning layer. The skill does not need a separate LLM service, a web app, or a custom model server.

## Hard Constraints

- Reuse mature upstream projects wherever possible.
- Do not rewrite a simplified imitation of DuckDB, data exploration, reporting, charting, or statistical libraries.
- Copy, vendor, or depend on upstream code where license and fit allow.
- Keep custom code limited to domain contracts, mapping glue, task orchestration, and Xiaohongshu ceramics-specific analysis templates.
- Treat note-to-order attribution as weak inference unless explicit source data exists.
- Every conclusion must include evidence strength and caveats.
- The output must be understandable to non-professional users.

## Upstream Reuse Strategy

The design should prefer a reliable upstream stack instead of low-star personal skills.

### Primary Workflow Reference

Use Anthropic's `knowledge-work-plugins/data` plugin as the main workflow model:

- Repository: https://github.com/anthropics/knowledge-work-plugins
- License: Apache-2.0
- Role: data analysis workflow structure.
- Useful components: `analyze`, `explore-data`, `write-query`, `create-viz`, `build-dashboard`, `validate-data`, `statistical-analysis`.

The skill should reuse this style of task decomposition:

1. Understand the question.
2. Gather and inspect data.
3. Analyze.
4. Validate before presenting.
5. Present findings.
6. Visualize where helpful.

### Local Analytics Engine

Use DuckDB as the default local analytics database and reuse the official DuckDB skill design:

- Repository: https://github.com/duckdb/duckdb-skills
- License: MIT
- Role: local data file reading, SQL query execution, session state, DuckDB-friendly workflow.

Do not write a custom SQL engine or custom CSV parser. Use DuckDB directly for CSV, Excel, JSON, Parquet, and local database operations where practical. If the official DuckDB skill can be installed or vendored, prefer that over rewriting its behavior.

### Script Reference

Use ByteDance DeerFlow's `data-analysis` skill as a script pattern reference:

- Repository: https://github.com/bytedance/deer-flow
- License: MIT
- Role: DuckDB-backed inspection/query/summary scripts for Excel and CSV.

This can inform a thin wrapper for local file inspection and DuckDB database building. It should not become the business workflow.

### Marketing Method Reference

Use `coreyhaines31/marketingskills` as a marketing and experimentation reference:

- Repository: https://github.com/coreyhaines31/marketingskills
- License: MIT
- Role: analytics, A/B testing, ad creative, content, social, and marketing decision frameworks.

Use it for experiment discipline, creative evaluation language, and decision prioritization. Do not copy it as a generic marketing skill.

### Xiaohongshu Domain References

Use high-star Xiaohongshu skills only as domain references unless license and code quality make direct reuse appropriate:

- https://github.com/white0dew/XiaohongshuSkills
- https://github.com/Xiangyu-CAS/xiaohongshu-ops-skill

The first version does not need Xiaohongshu crawling, publishing, or automation because the user says data exports are available. These references can inform platform terms, content fields, content-data concepts, and operating-report structure.

### Vendor Policy

If upstream code is copied:

- Keep upstream license files.
- Record repository URL, license, commit hash, copied paths, and local modifications in `references/upstream_sources.md`.
- Prefer keeping vendored code unmodified.
- Put custom adapters outside the vendored directory.
- If a dependency can be installed cleanly, prefer dependency plus wrapper over copying.

## Non-Goals

The first version must not spend effort on:

- Xiaohongshu scraping or automated publishing.
- A standalone SaaS, hosted dashboard, login system, or multi-user web app.
- A separate LLM/model service.
- A custom BI engine.
- A custom visualization engine.
- A custom causal inference library.
- A strong deterministic attribution claim from note to order unless source data explicitly supports it.

## Skill Shape

Recommended name:

`xiaohongshu-ceramics-analytics`

Recommended top-level structure:

```text
xiaohongshu-ceramics-analytics/
  SKILL.md
  references/
    upstream_sources.md
    data_contract.md
    metric_definitions.md
    report_contract.md
    evidence_strength.md
    experiment_matrix.md
    task_menu.md
  task_templates/
    data_quality_check.md
    account_baseline.md
    note_funnel.md
    sku_counterfactual_lift.md
    content_response_curve.md
    cover_style_effect.md
    copy_angle_effect.md
    product_content_interaction.md
    product_opportunity_matrix.md
    comment_demand_mining.md
    content_portfolio_optimization.md
    weekly_experiment_matrix.md
    reshoot_repost_candidates.md
    hypothesis_knowledge_base.md
    weekly_business_review.md
  scripts/
    import_wizard.py
    build_duckdb.py
    run_task.py
    render_report.py
    validate_mapping.py
  vendor/
    README.md
    upstream-projects/
  examples/
    mapping.example.yml
    project_config.example.yml
```

The actual implementation can reduce script count if an upstream tool handles the job. The important part is the boundary: references and task templates contain domain logic; scripts are glue.

## Standard Data Contract

The user may provide messy exports. The skill normalizes them into the following standard tables.

### `notes`

One row per Xiaohongshu note.

Core fields, with graceful degradation if the source export lacks them:

- `note_id`
- `publish_time`
- `title`
- `body`
- `note_type`
- `cover_image_path`
- `impressions`
- `reads`
- `likes`
- `collects`
- `comments`
- `shares`
- `followers_gained`

Optional:

- `author_account`
- `topic_tags`
- `post_status`
- `platform_url`
- `raw_file`
- `raw_row_id`

### `products`

One row per product.

- `product_id`
- `product_name`
- `category`
- `vessel_type`
- `series`
- `color_family`
- `pattern_style`
- `price_band`
- `launch_date`
- `status`

Optional:

- `margin_band`
- `inventory_strategy`
- `product_page_url`

### `skus`

One row per SKU.

- `sku_id`
- `product_id`
- `sku_name`
- `price`
- `inventory_optional`
- `cost_optional`

### `orders`

One row per order line or SKU line. Order-level exports must be exploded into order lines when SKU lists are nested.

- `order_id`
- `paid_time`
- `sku_id`
- `quantity`
- `paid_amount`
- `refund_status_optional`

Optional:

- `buyer_id_hash`
- `order_status`
- `channel_field_raw`

The design must not assume `channel_field_raw` can map to a Xiaohongshu note.

### `daily_sku_sales`

Derived from orders or imported directly.

- `date`
- `sku_id`
- `units`
- `gmv`
- `order_count`

### `note_sku_links`

Links notes to candidate products or SKUs.

- `note_id`
- `sku_id`
- `link_type`
- `confidence`
- `evidence`

Allowed `link_type` values:

- `explicit`: source file provides the relationship.
- `manual`: user confirms the relationship.
- `inferred`: title, body, SKU name, product name, image filename, publish plan, or timing suggests a relationship.

### `content_features`

One row per note, optionally split into cover and copy feature groups. If cover and copy features are split into separate files, each row still carries `note_id`.

- `note_id`

Cover features:

- `vessel_type_visible`
- `composition_type`
- `product_area_ratio_band`
- `shooting_angle`
- `background_material`
- `lighting_style`
- `color_temperature`
- `saturation_band`
- `contrast_band`
- `scene_hint`
- `human_hand_visible`
- `food_drink_visible`
- `text_overlay_present`
- `text_overlay_length_band`
- `aesthetic_semantics`

Copy features:

- `copy_angle`
- `purchase_motive`
- `craft_terms_present`
- `scene_terms_present`
- `gift_terms_present`
- `scarcity_terms_present`
- `price_explanation_present`
- `title_length_band`
- `specific_noun_density_band`
- `emotional_intensity_band`
- `call_to_action_type`

### `comments`

One row per comment when comment-level exports are available.

- `note_id`
- `comment_time`
- `comment_text`

Optional:

- `comment_id`
- `parent_comment_id`
- `comment_like_count`
- `author_id_hash`
- `raw_file`
- `raw_row_id`

### `calendar_events`

One row per date/event.

- `date`
- `event_type`
- `event_name`
- `affected_sku_id_optional`
- `affected_product_id_optional`
- `severity`
- `notes`

Examples:

- new product launch
- promotion
- holiday
- stockout
- restock
- shipping disruption
- platform campaign

### `experiments`

One row per planned or completed test cell.

- `experiment_id`
- `week`
- `hypothesis`
- `planned_publish_time`
- `note_id_optional`
- `sku_id`
- `controlled_variables`
- `changed_variable`
- `success_metric`
- `decision_rule`
- `status`
- `result_summary`

### `hypotheses`

Persistent knowledge base.

- `hypothesis_id`
- `statement`
- `status`
- `evidence_strength`
- `supporting_runs`
- `contradicting_runs`
- `next_test`
- `last_updated`

## Import Wizard

The import wizard is mandatory because users should not have to clean files manually.

Workflow:

1. Scan user-provided files.
2. Detect file type and sheet names.
3. Profile columns, row counts, date ranges, nulls, uniqueness, sample values, and numeric ranges.
4. Guess table type: notes, products, skus, orders, daily sales, images, experiments, or calendar events.
5. Guess field mapping using column names and sample values.
6. Create `mapping.yml`.
7. Ask only for critical ambiguous mappings.
8. Validate mapping.
9. Build or refresh the local DuckDB database.
10. Write an import report with data quality caveats.

The wizard must degrade gracefully:

- If order data is absent, run content-only and note-performance analysis.
- If impression data is absent, use reads as the upper funnel metric and label the limitation.
- If SKU links are absent, allow manual linking or inferred linking with lower evidence strength.
- If images are absent, skip visual feature extraction and allow manual tags.
- If product metadata is sparse, still run SKU sales and note response tasks with caveats.

## Metrics

Metrics must be defined in `references/metric_definitions.md`.

Core content metrics:

- `read_rate = reads / impressions`, only when impressions exist.
- `like_rate = likes / reads`.
- `collect_rate = collects / reads`.
- `comment_rate = comments / reads`.
- `share_rate = shares / reads`.
- `engagement_rate = (likes + collects + comments + shares) / reads`.
- `follower_conversion = followers_gained / reads`.

Core sales metrics:

- `units`
- `gmv`
- `order_count`
- `average_order_value`
- `sku_daily_units`
- `sku_daily_gmv`

Weak lift metrics:

- `baseline_units`: expected units from pre-period or model baseline.
- `observed_units`: units in post window.
- `absolute_lift = observed_units - baseline_units`.
- `relative_lift = observed_units / baseline_units - 1`.
- `z_score` or model residual score.
- `window`: 0-24h, 1-3d, 4-7d, 7-14d.

Portfolio metrics:

- `content_efficiency = reads or collects per post`.
- `sales_response = SKU lift or sales residual after publish`.
- `content_sales_alignment`: whether high attention coincides with sales response.
- `fatigue_signal`: declining response under similar repeated content.

## Evidence Strength

Every finding must include evidence strength.

### Strong

Use when:

- sample size is adequate,
- source data is complete for the metric,
- major confounders are controlled or absent,
- the pattern repeats across multiple posts or SKU groups,
- there is a reasonable control group or counterfactual baseline.

### Medium

Use when:

- pattern is numerically clear,
- sample size is moderate,
- some controls exist,
- but timing, inventory, promotion, platform traffic, or SKU mix could still explain part of the effect.

### Weak

Use when:

- sample size is small,
- variables are mixed,
- SKU links are inferred,
- data is missing,
- or the pattern appears only once.

### Not Judgable

Use when:

- required data is missing,
- metric definitions are incompatible,
- the relevant rows cannot be mapped,
- or confounders overwhelm the signal.

Reports must not hide weak evidence. Weak findings should become hypotheses, not recommendations.

## First Version Task Menu

The first version includes the complete menu below. Each task must run independently and produce a report section. If data is insufficient, the task produces a limitation section and a next-data-needed recommendation.

### 1. Data Quality Check

Purpose:

Assess whether the dataset can support the requested analyses.

Outputs:

- detected files and table types,
- row counts and date ranges,
- missing critical fields,
- duplicate IDs,
- unmapped columns,
- suspicious values,
- usable analysis tasks,
- tasks blocked by missing data.

### 2. Account Baseline

Purpose:

Define the normal operating range before interpreting any lift.

Analyses:

- posts per day,
- reads and interaction distribution,
- weekday/time-of-day effects,
- baseline by note type,
- baseline by product type,
- traffic volatility,
- top and bottom decile behavior,
- post density dilution.

### 3. Note Funnel

Purpose:

Separate cover/title performance from content resonance.

Analyses:

- impression to read, when impression data exists,
- read to like,
- read to collect,
- read to comment,
- read to follow,
- content type and vessel type differences,
- high-read low-collect notes,
- low-read high-collect notes.

### 4. SKU Counterfactual Lift

Purpose:

Estimate whether linked SKU sales after a note are above expected baseline.

Windows:

- 0-24h,
- 1-3d,
- 4-7d,
- 7-14d.

Methods, chosen by data availability:

- simple pre/post baseline,
- matched weekday baseline,
- rolling historical baseline,
- similar SKU control group,
- regression baseline with calendar controls,
- Bayesian or time-series baseline later if data supports it.

Output must use weak attribution language:

- possible contribution,
- related lift,
- sales response,
- counterfactual residual.

Do not claim deterministic order attribution unless explicit source data supports it.

### 5. Content Response Curve

Purpose:

Measure how content influence may decay or accumulate over time.

Analyses:

- immediate response,
- short-term response,
- delayed response,
- long-tail response,
- multiple notes promoting the same SKU,
- content stacking and dilution,
- response decay by product type.

### 6. Cover Style Effect

Purpose:

Identify visual patterns associated with read, collect, and sales response.

Feature groups:

- composition,
- scene,
- product area ratio,
- background material,
- lighting,
- color,
- text overlay,
- human hand or usage cue,
- aesthetic semantics.

Analyses:

- univariate comparisons,
- stratified comparisons by SKU/product type,
- regression or tree model where sample size allows,
- interaction with price band and vessel type,
- top cover archetypes,
- underperforming cover archetypes.

### 7. Copy Angle Effect

Purpose:

Identify title and body patterns associated with content and sales outcomes.

Feature groups:

- craft,
- lifestyle,
- gift,
- table setting,
- collection,
- season/holiday,
- scarcity,
- restock,
- price explanation,
- title length,
- concrete noun density,
- emotional intensity.

Analyses:

- outcome by copy angle,
- copy angle by product type,
- copy angle by cover type,
- sales response by copy angle,
- risky low-performing expressions,
- reusable title/copy patterns.

### 8. Product and Content Interaction

Purpose:

Answer product-specific creative questions instead of global averages.

Questions:

- Which cover style works for high-price cups?
- Which copy angle works for plates?
- Which scene works for gift sets?
- Which content style helps new SKUs?
- Which style helps old SKUs revive?

Methods:

- stratified comparisons,
- mixed-effect or grouped regression when feasible,
- rule extraction from tree models,
- evidence thresholds to avoid overfitting.

### 9. Product Opportunity Matrix

Purpose:

Prioritize product operating actions.

Quadrants:

- high content performance and high sales response: scale.
- high content performance and low sales response: improve product page, price, offer, or SKU match.
- low content performance and high sales response: reshoot and retell.
- low content performance and low sales response: deprioritize or reposition.

Additional constraints:

- inventory,
- margin,
- launch stage,
- seasonality,
- price band.

### 10. Comment and Demand Mining

Purpose:

Extract purchase intent and product questions from comments.

Signals:

- asks for price,
- asks for link,
- asks for capacity,
- asks for material,
- asks for shipping,
- asks whether it is suitable as a gift,
- says expensive,
- says beautiful,
- compares to another style,
- asks for restock.

Outputs:

- demand clusters,
- objections,
- FAQ candidates,
- next copy angles,
- product page improvement ideas.

If comments are missing or sparse, the task reports that and suggests collection requirements.

### 11. Content Portfolio Optimization

Purpose:

Optimize the daily 5-post mix.

Content roles:

- traffic post,
- conversion post,
- brand tone post,
- new product post,
- restock post,
- experiment post.

Analyses:

- current mix,
- mix by outcome,
- SKU overlap,
- repeated style fatigue,
- same-day cannibalization,
- post spacing,
- exploration vs exploitation ratio.

### 12. Weekly Experiment Matrix

Purpose:

Generate a concrete 7-day posting plan.

Rules:

- 5 posts per day.
- Keep 20-30 percent exploration slots.
- Keep high-confidence winners in exploitation slots.
- Control SKU, vessel type, time slot, or copy angle where possible.
- Avoid testing too many variables at once.
- Avoid same-SKU overcrowding unless deliberately testing repetition.
- Include decision rule before running the experiment.

Output:

- day,
- time slot,
- SKU/product,
- cover style,
- copy angle,
- changed variable,
- controlled variables,
- success metric,
- evidence expected,
- stop/continue decision rule.

### 13. Reshoot and Repost Candidates

Purpose:

Find posts/products worth another attempt.

Candidate types:

- high collect but low sales response,
- high sales response but low read,
- strong SKU but weak cover,
- good product but stale copy,
- old hit worth updating,
- new product that lacked fair exposure.

Output:

- prioritized candidate list,
- why it is a candidate,
- suggested new cover,
- suggested new copy angle,
- expected metric to watch.

### 14. Hypothesis Knowledge Base

Purpose:

Make the skill compound over time.

The skill maintains:

- confirmed patterns,
- rejected patterns,
- active hypotheses,
- experiment history,
- data caveats,
- next tests.

Reports should update the knowledge base instead of treating every run as isolated.

### 15. Weekly Business Review

Purpose:

Provide the complete non-technical weekly operating report.

Sections:

- headline conclusions,
- what changed this week,
- strongest evidence,
- weak but interesting hypotheses,
- product opportunities,
- content opportunities,
- risks and caveats,
- next week experiment matrix,
- appendix with methodology, SQL, and data quality.

## Analysis Methods

The first version should choose methods based on data readiness.

### Always Available With Basic Data

- descriptive statistics,
- grouped comparisons,
- rolling baselines,
- pre/post windows,
- ranked opportunity lists,
- evidence scoring,
- report generation.

### Available With Enough Rows

- regression with controls,
- tree models for feature importance,
- SHAP-style explanation if dependency is available,
- grouped analysis by SKU/product/vessel type,
- interaction analysis.

### Available With Better Experimental Data

- matched comparisons,
- difference-in-differences style analysis,
- sequential testing,
- bandit-style allocation recommendations,
- stronger counterfactual baselines.

The implementation should not overuse advanced methods when data is weak. The report should explain why a simpler method was chosen.

## Report Contract

Reports are decision-first and non-technical.

Each task section must include:

1. conclusion,
2. key numbers,
3. evidence strength,
4. why the skill thinks this,
5. possible confounders,
6. recommended action,
7. next test or next data needed,
8. appendix link or details for SQL/methodology.

Tone:

- direct,
- plain language,
- no fake certainty,
- no statistics jargon unless necessary,
- concrete next actions.

The first version must always write a Markdown report and should also write a single-file HTML report with charts and tables when local chart dependencies are available. If HTML rendering fails, the skill must keep the Markdown report, report the rendering error, and keep all generated tables in reproducible output files.

## Minimal Custom Code

The custom code should be kept small.

### Necessary Custom Work

- data contract files,
- field mapping wizard,
- metric definitions,
- weak attribution SQL/templates,
- content feature schema,
- report contract,
- experiment matrix rules,
- task menu orchestration,
- Xiaohongshu ceramics-specific examples.

### Thin Wrappers Only

- DuckDB query execution,
- file reading,
- schema profiling,
- visualization rendering,
- statistical modeling,
- report rendering.

### Avoid Writing

- crawler,
- publisher,
- dashboard app,
- custom SQL runner,
- custom chart library,
- custom model service,
- full generic data-analysis skill,
- strong attribution engine without data support.

## Error Handling And Degradation

The skill should never fail silently.

Common cases:

- If note IDs are missing, create stable local IDs and warn about merge risk.
- If publish times are missing, block time-window attribution and still run content feature analysis.
- If SKU IDs are missing, allow product-level mapping with lower evidence strength.
- If orders are missing, run content-only analysis.
- If images are missing, skip or ask for manual cover tags.
- If data has multiple date formats, normalize and report conversions.
- If columns are ambiguous, ask the user before importing.
- If a task is not supported by available data, output a limitation report and next-data-needed checklist.

## Testing And Verification

The first version should include tests or reproducible checks for:

- mapping validation,
- date parsing,
- SKU order-line expansion,
- daily SKU sales derivation,
- note-SKU link creation,
- lift window calculation,
- evidence strength assignment,
- report section generation,
- missing-data degradation.

Use synthetic sample data for ceramics ecommerce:

- 1000+ historical notes,
- 30-100 SKUs,
- daily 5-post pattern,
- order lines over multiple months,
- known promotions and stockouts,
- cover/copy feature labels.

## First Version Implementation Decisions

These choices are part of the V1 design:

- Start as a full Codex plugin if practical, with one primary skill and supporting references/templates. If plugin packaging adds friction, keep the folder skill-compatible and add plugin packaging after the skill works.
- Use DuckDB directly and prefer installing or vendoring `duckdb/duckdb-skills` rather than rewriting equivalent behavior.
- Write Markdown and single-file HTML reports. Markdown is the guaranteed fallback.
- Start content feature extraction with manual tags plus Codex-assisted labeling. Add OpenCV/CLIP-assisted extraction only through an optional adapter, not as a hard dependency.
- Store project state under `.xhs-ceramics-analytics/` by default: mapping, DuckDB database, report outputs, experiment records, and hypothesis knowledge base.
- Keep upstream sources recorded in `references/upstream_sources.md` with repository URL, license, commit hash, copied paths, and local changes.

## Success Criteria

The first version is successful when a non-technical user can:

1. point the skill at messy exported files and cover images,
2. confirm only ambiguous mappings,
3. get a local DuckDB analysis database,
4. run all 15 task templates,
5. receive a readable weekly business report,
6. see evidence strength for every conclusion,
7. get a concrete next-week 5-post-per-day experiment matrix,
8. preserve hypotheses and learnings for the next run.

## Implementation Boundary

The first implementation plan should start with a full V1, not a toy MVP. However, "full V1" means every task has a real, data-aware, degradable workflow. It does not mean every advanced method must be used on every dataset.

The hierarchy is:

1. reliable import and data quality,
2. correct metrics and weak attribution windows,
3. full report menu,
4. experiment matrix and knowledge base,
5. richer models where the data justifies them.
