# 摄入硬化 (Ingestion Hardening) Design

Date: 2026-07-03

Scope note: This is the **first sub-project** of the post-Phase-1a program (before the §2/§5/§7/§6 report modules). Phase 1a made the *structure* layer robust ("降级不拒绝": fuzzy table classification, missing-table degradation via `needs_data`, unknown columns preserved as slugs). But the **Chinese field-name normalization layer is brittle and fails silently** — a Required column whose header wording/punctuation drifts degrades to an un-canonicalized slug, downstream marts `SELECT` the canonical name and get NULL, with **no crash and no signal**. This sub-project makes that failure class **explicit and self-healing** so every later module stands on a hardened base instead of burying one more silent landmine per new table type.

## Background

### The silent-failure class (verified in code)

Three mechanisms in `importing/mapping.py` combine so that a Required column can vanish without any signal:

1. **Aliases are exact-match on specific Chinese strings.** `FIELD_ALIASES[t][canonical]` is a `set` of literal headers (e.g. `refund_users: {"退款人数（支付时间）", "退款人数"}`). A header the set does not contain is not matched.
2. **`_normalize_column_name` only folds ASCII whitespace/hyphens** (`mapping.py:304-306`). It does **not** normalize full-width parentheses. So `退款人数（支付时间）` (full-width `（）`) and `退款人数(支付时间)` (half-width) are *different* normalized strings — a punctuation drift misses the alias.
3. **The fuzzy fallback compares the English canonical name vs the Chinese source** (`fuzz.WRatio("refund_users", "退款人数（支付时间）")` ≈ 0) — so there is **no CJK safety net**. The near-miss is not caught.

When all three miss, `_projected_frame` (`db/build.py:242-257`) sends the unmapped column through `_safe_column_name` → a slug like `退款人数_支付时间`. The typed table builds; the canonical `refund_users` column is simply absent. Downstream (`db/marts.py`) reads it via `numeric_expr`, which returns the SQL literal `NULL` for an absent column, so `SUM(...)` silently yields NULL — **no error, wrong number**. This is exactly how the real bug found in Phase 1a review (`refund_users` from `退款人数（支付时间）`) slipped from plan → code → tests.

The operator's steer (verbatim): *"结构层不会被锁死、数据变了也不会崩;但字段名规范化层对中文表头是偏脆的,而且失败是'静默'的… 建议把这些作为后续模块设计的横切要求写进新 spec,而不是每加一个表类型就多埋一处这样的隐雷。"*

### Design decisions locked in brainstorming

- **Required = downstream hard-dependency, made explicit** (not derived from the classification signature, which is chosen for *discrimination* and systematically omits mart-consumed columns like `net_gmv_pay`; not derived from the `_optional` naming convention, which the new §2/§5/§6/§7 tables do not use, so it over-flags every optional column).
- **Punctuation/caliber-drift is handled deterministically by normalization**, so it never reaches the agent. The only cases that reach the agent are *genuine wording differences* — where language judgment beats string ratio, and where `token_set_ratio` would dangerously collide across calibers (`退款金额（支付时间）` vs `退款金额（退款时间）` differ by one token inside the suffix).
- **The runtime agent is the CJK "fuzzy" mechanism, and its decisions persist.** The tool runs as a skill inside an agent session; the agent adjudicates ambiguous Required columns using semantic, caliber-aware judgment, and writes the result to an overrides file so the build stays deterministic and reproducible, and headless/CI/pytest runs (no agent) are unaffected.
- **Persistence + risk-gated confirmation (hybrid).** Obvious, unique matches are auto-written to the overrides file; ambiguous / caliber-uncertain matches are confirmed with the operator first.

## Goals

- **Explicit, never silent.** A Required column that fails to map to its canonical name is recorded in a queryable `mapping_diagnostics` table with enough context to fix it. Never a silent slug.
- **Deterministic self-healing.** Punctuation / full-width-half-width drift is resolved in code (exact match after normalization); genuine wording drift is resolved once by the runtime agent and frozen into `mapping_overrides.yaml`, after which builds are reproducible.
- **Caliber-safe.** `（支付时间）` vs `（退款时间）` are semantic and map to *different* canonical names; normalization preserves the suffix, and neither code nor agent may blur them.
- **Degrade, never reject.** The build always completes; a missing Required column produces a diagnostic + a degraded table, never an exception. `xhs-ca run all` still succeeds on any subset.
- **Zero regression.** `guess_field_mapping` keeps its `dict[str, str]` contract; all existing call sites (`build.py`, `wizard.py`) and the 250-test suite stay green; the no-agent path behaves like today plus normalization plus diagnostics.

