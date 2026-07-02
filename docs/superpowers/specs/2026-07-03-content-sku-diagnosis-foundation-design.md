# 千帆真实导出摄入 + 报告契约 Foundation (Phase 1a) Design

Date: 2026-07-03
Scope note: This spec was rewritten after inspecting the operator's **real 4–7月 千帆 export** (`小红书千帆4-7月数据`, 12 files). The real data is **pre-aggregated platform report tables**, not the per-order / catalog schema the tool was built around — which changes the foundation's center of gravity from "compute new metrics" to "ingest the real exports correctly." The two modules the operator loves (§3 内容与笔记诊断, §4 商品与SKU) are then thin analysis layers on top (later phases).

## Background

The operator loves two sections of a reference report and asked to reproduce them, take them deeper, make them prescriptive, and observed "17 templates but the report is short." Inspecting the **real export** revealed why.

### The real export (ground truth, verified 2026-07-03)

Ran the tool's own `profile_file` + `guess_table_type` against every file. Results:

| Real file | Grain | Tool classifies as | Outcome today |
|---|---|---|---|
| 1.核心数据汇总 (21 col) | daily (`时间`=int YYYYMMDD) | ❌ `calendar_events` (1/4) | wrong table |
| 1/5.成交概览-all (58 col) | daily + 笔记/商卡 split | ❌ `calendar_events` (1/4) | wrong table + **overwritten** |
| 2.规格明细 (26 col) | per-SKU (`规格ID`) | ⚠️ `skus` catalog (3/4) | commerce cols un-canonicalized; collides with real catalog |
| 3.流量来源 | account×渠道×笔记类型 | ❌ UNCLASSIFIED | rejected |
| 4.商品笔记数据 ×3 (38 col) | per-note (`笔记ID`) | ✅ `notes` (6/6) | commerce/refund/type cols un-canonicalized; **3 files overwrite → only last survives** |
| 6.退款概览 | period×载体 structure | ❌ UNCLASSIFIED | rejected |
| 7.搜索总览 (9 col) | daily×载体 | ❌ `calendar_events` | wrong table + **overwritten** |
| 7.搜索词 | per-term (`搜索词`) | ❌ UNCLASSIFIED | rejected |
| 8.店铺漏斗 | daily×人群×首购周期 | ❌ `calendar_events` | wrong table + **overwritten** |
| 8.进店来源 | daily×人群×来源页面 | ❌ `calendar_events` | wrong table + **overwritten** |
| 6.退款原因 | — | **PNG screenshots only** | not machine-readable |
| 9.人群分析 | — | **PNG screenshots only** | not machine-readable |

### Two mechanisms, verified in code

1. **Silent overwrite (fatal).** `build_database` does `CREATE TABLE <type> AS SELECT …` once per file (`db/build.py:29-37,84-91`). When N files share a `table_type`, each `CREATE TABLE` replaces the previous — so notes×3 collapse to the last file, and overview/search/shop all land in `calendar_events` and clobber each other. **Most of the real export is lost at import.**
2. **Un-canonicalized survival.** Unmapped columns are **not dropped** — `_safe_column_name` (`build.py:189-196`) keeps Chinese, only slugging punctuation (`退款后支付金额（支付时间）` → `退款后支付金额_支付时间`, `笔记支付金额` → `笔记支付金额`). So the key columns physically exist, but under Chinese/slug names that are untyped, un-marted, and referenced by no downstream task. The tool literally cannot see "退款后GMV" or per-note 商品点击率.

### Why the report is short — corrected root cause

The reference report the operator loves was **not** produced by this tool; it was built from this raw data by another process. The tool's report is thin because:

1. **Ingestion loses or hides the richest columns** (mechanisms above) — the biggest cause, and invisible until we saw real data.
2. **Report contract structurally unmeetable** — the `Finding` dataclass has no field for `confounders`, `next_test`, or `appendix`, so no task can emit them; `evidence_reason` ("why") is HTML-only by deliberate design (`tests/test_report_rendering.py:38,227`). The richest a finding gets is conclusion + strength + key_numbers + caveats + action.
3. **No synthesis layer, whole domains missing** (search/refund/audience) — later phases.

