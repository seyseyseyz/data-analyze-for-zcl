# Content & SKU Diagnosis Expansion — Foundation (Phase 1a) Design

Date: 2026-07-03

## Background

The operator loves two sections of an external reference report (`小红书千帆4-6月经营分析报告`):

- **§3 内容与笔记诊断** — a title-tag rollup (上新 / 鱼盘 / 兴安岭 / 开窑 / 杯 …) with GMV, 商品点击率, 点击→订单, and **退款率** per tag; 图文 vs 视频; 新 vs 旧内容; named high-read/low-convert notes; a 70/20/10 content portfolio and a "买前确认区" template.
- **§4 商品与 SKU 机会** — top products with **退款后GMV, 加购人数, 退款率**, tiered into A (放大稳定款) / B (高GMV降退款) / C (高兴趣弱成交待修款).

The operator asked for these modules to be reproduced, **taken deeper** (statistics, trend/anomaly detection, evidence grading), and made **prescriptive** (ranked actions) — and separately observed that "the tool has 17 templates but the report is short."

### Why the report is short (root cause, evidence-based)

Verified against the actual generated `.xhs-ceramics-analytics/outputs/all.md`:

1. **Each task emits one table + a one-line finding**, not a reasoned section. `references/report_contract.md` requires **8 elements** (conclusion, key numbers, evidence strength, why, confounders, action, next test, appendix). But the `Finding` dataclass has **no field** for `confounders`, `next_test`, or an `appendix` pointer, so no task can emit them; and `evidence_reason` ("why") is **HTML-only by an existing deliberate choice** (enforced by `tests/test_report_rendering.py:38` and `:227`). The richest a markdown finding can get today is conclusion + strength + key_numbers + caveats + action (`markdown.py:39-61`), and most tasks populate only two or three of those. The 8-element contract is **structurally unmeetable until the missing fields exist** — independent of any new data.
2. **No synthesis layer.** `weekly_business_review` reports *which modules ran*, not a business narrative; there is no §0 一句话结论, no §2 month-over-month trend, no §8 action matrix.
3. **Whole domains are missing** — no search, refund, or audience tasks.

### The program (context; only Phase 1a is specced here)

| Phase | Delivers |
|---|---|
| **1a Foundation core** *(this doc)* | Report-contract + renderer fix · shared helpers (refund-adjust / trends+period / confidence) · refunds ingestion + 退款后GMV mart · `note_commerce` optional table |
| **1b Foundation tagging** | Title-tag classifier (rules + state-dir config + auto-suggest, fractional GMV attribution) · `search_terms` / `audience` / `shop_page` ingest-only stubs |
| **2 Content & Note Diagnosis** | Deep §3 module (tag rollup, 图文vs视频, 新vs旧, named weak notes, portfolio + 买前确认区), note-GMV provenance resolver |
| **3 Product & SKU Opportunity** | 退款后GMV, 加购, A/B/C tiers, refund-driver decomposition, ranked fix-lists |
| **4 New domains** | Search diagnosis (§5), Refund/after-sales (§7), Audience/shop-page (§6) |
| **5 Synthesis brain** | Rebuild `weekly_business_review`: §0 一句话结论, §2 MoM core-overview, §8 30-day action matrix, §9 needs-data |

This design was hardened by a research + adversarial-review pass (千帆 schema research, codebase-wiring verification, and skeptical critique). The scope cut below (Phase 1a vs 1b) is the critique's recommended cut-line: ship the root-cause fix and the single most decision-relevant new number (退款后GMV) first; defer the highest-risk subsystem (tagging) and speculative ingest to 1b.

## Goals (Phase 1a)