## Non-Goals

- **Any §2/§5/§6/§7 analysis module** — those are the following sub-projects; this one only hardens ingestion.
- **rapidfuzz-based auto-mapping of CJK headers** — explicitly removed. CJK judgment is the agent's; code fuzzy stays only for the pre-existing ASCII/English path (`"Paid Time"` → `paid_time`).
- **OCR of PNG-only domains** (退款原因 图, 人群画像) — unchanged; they remain `needs_data`.
- **Removing or editing existing aliases / `FIELD_ALIASES`** — overrides only *add* (union); the shipped alias sets are unchanged.
- **A strict/fail-fast build mode** — YAGNI; degrade-not-reject is the only mode.

## Architecture

Three layers, each testable in isolation:

```
Layer 1 — Deterministic core (pure, tested, no agent)
  _normalize_column_name  (folds full-width punctuation, preserves caliber suffix)
  exact-alias match       (benefits from normalization)
  ASCII/English fuzzy      (unchanged; CJK no longer routed here)
  overrides merge          (learned aliases unioned into the effective alias set)

Layer 2 — Contract + diagnostics (pure, tested)
  REQUIRED_COLUMNS[t]      (explicit downstream hard-dependencies)
  map_columns() -> ColumnMapping(mapping, diagnostics)
  build writes mapping_diagnostics table   (never raises)

Layer 3 — Agent runtime (SKILL.md instructions; skipped when no agent)
  read mapping_diagnostics -> judge caliber-aware -> obvious auto-write /
  risky confirm -> mapping_overrides.yaml -> re-run build (deterministic thereafter)
```

Data flow (unchanged pipeline, new pieces in **bold**):
`xhs-ca build <files>` → `profile` → **`map_columns`** (was `guess_field_mapping`) → `db.build` (base tables + marts + **`mapping_diagnostics`**) → agent reads diagnostics, writes **`mapping_overrides.yaml`** → re-build.

---

## §1 The Required-column contract — `REQUIRED_COLUMNS`

New module-level dict in `importing/mapping.py`. Each modeled table type lists the canonical columns that downstream code depends on **by canonical name** — grain keys (a missing grain key silently corrupts the coalesce in `_combine_frames`) plus columns any built mart/task `SELECT`s.

```python
REQUIRED_COLUMNS: dict[str, set[str]] = {
    "notes": {"note_id", "publish_time", "title", "reads", "likes", "collects"},
    "products": {"product_id", "product_name", "vessel_type", "series"},
    "skus": {"sku_id", "product_id", "sku_name", "price"},
    "orders": {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"},
    "comments": {"note_id", "comment_time", "comment_text"},
    "content_features": {"note_id", "composition_type", "scene_hint", "copy_angle"},
    "calendar_events": {"date", "event_type", "event_name", "severity"},
    "ad_performance_daily": {"date", "spend", "impressions", "clicks"},
    "business_overview_daily": {
        "date", "gmv", "paid_orders", "paid_buyers", "aov",
        "paid_units", "refund_amount_pay", "net_gmv_pay",   # mart-SUM deps, NOT in signature
    },
    "sku_performance": {"sku_id", "net_gmv_pay", "refund_rate_pay", "add_to_cart_users"},
    "search_overview": {
        "date", "carrier", "gmv", "paid_orders",
        "card_impression_users", "product_click_rate", "pay_conversion",
    },
    "search_terms": {
        "search_term", "gmv",
        "card_impression_users", "product_click_rate", "pay_conversion",
    },
    "shop_page_funnel": {
        "date", "audience_type", "first_purchase_cycle", "shop_visitors", "shop_payers",
    },
    "shop_page_source": {
        "date", "audience_type", "first_purchase_cycle", "source_page",
        "shop_visitors", "enter_pay_rate",
    },
    "refund_overview": {
        "stat_period", "account_name", "carrier",
        "refund_amount_pay", "refund_users", "refund_rate_pay",
        "pre_ship_refund_amount", "post_ship_refund_amount", "return_refund_amount",
    },
    "traffic_source": {
        "xhs_id", "channel", "note_type",
        "gmv", "paid_orders", "product_clicks", "product_click_users",
    },
}
```