### The program (context; Phase 1a specced here)

| Phase | Delivers |
|---|---|
| **1a Foundation** *(this doc)* | Robust multi-file ingestion of the real export (9 tabular table types, merge-on-grain-key not overwrite, table-scoped classification) · report-contract renderer fix · period/refund/trend/confidence helpers · PNG-only domains as needs-data |
| **2 Content & Note Diagnosis (§3)** | Title-tag classifier (rules + state-dir config), tag rollup, 图文vs视频, 新vs旧, named weak notes, portfolio + 买前确认区 |
| **3 Product & SKU Opportunity (§4)** | Top-SKU 退款后GMV/加购/退款率 tiers A/B/C, category rollup, refund-driver decomposition, ranked fix-lists |
| **4 New domains** | Search diagnosis (§5), Refund/after-sales structure (§7), Shop-page funnel (§6) |
| **5 Synthesis brain** | Rebuild `weekly_business_review`: §0 一句话结论, §2 MoM core-overview, §8 30-day action matrix, §9 needs-data |

## Goals (Phase 1a)

- **Ingest the real export losslessly and correctly**: each of the 9 tabular files lands in its own typed table with stable canonical column names; multiple files of one type merge on a grain key (row-disjoint files union, column-view files coalesce); no silent overwrite; no double-count; no misclassification.
- **Report contract**: every task *can* emit all 8 elements; STRONG/MEDIUM findings are *required* to.
- **Shared helpers**: period (int-YYYYMMDD & timestamp), refund-rate/net-gmv, trends, honest small-sample confidence.
- **Graceful degradation**: PNG-only domains (退款原因, 人群画像) surface as explicit needs-data, never crash. `xhs-ca run all` succeeds on any subset of the export.

## Non-Goals (deferred)

- Any new **analysis task / §3–§7 module** — Phase 1a lands data + substrate only; first consuming task is Phase 2.
- **Title-tag classifier** (上新/兴安岭/鱼盘 …) → Phase 2. (Note: §4 SKU grouping does **not** need it — 规格明细 ships `一级/二级品类`.)
- **OCR of PNG exports** (退款原因, 人群画像) → later; Phase 1a only emits the needs-data signal + a manual-entry path.
- **note-GMV attribution model** (platform-direct `note_gmv` vs `note_sku_links` weighting) → Phase 2. Phase 1a ingests `note_gmv` as a first-class column; `note_sku_links` stays.
- Keeping full parity with the legacy **per-order `orders` path** is out of scope to *change*; it remains as-is for users who have per-order CSVs (compatibility), and marts prefer whichever source is present.

## Current architecture fit

Pipeline: `xhs-ca build <files>` → `importing.profile`/`mapping` (guess type + field map) → `db.build` (base tables + marts/views) → `analysis.registry` tasks → `reporting.markdown`/`html`.

Verified anchors: `TABLE_SIGNATURES`/`FIELD_ALIASES` per-table (`mapping.py:11-98`); `guess_table_type` scores `|signature ∩ observed| / |signature|`, threshold 0.25 (`mapping.py:106-118`); `_canonical_column_name` is a **global first-match** scan across all tables' aliases (`mapping.py:151-158`) — the fragility behind the misclassifications. Loader keeps all columns (`_projected_frame` `build.py:94-102`, `_projected_columns` `:159-177`). Pydantic only for `orders` (`build.py:34,129-143`). PyYAML already a dep (`pyproject.toml:11`). `note_metrics` is a VIEW (`marts.py:30-59`); `daily_sku_sales` a derived TABLE guarded on `orders` (`build.py:208-252`).

---

## Section A — Ingestion robustness (the foundation)

### A.1 Table-scoped classification (fixes misclassification)

Replace the global-canonicalization guesser with a **table-scoped** one: for each candidate table, score how many of *that table's* signature columns match the file's columns under *that table's own* aliases.