- Make **every** task capable of emitting the full 8-element report contract, and enforce it for STRONG/MEDIUM findings. This alone fixes the "thin report" root cause.
- Add three small, pure, reusable analytic helpers used by all later phases: refund adjustment, period-aware trends, and honest small-sample confidence.
- Add first-class ingestion for an optional **`refunds`** export and a **退款后GMV** (`sku_net_gmv`) mart.
- Add an optional **`note_commerce`** table (per-note 商品点击 / 笔记GMV / 支付订单数) joined into the existing `note_metrics` view.
- Establish the **period/time dimension** that §2 trends and §0 summary depend on.
- Keep everything **gracefully degrading**: missing table/column → the module degrades and says what to export next, never crashes.

## Non-Goals (deferred)

- The **title-tag classifier** and its config, auto-suggest, and fractional-attribution rollup → **Phase 1b**.
- `search_terms`, `audience_profile`, `shop_page_funnel` ingestion → **Phase 1b** (ingest-only stubs), consumed in **Phase 4**.
- The **note-GMV provenance resolver** and the note-commerce ↔ `note_sku_links` attribution-model decision → **Phase 2** (where it is consumed). Phase 1a only *ingests* `note_commerce` and joins it into the view.
- Per-product **加购人数** (`add_to_cart_users`) ingestion → **Phase 3** (where the A/B/C C-tier consumes it). Not on any note table.
- Any new analysis **task/registry entry**. Phase 1a changes the ingestion/mart/renderer substrate only; the first consuming task is Phase 2.

## Current architecture fit

The change follows the existing pipeline and touches no new reporting path:

1. `xhs-ca build <files>` → `importing.mapping` guesses table type + normalizes columns.
2. `db.build` writes DuckDB base tables and derived marts/views.
3. `analysis.registry` exposes task IDs; modules return `AnalysisResult` / `Finding`.
4. `reporting.markdown` / `reporting.html` render findings, tables, caveats, actions.

Verified anchors (from codebase-wiring pass):

- `note_metrics` is a **VIEW** over `notes` (`db/marts.py:30-59`), built conditionally at `db/build.py:39-40`; `daily_sku_sales` is a derived **TABLE** (`db/build.py:208-252`). → we cannot "add columns to `note_metrics`"; a new base table is required.
- `TABLE_SIGNATURES` (`importing/mapping.py:11-33`) drives table-type guessing and auto-registers drop/refresh (`build.py:47-52`).
- `FIELD_ALIASES` is per-table `{table: {canonical_col: {aliases}}}` (`mapping.py:35-98`); `_canonical_column_name` scans **all** tables' aliases globally, first-match wins (`mapping.py:151-158`) — new tables must disambiguate on table-unique columns.
- Pydantic validation is wired **only for `orders`** (`build.py:34-35`, `normalize.py:119-137`); other tables load via raw projection. New tables may skip Pydantic.
- **PyYAML is already a dependency** (`pyproject.toml:11`, used in `importing/wizard.py`). Config uses YAML; no new dependency.
- `Finding` / `AnalysisResult` live in `analysis/result.py:6-23`; markdown render loop `reporting/markdown.py:39-64`; HTML `_finding_view`/`_result_view` `reporting/html.py:410-439`; Jinja finding card `reporting/templates/report.html.j2:863-897`.

---

## Section A — Report contract & renderer fix (fixes root cause #1)

**Do this first and independently.** It has zero new-data dependencies and unlocks every later phase; without it, richer data still renders as a thin report.

### A.1 Extend the result types

`analysis/result.py`:

```python
@dataclass
class Finding:
    title: str
    conclusion: str
    evidence_strength: EvidenceStrength
    key_numbers: dict[str, object] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    evidence_reason: str | None = None
    confounders: list[str] = field(default_factory=list)   # NEW — was jammed into caveats
    next_test: str | None = None                           # NEW
    appendix: str | None = None                            # NEW — SQL/methodology or output-file pointer

@dataclass
class AnalysisResult:
    task_id: str
    title: str
    findings: list[Finding]
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    subsections: list["Subsection"] = field(default_factory=list)   # NEW
    named_examples: list[dict[str, object]] = field(default_factory=list)  # NEW
```