Rationale for the non-obvious entries: `business_overview_daily` adds `paid_units, refund_amount_pay, net_gmv_pay` because `create_business_overview_monthly` (`marts.py:78-91`) `SUM`s them via `numeric_expr` — absent → silent NULL. Every `refund_overview` structure column is required because the §7 module decomposes pre/post-ship × return/shipped-only. Grain-key columns (`account_name`, `first_purchase_cycle`, `source_page`, `note_type`, …) are required because `_combine_frames` drops absent keys from the coalesce.

**Invariants (enforced by test, §6):** for every `t` in `TABLE_SIGNATURES`:
- `TABLE_SIGNATURES[t] ⊆ REQUIRED_COLUMNS[t]` — the discriminative signature is always required.
- `REQUIRED_COLUMNS[t] ⊆ TABLE_SIGNATURES[t] ∪ FIELD_ALIASES[t].keys()` — no required column is un-aliasable (would be permanently unmappable).
- `GRAIN_KEYS[t] ⊆ REQUIRED_COLUMNS[t]` for every `t` in `GRAIN_KEYS`.

This turns the previously-implicit "required" notion into a receipted contract that cannot drift from the signatures, aliases, or grain keys without a test failing.

## §2 Normalization — `_normalize_column_name`

Fold full-width punctuation to half-width **before** the existing whitespace/hyphen collapse, and preserve the caliber suffix content.

```python
_FULLWIDTH_PUNCT = str.maketrans({
    "（": "(", "）": ")", "【": "[", "】": "]",
    "，": ",", "、": ",", "：": ":", "　": " ",   # ideographic space
})

def _normalize_column_name(column: str) -> str:
    folded = column.translate(_FULLWIDTH_PUNCT)
    normalized = re.sub(r"[\s\-]+", "_", folded.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")
```

Effect: `退款人数（支付时间）` and `退款人数(支付时间)` both normalize to `退款人数(支付时间)` and now match the same alias. **The suffix is preserved** — `退款人数（支付时间）` → `refund_users` and a future `退款人数（退款时间）` → a different canonical (e.g. `refund_users_refundtime`) stay distinct; nothing strips `（支付时间）`. Aliases are normalized through the same function (`_alias_source_column` already does this), so alias and header meet in one normalized space. This is **additive** — it only merges strings that ASCII-folding left apart — so no existing exact-alias match or classification changes (verified against the current `test_mapping.py` corpus in §6).

## §3 `map_columns` + diagnostics

New richer entry point in `importing/mapping.py`; `guess_field_mapping` becomes a thin, behavior-preserving wrapper.

```python
@dataclass(frozen=True)
class ColumnDiagnostic:
    table_type: str
    required_column: str
    status: str                      # "missing" | "ambiguous"
    candidate_sources: tuple[str, ...]  # unmapped source headers (the agent's candidate pool)
    reason: str                      # Chinese, operator-facing
    action: str                      # Chinese, what to do

@dataclass(frozen=True)
class ColumnMapping:
    mapping: dict[str, str]                 # canonical -> source, exactly as today
    diagnostics: tuple[ColumnDiagnostic, ...]

def map_columns(
    profile: FileProfile,
    table_type: str,
    *,
    overrides: dict[str, dict[str, set[str]]] | None = None,
) -> ColumnMapping: ...

def guess_field_mapping(profile: FileProfile, table_type: str) -> dict[str, str]:
    return map_columns(profile, table_type).mapping
```