```python
def guess_table_type(profile):
    scores = {t: _table_scoped_hits(profile.columns, t) / len(sig)
              for t, sig in TABLE_SIGNATURES.items()}
    best, score = max(scores.items(), key=lambda kv: kv[1])
    runner_up = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0.0
    if score < MIN_TABLE_CONFIDENCE:
        raise ValueError(...)                      # UNCLASSIFIED → caught by loader → needs-data (Section F)
    if score - runner_up < MARGIN:                 # ambiguous → warn + record, don't guess silently
        ...
    return best
```

`_table_scoped_hits` matches each signature column against the file using that table's `FIELD_ALIASES[table]` only. This removes the "支付金额 globally canonicalizes to orders.paid_amount" class of bug and lets each new table define clean canonical names without cross-table collision. `MARGIN` (start 0.15) surfaces genuinely ambiguous files instead of silently picking one.

### A.2 Merge on grain key (fixes both data loss *and* double-counting)

Multiple input files classify to one `table_type` in two different shapes, and they need **different** combine semantics — so the rule is **merge on a declared grain key with column coalesce**, not blind append:

- **Row-disjoint files** (notes×3 — different `note_id`s; search terms across pages): the key groups don't overlap, so coalesce-on-key reduces to a plain union. Correct, no double-count.
- **Column-view files of one grain** (核心汇总 + 成交/经营概览-all all cover the **same 91 daily dates**, differing only in *which columns* they carry): naive append would emit two rows per `date` and **double-count GMV**. Coalesce-on-key merges them into one wide daily row (each column filled from whichever file has it).

Mechanism (in the loader, before DuckDB load): stage every file of a type as a canonical-named frame, `concat`, then group by the type's **grain key** and coalesce each column to its first non-null value. Load the merged frame with `CREATE TABLE <type> AS …` (one CREATE per type, so no overwrite). Grain keys:

| type | grain key |
|---|---|
| `business_overview_daily` | `date` |
| `sku_performance` | `sku_id` |
| `notes` | `note_id` |
| `search_overview` | `(date, carrier)` |
| `search_terms` | `search_term` |
| `shop_page_funnel` | `(date, audience_type, first_purchase_cycle)` |
| `shop_page_source` | `(date, audience_type, first_purchase_cycle, source_page)` |
| `refund_overview` | `(stat_period, account_name, carrier)` |
| `traffic_source` | `(xhs_id, channel, note_type)` |

- **Conflict handling**: if two files supply *different* non-null values for the same key+column (e.g. both overview files carry `gmv` for a date and they differ beyond `REFUND_RECONCILE_TOLERANCE`), coalesce keeps the first-loaded and emits a **data-quality caveat** naming both files; identical/within-tolerance values merge silently.
- **Provenance**: the build logs which files contributed to each table (for needs-data/data-quality reporting) rather than stamping a per-row `source_file`, since a merged row can blend files.
- `_drop_refresh_objects` (`build.py:47-52`) already drops all `TABLE_SIGNATURES` types up-front, so a rebuild starts clean; the loader change is "gather files by type → merge-on-key → one CREATE" instead of "CREATE per file."

### A.3 Canonical naming conventions

New tables use English canonical names so marts/tasks reference stable identifiers. Conventions:

- **Channel split**: base name for the total; `note_` / `card_` prefix for 笔记 / 商卡 variants (`note_gmv`, `card_gmv`).
- **Refund caliber**: suffix `_pay` for 支付时间, `_refundtime` for 退款时间. Rates exist **only** in 支付时间 → `refund_rate_pay` (no 退款时间 rate exists; open item resolved).
- **Ship stage**: `pre_ship_` / `post_ship_`.
- **Rate denominator**: keep platform's `_pv` / `_uv` suffix where the header carries it.

Full alias maps live in the per-table data-contract docs (`references/data_contract/<table>.md`) and are **validated by tests against the real headers** (§ Testing). The spec fixes intent + distinctive signatures; exact tuples are asserted in code.

---

## Section B — The 9 tabular table types