`Subsection` is a small dataclass `(title: str, body: str | None, table_name: str | None, findings: list[Finding])` so one section (e.g. §3) can carry a tag table **and** 图文vs视频 **and** named weak notes in one `AnalysisResult`.

### A.2 Render the contract elements

The HTML report is the canonical rich deliverable and must render **all 8** elements. Markdown (`all.md`) is the terse operator digest and renders the **7 operator-facing** elements — everything except `evidence_reason` ("why"), which stays **HTML-only** by the existing deliberate design (do not "fix" `markdown.py` to emit it; `test_render_markdown_does_not_render_html_only_evidence_reason` must stay green).

- `reporting/markdown.py:39-64`: `key_numbers` is **already rendered** (`:50-54`); add `confounders` (list, like `caveats`), `next_test` (scalar, like `recommended_action`), and an `appendix` pointer. After the finding loop, render `subsections` (mirror the `limitations` block at `markdown.py:34-38`) and `named_examples`. Do **not** add `evidence_reason`.
- `reporting/html.py`: add `confounders`, `next_test`, `appendix` to `_finding_view` (`:424-439`) — `evidence_reason` is already wired (`html.py:768`); add `subsections`, `named_examples` to `_result_view` (`:410-421`). `next_test` already has a `_FIELD_LABELS` entry (`html.py:94`).
- `reporting/templates/report.html.j2:863-897`: add `{% if finding.confounders %}` / `{% if finding.next_test %}` / `{% if finding.appendix %}` guarded blocks copying the `caveats` / `recommended_action` markup; add a `subsections` loop in the result block.

### A.3 Anti-filler enforcement (the important part)