`map_columns` logic:
1. Build the **effective alias set** = `FIELD_ALIASES[table_type]` unioned with `overrides.get(table_type, {})` (learned aliases only add).
2. Run the existing exact-alias + ASCII-fuzzy mapping against the effective set (unchanged algorithm, now normalization-aware).
3. Compute `leftover` once per file = the source headers that stayed unmapped after step 2 (the raw Chinese columns that became slugs). For each `col` in `REQUIRED_COLUMNS.get(table_type, set())` **not** in `mapping`, emit one `ColumnDiagnostic`:
   - `candidate_sources` = `leftover` — the **shared** leftover pool for this file (deterministic core cannot know *which* leftover header is *this* column — that is the agent's CJK judgment — so every diagnostic for the file carries the same pool; the agent narrows it).
   - `status` is computed purely from whether that pool is empty: `"ambiguous"` if `leftover` is non-empty (some header is present but unmatched — a wording/caliber drift the agent can adjudicate), else `"missing"` (no leftover header at all — the column is genuinely absent from the file, nothing to adjudicate). No semantic guess is made here.
   - `reason` / `action` are Chinese, e.g. `reason="必填列 refund_users 未匹配到任何表头"`, `action="确认口径后在 mapping_overrides.yaml 补别名"`.

`guess_field_mapping`'s signature and return type are unchanged, so `build.py:243`, `wizard.py:19`, and every `test_mapping.py` assertion keep working verbatim.

### The `mapping_diagnostics` table

A **dedicated** aux table — distinct from `needs_data` (per-*file*: "this file could not be used at all") and `data_quality` (cross-*file* merge conflicts). A missing Required column is per-*table*-per-*column*: the file *was* ingested but a column degraded.

- Schema: `table_name, file, required_column, status, candidate_sources, reason, action` (`candidate_sources` joined with `; `).
- Added to `_AUX_TABLES` in `build.py` so it is dropped/refreshed each build.
- `build_database` loads overrides once (see §4), threads them into `_projected_frame` → `map_columns(profile, table_type, overrides=overrides)`, collects every frame's diagnostics, and writes the table via the existing `_create_table_from_frame` path.
- **Degrade, never reject:** producing a diagnostic never raises; the table still builds with the column absent.

## §4 Persistence — `mapping_overrides.yaml`

The durable home for learned aliases; the mechanism that makes agent judgment deterministic.

- **Format** — `table_type → canonical_name → [chinese_alias, ...]`:
  ```yaml
  refund_overview:
    refund_users:
      - 退款人数
  business_overview_daily:
    net_gmv_pay:
      - 退款后金额
  ```
- **Location** — resolved from the same config that locates the DB (a new optional `overrides_path: Path | None = None` parameter on `build_database`, defaulting to `<db_path>.parent / "mapping_overrides.yaml"`). It lives in the operator's data/config dir, **not** inside the package, so it is stable across the root ↔ runtime-mirror split and is user-inspectable/editable.
- **Loader** — `load_overrides(path) -> dict[str, dict[str, set[str]]]`; returns `{}` when the file is absent or empty. Malformed YAML raises a clear error at build start (fail fast on a corrupt config, but an *absent* config is normal).
- **Merge semantics** — union into the effective alias set; overrides can only *add* aliases, never remove or override a shipped one. A learned alias is normalized through `_normalize_column_name` like any other.

Once an alias is learned, the next build matches it exactly — the judgment is frozen, and reproducibility holds for identical `(export, overrides)`.

## §5 Agent runtime layer — SKILL.md

The CJK judgment lives as **instructions to the running agent**, added to `skills/data-analyze-for-zcl/SKILL.md`. Pure prose + the two data hooks above (`mapping_diagnostics` to read, `mapping_overrides.yaml` to write). Substance:

1. After `xhs-ca build`, query `mapping_diagnostics`. If empty, done.
2. For each row, open the source file's headers and judge, **caliber-aware**, which raw header (if any) is the Required column — understanding that `（支付时间）` / `（退款时间）` are different calibers mapping to different canonicals, and never blurring them.
3. **Risk gate (hybrid):**
   - *Obvious + unique* (exactly one plausible header, same caliber, high confidence) → append the alias to `mapping_overrides.yaml` and re-run `xhs-ca build`.
   - *Ambiguous / caliber-uncertain / multiple candidates* → present the candidates to the operator, get confirmation, then write.
4. Re-running the build applies the learned alias; the column is now canonical and marts see it.

No-agent environments (pytest, CI, headless) never execute Layer 3 — they build with the deterministic core and simply carry the diagnostics table, so the existing suite is unaffected.

## §6 Testing strategy (TDD)

Unit — `tests/test_mapping.py` (+ a new `tests/test_ingestion_hardening.py`):
- **Normalization**: `_normalize_column_name("退款人数（支付时间）") == _normalize_column_name("退款人数(支付时间)")`; and the two calibers stay distinct: `_normalize_column_name("退款人数（支付时间）") != _normalize_column_name("退款人数（退款时间）")`.
- **REQUIRED invariants** (parametrized over table types): `signature ⊆ required ⊆ signature ∪ alias-keys`, and `grain ⊆ required`.
- **`map_columns` diagnostics**: a `refund_overview` profile that is fully mapped **except** `退款人数` is absent (no leftover headers) → one diagnostic, `status="missing"`, `candidate_sources == ()`; a profile whose only `refund_users`-shaped header is a genuinely-unaliased wording (so that header stays in the leftover pool) → `status="ambiguous"` with that header in `candidate_sources`. A complete profile → `diagnostics == ()`.
- **Overrides merge**: with `overrides={"refund_overview": {"refund_users": {"退款人数合计"}}}`, a header `退款人数合计` maps to `refund_users` and produces no diagnostic.
- **Wrapper parity**: `guess_field_mapping(p, t) == map_columns(p, t).mapping` for a representative profile; all pre-existing `test_mapping.py` assertions unchanged and green.
- **`load_overrides`**: absent file → `{}`; well-formed YAML → nested dict of sets; malformed → raises.

Integration — `tests/test_real_export_build.py` (+ additions):
- A build whose `business_overview_daily` file lacks `net_gmv_pay` → build succeeds, `business_overview_monthly` still builds, and `mapping_diagnostics` has a `net_gmv_pay` row (proves explicit-not-silent end-to-end).
- `test_run_all_succeeds_on_any_subset` still passes (degrade-not-reject).
- Golden fixtures carry every Required column so `mapping_diagnostics` is empty on the happy path (add any missing columns to the fixture CSVs as part of the work).

Regression gate: the full root suite (currently **250 passed**) stays green; then `bash skills/data-analyze-for-zcl/scripts/sync-runtime` and confirm the mirror suite.

## File-change map

| File | Change |
|---|---|
| `xhs_ceramics_analytics/importing/mapping.py` | Add `REQUIRED_COLUMNS`, `_FULLWIDTH_PUNCT`, fold in `_normalize_column_name`, `ColumnDiagnostic`/`ColumnMapping` dataclasses, `map_columns`, retarget `guess_field_mapping` as wrapper |
| `xhs_ceramics_analytics/importing/overrides.py` (new) | `load_overrides(path)` + merge helper |
| `xhs_ceramics_analytics/db/build.py` | Load overrides; `_projected_frame`/`_canonical_frame` call `map_columns(..., overrides=...)`; collect diagnostics; add `mapping_diagnostics` to `_AUX_TABLES` + `_create_mapping_diagnostics_table`; `build_database(..., overrides_path=None)` |
| `skills/data-analyze-for-zcl/SKILL.md` | Add the Layer-3 diagnostics→judge→overrides→rebuild instructions |
| `tests/test_ingestion_hardening.py` (new), `tests/test_mapping.py`, `tests/test_real_export_build.py` | Tests above; top up fixtures with Required columns |
| runtime mirror (`skills/data-analyze-for-zcl/assets/xhs-ca/...`) | Regenerated by `sync-runtime` |

## Determinism & compatibility summary

- **Backward-compatible:** `guess_field_mapping` unchanged → `build.py`, `wizard.py`, all tests untouched.
- **Deterministic:** identical `(export, mapping_overrides.yaml)` → identical build. No `Date.now`/random/LLM in the build path.
- **Headless-safe:** overrides file absent → `overrides={}` → today's behavior + normalization + diagnostics; Layer 3 simply doesn't run.
- **Self-healing:** the one manual/agent judgment per genuinely-new header wording is captured once and frozen.