Each new type: grain, **distinctive signature** (columns unique enough to beat other types), and the key canonical columns. `notes` is *enriched*, not replaced.

### B.1 `business_overview_daily` — from 核心汇总(21) + 成交/经营概览-all(58), merge on `date`
- Grain: one row per `date` (`时间` int YYYYMMDD → kept raw, converted in mart). The 2–3 source files are column-views of this same daily grain → coalesce-on-`date` (A.2).
- Signature: `{date, gmv, paid_orders, paid_buyers, aov}` (present in both variants; overview scores ~1.0, calendar_events ~0.25).
- Key cols: `gmv/note_gmv/card_gmv`, `paid_orders(+note_/card_)`, `paid_buyers`, `product_visitors`, `aov`, `paid_units`, `pay_conversion(+_pv/_uv)`, `add_to_cart_users/add_to_cart_units`, refund block `refund_amount_pay/refund_rate_pay/refund_orders_pay`, `pre_ship_refund_rate_pay/post_ship_refund_rate_pay`, **`net_gmv_pay`** (退款后支付金额), `refund_amount_refundtime`; core-21 extras `total_visitors/total_pv/product_click_rate_pv/new_add_to_cart_users/refund_order_share_refundtime`.

### B.2 `sku_performance` — from 规格明细, per-SKU (§4 source)
- Grain: one row per `sku_id` (`规格ID`), whole-period aggregate (no date col).
- Signature: `{sku_id, net_gmv_pay, refund_rate_pay, add_to_cart_users}` → scores 1.0; a real `skus` **catalog** (has `price`) still prefers `skus`.
- Key cols: `sku_id, sku_name, product_id, product_name, is_channel_product, barcode, category_l1(一级品类), category_l2(二级品类), brand, add_to_cart_users, add_to_cart_units, wishlist_users, gmv, paid_buyers, paid_orders, paid_units, aov, refund_amount_pay, refund_rate_pay, refund_orders_pay, pre_ship_refund_rate_pay, post_ship_refund_rate_pay,` **`net_gmv_pay`** (退款后支付金额), refundtime block.
- **退款后GMV is given by the platform** — ingest the column; no computation. Optional cross-check mart (E.4).

### B.3 `notes` — ENRICH existing, from 商品笔记数据 ×3, merge on `note_id`
- The 3 files are row-disjoint note sets → coalesce-on-`note_id` reduces to a union (no double-count; dedups if they overlap). Already classifies 6/6; keep signature. **Add aliases** so the 30 un-canonicalized cols get stable names:
  `note_type`(笔记类型 图文/视频), `related_product_id/related_product_name`, `video_seconds`, `note_gmv`(笔记支付金额), `note_paid_orders`, `note_paid_buyers`, `product_clicks`(笔记商品点击次数), `product_click_rate_pv`, `product_click_users`, `pay_conversion_pv/_uv`, `note_refund_amount_pay`, `note_refund_rate_pay`, `note_refund_orders_pay`, `add_to_cart_units`, `to_shop_home_count/_gmv`, `to_live_count/_gmv`, `follow_clicks`, `danmu_count`, `avg_read_seconds`, `completion_rate_pv`. (Existing: `title, note_id, publish_time`(笔记创建时间)`, reads, likes, collects, comments, shares`.)

### B.4 `search_overview` — from 搜索总览数据, daily×载体
- Signature: `{date, carrier, card_impression_users, product_click_rate, pay_conversion}` (载体+商卡曝光人数 distinctive).
- Cols: `date, carrier(载体 商卡/笔记), gmv, paid_orders, paid_buyers, card_impression_users(商卡曝光人数), product_click_users, product_click_rate, pay_conversion`.

### B.5 `search_terms` — from 搜索词数据, per-term
- Signature: `{search_term, card_impression_users, product_click_rate, pay_conversion}` (`search_term` unique → clean).
- Cols: `search_term(搜索词), gmv, paid_orders, paid_buyers, card_impression_users, product_click_users, product_click_rate, pay_conversion`.