- **Omit absent fields** — never print "confounders: 无" / "N/A". Empty list / None → nothing renders.
- Add a **contract test** (`tests/test_report_rendering.py`): for a fully-populated `Finding`, all **8** elements appear in the **HTML** output, and the **7** operator-facing elements (all but `evidence_reason`) appear in the **markdown** output. The existing `test_render_markdown_does_not_render_html_only_evidence_reason` (`:38`) stays green.
- Add a **contract guard** (unit-tested helper `contracts/finding_contract.py`): a `Finding` with `evidence_strength ∈ {STRONG, MEDIUM}` **must** have non-empty `confounders` and `next_test`, else the guard raises in tests (so future tasks can't regress to one-liners). WEAK / NOT_JUDGABLE are exempt (they legitimately have less to say).

### A.4 Report labels

Add Chinese labels for the new fields to `reporting/labels.py` / `_FIELD_LABELS`:
`confounders: 可能的混淆因素`, `next_test: 下一步验证`, `appendix: 方法与附录`.

---

## Section B — Shared analytic helpers (`analytics/`)

Three focused modules, each < 150 lines, one job, fully unit-tested. They hold **no I/O** — pure functions over numbers — so later phases compose them freely.

### B.1 `analytics/refund_adjust.py`

```python
def net_gmv(gmv: float | None, refund: float | None) -> float | None      # gmv - refund, None-safe
def refund_rate(refund_amount, gmv) -> float | None                        # None if gmv <= 0
def refund_order_rate(refund_orders, orders) -> float | None
```

Divide-by-zero / None → `None` (renders as "分母不足", matching `ad_metrics` convention).

### B.2 `analytics/periods.py`  (the missing time dimension)

**Decision:** treat all 千帆-exported timestamps as **Asia/Shanghai wall-clock** and bucket **naively** — explicitly do **not** apply any UTC conversion (this sidesteps DuckDB's ICU-extension requirement and is correct because 千帆 exports local time).

```python
def to_period_month(ts) -> str | None          # 'YYYY-MM' from a naive local timestamp
def month_bounds(period_month: str) -> tuple[date, date]
```

Plus a SQL helper in `db/sql_helpers.py`: `period_month_expr(col) -> "strftime(col, '%Y-%m')"` (no `AT TIME ZONE`). Document the assumption in `references/metric_definitions.md`.

### B.3 `analytics/trends.py`

```python
def pct_change(cur, prev) -> float | None
def mom_change(series: list[tuple[str, float]]) -> list[dict]   # period, value, delta, pct, direction
def direction_label(pct) -> str                                # 上升 / 下降 / 持平, plain language
```

### B.4 `analytics/confidence.py`  (honest statistics, not a parallel enum)

**Constraint:** `evidence.py` already owns categorical strength via `score_evidence(...)`. `confidence.py` must **not** introduce a second strength enum. It returns **numbers** that *feed* `score_evidence`:

```python
def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float]  # binomial proportion CI
def min_n_guard(n: int, threshold: int) -> bool                              # False -> suppress/NOT_JUDGABLE
def rate_band(lo: float, hi: float) -> str                                  # plain-language, e.g. "约 12%–18%"
```

Rules enforced by tests (thresholds are module-level named constants, tunable in one place):
- `MIN_ORDERS_FOR_RATE = 30` — a rate on `n < 30` orders is **suppressed** (return NOT_JUDGABLE upstream, do not rank).
- Rate comparisons report **CI overlap / non-overlap**, never a p-value (observational, confounded data → no significance claims).
- The tool must not print "退款率 40%" on 5 orders without the interval — that is the "fake certainty" the contract forbids.

---

## Section C — Refunds ingestion + 退款后GMV mart

### C.1 Standard table `refunds` (optional)

One row per refund event, at the finest grain the export provides.

Required:
- `refund_id`
- `refund_amount`
- **at least one of** `{order_id, sku_id}` **non-null** (join-key requirement — otherwise the row cannot attribute and would silently undercount 退款后GMV)

Optional:
- `order_id`, `sku_id`, `note_id`
- `refund_time`
- `refund_reason` (free text / enum value; see C.3)
- `refund_stage` — `发货前` / `发货后`
- `minutes_to_refund` (for the "30 分钟内退款" cut)
- `carrier` — `商卡` / `笔记` (成交渠道 the refund is attributed to)
- `refund_type` — `仅退款` / `退货退款`
- `refund_caliber` — `支付时间口径` / `退款时间口径` (千帆 reports both; keep distinct, never alias together)
- `raw_file`, `raw_row_id`

### C.2 Import & mapping

Add to `TABLE_SIGNATURES` (`mapping.py:11-33`), leaning on refunds-unique columns so `订单号` doesn't collide with `orders`:

```python
"refunds": {"refund_id", "refund_amount", "refund_reason_optional", "order_id", "sku_id_optional"},
```

Add `FIELD_ALIASES["refunds"]`. Confidence tags: **[G]** = ground-truth from the PiGoo report, **[C]** = platform-confirmed vocabulary, **[I]** = inferred, **confirm against one real export before trusting [I]**:

```text
refund_id:        退款单号, 售后单号, 退款id                      # [I]
order_id:         订单号, 订单编号, 订单id                        # [C]
sku_id:           规格id, 规格ID, skuid                           # [C]
note_id:          笔记id, 笔记ID                                  # [C]
refund_amount:    退款金额, 退款总金额, 成功退款金额              # [G]
refund_time:      退款时间, 售后完成时间                          # [I]
refund_reason:    退款原因, 售后原因                              # [C]
refund_stage:     发货前退款, 发货后退款  (→ 发货前/发货后)       # [G]
minutes_to_refund: 支付后退款时长, 支付到退款分钟数              # [I]
carrier:          退款渠道, 成交渠道  (商卡/笔记)                 # [G]
refund_type:      仅退款, 退货退款  (→ refund_type value)         # [C]
refund_caliber:   退款率口径  (支付时间口径/退款时间口径)         # [G]
```

`refund_reason` values are **row values, not headers** — register the canonical enum in `references/xhs_glossary.md`, not as alias keys:
`多拍/拍错/不想要 · 尺寸/款式没选对 · 与商家协商一致退款 · 商品价格问题 · 快递/物流一直未送到 · 缺货 · 商家发错货 · 做工粗糙/有瑕疵 · 退运费 · 其他`.

Refunds load via the **raw projection path** (no Pydantic required). Optional: add a `Refund` schema + `normalize_refund_rows` later if validation is wanted (copy `OrderLine` / `normalize_order_rows`).

### C.3 Reconciliation with existing order-level refund flag

`daily_sku_sales` already nets out in-line refunds via `orders.refund_status_optional` (`build.py:217-236`). With a dedicated `refunds` table there are **two** refund sources. Rule:

- When a `refunds` table is present, it is **authoritative** for refund **amount / reason / timing**. The order-level flag is used only for a **cross-check**, never summed on top (prevents double-counting).
- Emit a **reconciliation caveat** when total refund amount from the two sources differs by more than `REFUND_RECONCILE_TOLERANCE` (0.05), telling the operator which export to trust.

### C.4 Mart `sku_net_gmv` (退款后GMV)

Derived TABLE (register in `_DERIVED_TABLES`, `build.py:21`; guarded call after `build.py:42`):

```text
sku_net_gmv(sku_id, period_month, gmv, refund_amount, net_gmv, refund_rate,
            refund_join_coverage)
```

- `net_gmv = gmv - COALESCE(refund_amount, 0)` via LEFT JOIN `refund_by_sku`.
- `refund_join_coverage` = share of refund amount that resolved to a SKU. **Low coverage downgrades evidence** in any consuming task, and the number is surfaced ("退款关到 SKU：82%").
- Companion marts: `refund_by_sku`, `refund_by_reason`, `refund_by_note` (all guarded on `refunds` presence, all None-safe via `db/sql_helpers.numeric_expr`).

---

## Section D — `note_commerce` optional table

Per the architecture fact that `note_metrics` is a view, per-note commerce lands in a **new base table**, LEFT JOIN-ed into the `note_metrics` view (columns are NULL when the table is absent — graceful degradation, `notes` stays stable).

### D.1 Table `note_commerce` (optional)

Required: `note_id`. Optional: `product_clicks`, `note_gmv`, `note_orders`, `period_month`, `raw_file`, `raw_row_id`.

Aliases:

```text
note_id:        笔记id, 笔记ID                                   # [C]
product_clicks: 商品点击, 商品点击量, 商品点击人数                # [C/I]
note_gmv:       笔记支付金额, 笔记GMV, 内容支付金额, 笔记成交金额  # [G]
note_orders:    支付订单数, 支付订单量, 成交订单数                # [C/G]
```

Signature: `{"note_id", "note_gmv", "product_clicks", "note_orders"}`.

### D.2 View join

Extend `create_note_metrics_view` (`marts.py:30-59`) to `LEFT JOIN note_commerce USING (note_id)` **only when the table exists**, exposing `product_clicks`, `note_gmv`, `note_orders`, plus null-safe derived `click_to_order = note_orders / product_clicks` and `gmv_per_click = note_gmv / product_clicks`. When `note_commerce` is absent, these columns are NULL and every existing `if 'x' in columns` guard still passes.

**Explicitly deferred to Phase 2:** the note-GMV **provenance resolver** (prefer platform-direct `note_commerce.note_gmv` = STRONG-eligible; fall back to `note_sku_links` `confidence`/`link_type`-weighted attribution = WEAK/MEDIUM) and the decision of how §3 blends the two. `note_commerce` and `note_sku_links` are **complementary, not substitutes** — note-level GMV vs note→SKU attribution — and `note_sku_links` is not deprecated.

---

## Evidence strength rules

Reuse `EvidenceStrength` / `score_evidence`. Phase 1a adds these provenance/quality inputs (thresholds are named constants):

- **Refund join coverage** below `LOW_JOIN_COVERAGE = 0.70` → downgrade any 退款后GMV / refund-rate finding one level and state coverage.
- **Small sample** (`min_n_guard` False, i.e. `n < MIN_ORDERS_FOR_RATE`) → NOT_JUDGABLE, do not rank; emit "样本太小，暂不判断".
- **Rate figures** carry a Wilson interval; conclusions phrased as bands, not point certainties.
- **Reconciliation mismatch** between refund sources beyond `REFUND_RECONCILE_TOLERANCE = 0.05` → add a caveat and cap at MEDIUM.

## Report changes

- New field labels (A.4): 可能的混淆因素 / 下一步验证 / 方法与附录.
- New metric labels: `net_gmv: 退款后GMV`, `refund_rate: 退款率`, `refund_join_coverage: 退款关联覆盖率`, `click_to_order: 点击到订单`, `gmv_per_click: 每次点击GMV`, `note_gmv: 笔记支付金额`.
- No new report *sections* in Phase 1a (no new task). The substrate is exercised by existing tasks gaining fuller findings via Section A, and by Phase 2+ tasks.

## CLI & task menu

No public-surface change. `xhs-ca build <files...>` auto-detects `refunds` and `note_commerce` by signature (`cli.py:18-31`). `xhs-ca run all` must continue to succeed when neither optional table is present.

## Testing strategy

- `tests/test_report_rendering.py` — all-8-elements contract test; STRONG/MEDIUM contract-guard test; omit-when-empty test (no "N/A" filler).
- `tests/test_mapping.py` — `guess_table_type` detects `refunds` and `note_commerce`; alias mapping including collision cases (`订单号` stays with `orders`).
- `tests/test_duckdb_build.py` — build imports `refunds` / `note_commerce`; `sku_net_gmv`, `refund_by_*` marts; `note_metrics` view gains commerce columns; **`all` succeeds with the optional tables absent**.
- New `tests/test_analytics_helpers.py` — `refund_adjust`, `periods` (naive Asia/Shanghai month bucketing; no UTC shift across month lines), `trends`, `confidence` (Wilson interval known values, min-n suppression).
- Reconciliation test — refunds table vs `orders.refund_status_optional` disagreement emits a caveat and does not double-count.

Fixtures: `tests/fixtures/refunds.csv` (with reason / stage / carrier / minutes columns, and a row missing `sku_id` but having `order_id` to exercise the join-key rule), `tests/fixtures/note_commerce.csv`.

## Rollout plan

1. Section A: extend `Finding`/`AnalysisResult`, renderers, labels, contract test + guard. **(ship-able alone)**
2. Section B: `analytics/refund_adjust.py`, `periods.py`, `trends.py`, `confidence.py` + unit tests.
3. Section C: `refunds` signature + aliases; enum in glossary; raw load; `refund_by_*` + `sku_net_gmv` marts; reconciliation caveat.
4. Section D: `note_commerce` signature + aliases + raw load; extend `note_metrics` view.
5. Update `references/data_contract/` (add `refunds.md`, `note_commerce.md`; note the period assumption in `metric_definitions.md`).
6. Fixtures + regression tests; `xhs-ca run all` green with and without optional tables.
7. Sync bundled skill assets (`sync-runtime`) after source changes.

## Phase 1a boundary

Phase 1a is done when:

- A fully-populated `Finding` renders **all 8 contract elements**, and a STRONG/MEDIUM finding without `confounders`+`next_test` fails a test.
- Importing a `refunds` export produces a **退款后GMV** number per SKU with a stated join-coverage, and importing a `note_commerce` export surfaces 点击到订单 / 每次点击GMV on `note_metrics`.
- Every helper is pure and unit-tested; rate figures never over-claim on small samples.
- `xhs-ca run all` still succeeds when refunds / note_commerce are absent.

It does **not** add the title-tag rollup, any new report section, search/audience ingestion, or the attribution resolver — those are Phases 1b–5.

## Open items to confirm

- **[I]-tagged aliases** (`refund_id`, `refund_time`, `minutes_to_refund`, `product_clicks` UV vs count) should be checked against **one real 千帆 export** before release; the alias sets above include 2–3 variants each as a hedge.
- **Refund-rate caliber**: default reporting caliber (支付时间口径, per the PiGoo report) — confirm this is the operator's preferred default.