### B.6 `shop_page_funnel` — from 店铺页转化漏斗, daily×人群×首购周期
- Signature: `{shop_visitors, shop_payers, first_purchase_cycle}` (店铺页访问人数+首购周期 distinctive).
- Cols: `date, audience_type(人群类型 新客/老客), first_purchase_cycle(首购周期), shop_visitors, product_click_users, shop_payers, visit_click_rate, click_pay_rate, visit_pay_rate`.

### B.7 `shop_page_source` — from 店铺页进店来源, daily×人群×来源
- Signature: `{source_page, shop_visitors, enter_pay_rate}` (`source_page` 来源页面 distinctive).
- Cols: `date, audience_type, first_purchase_cycle, source_page(来源页面), shop_gmv, shop_visitors, enter_pay_rate, gmv_per_user(人均支付金额)`.

### B.8 `refund_overview` — from 退款分析概览, period×载体 structure
- Signature: `{carrier, pre_ship_refund_amount, return_refund_amount, refund_users}` distinctive.
- Cols: `stat_period(统计时间), account_type, account_name, carrier(载体), refund_amount_pay, post_ship_refund_amount, shipped_refundonly_amount, pre_ship_refund_amount, return_refund_amount, refund_orders_pay, post_ship_refund_orders, shipped_refundonly_orders, pre_ship_refund_orders, return_refund_orders, refund_rate_pay, post_ship_refund_rate_pay, pre_ship_refund_rate_pay, return_refund_rate_pay, refund_users`.
- Single-row period aggregate → feeds §7 refund **structure** (stage/type split), not per-SKU attribution.

### B.9 `traffic_source` — from 商品笔记-账号流量数据列表, account×渠道×笔记类型
- Signature: `{xhs_id, channel, product_clicks, product_click_users}` (小红书号+渠道 distinctive).
- Cols: `xhs_id(小红书号), account_name, channel(渠道), note_type(笔记类型), gmv, paid_orders, paid_buyers(支付人数), product_clicks, product_click_users, pay_conversion_pv, pay_conversion_uv`.

---

## Section C — Report contract & renderer fix

Unchanged intent from the prior design; still required (root cause #2). Ship independently of ingestion.

### C.1 Result types (`analysis/result.py`)
Add to `Finding`: `confounders: list[str] = []`, `next_test: str | None = None`, `appendix: str | None = None`. Add to `AnalysisResult`: `subsections: list[Subsection] = []`, `named_examples: list[dict] = []`. `Subsection = (title, body, table_name, findings)` so one §-module can carry a rollup table + sub-analyses + named examples.

### C.2 Rendering
- HTML is canonical rich output → renders **all 8** elements. Markdown (`all.md`) renders the **7** operator-facing (all but `evidence_reason`, which stays HTML-only; `test_render_markdown_does_not_render_html_only_evidence_reason` stays green).
- `markdown.py:39-64`: `key_numbers` already rendered (`:50-54`); add `confounders`, `next_test`, `appendix`; render `subsections`/`named_examples` after the finding loop.
- `html.py`: add `confounders/next_test/appendix` to `_finding_view` (`:424-439`) — `evidence_reason` already wired (`:768`); add `subsections/named_examples` to `_result_view` (`:410-421`).
- `report.html.j2:863-897`: guarded blocks + `subsections` loop.
- Labels (`reporting/labels.py`): `confounders: 可能的混淆因素`, `next_test: 下一步验证`, `appendix: 方法与附录`.

### C.3 Anti-filler enforcement
- Omit absent fields (empty/None → nothing; never "N/A"/"无").
- Contract test: fully-populated Finding → all 8 in HTML, 7 in markdown.
- Contract guard (`contracts/finding_contract.py`, unit-tested): STRONG/MEDIUM Finding **must** have non-empty `confounders` and `next_test`, else raise. WEAK/NOT_JUDGABLE exempt.

---

## Section D — Shared analytic helpers (`analytics/`)

Pure, no-I/O, < 150 lines each, fully unit-tested.

- **`periods.py`**: `to_period_month(v)` accepting int `YYYYMMDD` (real daily tables) **and** timestamp strings (`笔记创建时间`); `month_bounds`. Timestamps are Asia/Shanghai wall-clock, bucketed naively — **no UTC/tz conversion** (千帆 exports local time; int dates carry no tz). SQL helper `period_month_expr(col)` handling both int and date/timestamp.
- **`refund_adjust.py`**: `net_gmv(gmv, refund)`, `refund_rate(refund_amount, gmv)`, `refund_order_rate(...)`; None/÷0 → None ("分母不足"). Used mainly as a **cross-check** since the platform ships `net_gmv_pay`/`refund_rate_pay`.
- **`trends.py`**: `pct_change`, `mom_change(series)` → per-period delta/pct/direction, `direction_label` (上升/下降/持平).
- **`confidence.py`** (numbers feeding `evidence.py`, not a parallel enum): `wilson_interval(k,n)`, `min_n_guard(n)` with `MIN_ORDERS_FOR_RATE = 30` → below it a rate is NOT_JUDGABLE and unranked, `rate_band(lo,hi)` plain-language. Comparisons report **CI overlap/non-overlap**, never a p-value (observational data).

---

## Section E — Marts

- **E.1 `business_overview_monthly`**: roll `business_overview_daily` to `period_month`. Sum extensives (gmv, orders, buyers, units, refund amounts). Recompute a rate **only where both its numerator and denominator survive as daily columns** (e.g. `aov = Σgmv/Σorders`, `refund_rate_pay = Σrefund_amount_pay/Σgmv`); for rates whose denominator isn't a daily column (e.g. a UV-based conversion with no daily UV count), omit the rate at monthly grain rather than averaging daily rates. Feeds §2 MoM / §0. Guarded on the daily table's presence.
- **E.2 `note_metrics` view enrichment** (`marts.py:30-59`): expose the new note commerce/refund/type columns + null-safe derived `click_to_order = note_paid_orders / product_clicks`, `gmv_per_click = note_gmv / product_clicks`. Absent columns → NULL; existing `if 'x' in columns` guards still pass.
- **E.3 `sku_performance`**: used directly (already per-SKU aggregate); no derived table required. Optional `category_l2` rollup mart for §4.
- **E.4 Refund cross-check (optional, guarded)**: assert `abs((gmv - refund_amount_pay) - net_gmv_pay) / gmv < 0.01` per SKU/day; on mismatch beyond `REFUND_RECONCILE_TOLERANCE = 0.05`, emit a data-quality caveat naming the file. Prevents blind trust if a caliber is mixed up.
- All marts null-safe via `db/sql_helpers.numeric_expr`; every mart guarded on its source table via `_existing_tables`.

---

## Section F — Graceful degradation & needs-data

- **UNCLASSIFIED files** (below `MIN_TABLE_CONFIDENCE`) and **PNG-only domains** (退款原因, 人群画像) do not crash the build. The loader wraps each file's `guess_table_type` in try/except: a raised `ValueError` (or an ambiguous-margin flag from A.1) is **caught and converted to a needs-data record** — domain name (or "未识别文件"), what's missing, and the manual-entry path — never re-raised. The build continues with the remaining files.
- Provide an optional **manual-entry CSV** convention for the two PNG domains: `references/data_contract/refund_reasons.md` and `audience_profile.md` define a tiny hand-fillable schema (e.g. `refund_reason, refund_amount, refund_orders`); if the operator supplies it, it ingests like any table; if not, §7-reasons / §6-audience emit NOT_JUDGABLE with "请手工录入 / OCR".
- `xhs-ca run all` must succeed on **any subset** of the 12 files (0..N present).

## Evidence strength rules

Reuse `EvidenceStrength`/`score_evidence`. Inputs added (named constants): small sample (`n < MIN_ORDERS_FOR_RATE`) → NOT_JUDGABLE; rate figures carry a Wilson band; refund cross-check mismatch > `REFUND_RECONCILE_TOLERANCE` → caveat + cap MEDIUM; a table assembled from a **single** month/file when trends are claimed → cap MEDIUM and state coverage.

## Report changes

- New Finding labels (C.2). New metric labels: `net_gmv_pay: 退款后GMV`, `refund_rate_pay: 退款率(支付时间)`, `click_to_order: 点击到订单`, `gmv_per_click: 每次点击GMV`, `note_gmv: 笔记支付金额`, `category_l2: 二级品类`, `add_to_cart_users: 加购人数`.
- No new report **sections** in 1a (no new task). Substrate is exercised by existing tasks via Section C and by Phase 2+.

## CLI & task menu

No public-surface change. `xhs-ca build <files...>` (or a whole folder) auto-detects and appends all recognized files; unrecognized/PNG → needs-data. `xhs-ca run all` succeeds on any subset.

## Testing strategy

- `tests/test_mapping.py` — table-scoped `guess_table_type` returns the correct type for **each of the 9 real headers**; the ambiguous-margin path triggers on a crafted collision; catalog-`skus` still beats `sku_performance`.
- `tests/test_duckdb_build.py` — **merge-on-key**: 2 disjoint note files → row count = sum (not last-wins); 2 overview variants over the **same dates** → **one row per date** (not doubled) with columns coalesced from both; a deliberate same-key/same-column conflict beyond tolerance → data-quality caveat; `business_overview_monthly`, enriched `note_metrics` present; an UNCLASSIFIED file → needs-data record, build still succeeds; **`run all` green with any subset incl. empty**.
- `tests/test_report_rendering.py` — all-8 (HTML) / 7 (markdown) contract test; STRONG/MEDIUM guard; omit-when-empty.
- `tests/test_analytics_helpers.py` — `periods` (int-YYYYMMDD & ts, no month-boundary tz shift), `refund_adjust`, `trends`, `confidence` (Wilson known values, min-n suppression).
- **Fixtures derived from the real headers** (anonymized, few rows each): `business_overview_daily.csv` (both variants), `sku_performance.csv`, `notes_commerce.csv`, `search_overview.csv`, `search_terms.csv`, `shop_page_funnel.csv`, `shop_page_source.csv`, `refund_overview.csv`, `traffic_source.csv`. Header text must match the real export exactly (incl. `（支付时间）` full-width parens) so alias tests are meaningful.

## Rollout plan

1. **Section C** (renderer + contract) — independent, ship first.
2. **A.1 table-scoped guess** + **A.2 merge-on-grain-key** + per-type contributing-file provenance — the ingestion backbone; regression-test against the 9 real headers.
3. **B.1–B.9** signatures + alias maps + data-contract docs.
4. **D** helpers + unit tests.
5. **E** marts.
6. **F** needs-data + optional manual-entry schemas.
7. Fixtures + full-subset regression; `references/data_contract/_index.md` updated; note the period assumption in `metric_definitions.md`; caliber note in `xhs_glossary.md`.
8. `sync-runtime` after source changes.

## Phase 1a boundary

Done when: building the **real 12-file export** yields 9 correctly-typed tables with canonical names (退款后GMV, per-note 商品点击率/退款率, 图文/视频, search, shop-funnel all queryable), notes×3 and overview×2 **merge on grain key** (no data loss, no double-count), PNG domains register needs-data, a fully-populated Finding renders all 8 (HTML)/7 (markdown), STRONG/MEDIUM without confounders+next_test fails a test, helpers are pure+tested, and `run all` succeeds on any subset. It does **not** add §3–§7 analysis, the title-tag classifier, or OCR — those are Phases 2–5.

## Open items (mostly resolved by the real data)

- **Caliber** — resolved: rates exist only in 支付时间; `_pay` is the default. Amounts keep both calibers.
- **Time dimension** — resolved: `时间/日期` int YYYYMMDD, `笔记创建时间` local timestamp; no tz.
- **Remaining to confirm at implementation**: whether the operator ever has a **per-order** export (keeps the legacy `orders` path relevant) or is fully aggregate-only; and the exact hand-entry schema for 退款原因 / 人群画像 that best matches how they read those screenshots.
