# Phase 1a · Plan 3 — Real 千帆 Export Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the operator's real 4–7月 千帆 export **losslessly and correctly** — each of the 9 tabular files lands in its own typed table with stable canonical column names; multiple files of one type **merge on a declared grain key** (row-disjoint files union, column-view files coalesce) instead of silently overwriting; PNG-only domains register as needs-data; the build never crashes on any subset.

**Architecture:** (A.1) Replace the global-canonicalization guesser with **table-scoped** scoring — each candidate type scores its own signature under its own aliases — plus an ambiguity margin. (A.2) Rewrite the loader from "one `CREATE TABLE` per file" to "group files by type → build one canonical frame per file → concat → coalesce on the type's grain key → one `CREATE TABLE` per type." (B) Add 9 table types (signatures + full alias maps + grain keys + data-contract docs). (E) Add a monthly rollup mart + enrich `note_metrics`. (F) Wrap classification in try/except → a `needs_data` table; PNG/unreadable files degrade instead of raising.

**Tech Stack:** Python 3.11+, DuckDB, pandas, rapidfuzz (already deps). Depends on **Plan 2** (`xhs_ceramics_analytics.analytics.periods`/`refund_adjust`).

## Global Constraints

- Python **3.11+**; ruff **line-length = 100**.
- Constants (verbatim): `MIN_TABLE_CONFIDENCE = 0.25` (existing), `MIN_FIELD_CONFIDENCE = 80` (existing), **`MARGIN = 0.15`** (new), `REFUND_RECONCILE_TOLERANCE = 0.05` (new, Task 12).
- **Canonical naming** (A.3): channel split `note_`/`card_` prefix; refund caliber suffix `_pay` (支付时间) / `_refundtime` (退款时间) — **rates exist only in `_pay`**; ship stage `pre_ship_`/`post_ship_`; keep platform `_pv`/`_uv` rate-denominator suffix.
- `_normalize_column_name` only lowercases and collapses spaces/hyphens — **Chinese characters and full-width parens `（）` survive unchanged**, so every alias RHS must be the exact header text (e.g. `"退款后支付金额（支付时间）"`, not a half-width variant).
- 退款后GMV (`net_gmv_pay`) is **platform-given** — ingest the column, never compute it (cross-check only, Task 12).
- The legacy per-order `orders` path stays behavior-identical (compatibility) — it is not in `GRAIN_KEYS`, so multiple order files union and a single file is unchanged.
- **Read-only source data:** never modify the WeChat export dir `小红书千帆4-7月数据` or the reference HTML. Read it only via throwaway scripts under `/tmp`.
- No `Co-Authored-By` trailer on commits. Prereq: Plan 1 Task 0 (WIP committed, clean tree).

---

### Task 1: Table-scoped `guess_table_type` with ambiguity margin (A.1)

**Files:**
- Modify: `xhs_ceramics_analytics/importing/mapping.py` (`guess_table_type` 106-118; add `_table_scoped_hits`, `AmbiguousTableTypeError`, `MARGIN`; `_canonical_column_name` becomes unused → remove)
- Test: `tests/test_mapping.py` (add tests)

**Interfaces:**
- Produces:
  - `MARGIN = 0.15`
  - `class AmbiguousTableTypeError(ValueError)`
  - `guess_table_type(profile) -> str` (same signature; now raises `AmbiguousTableTypeError` when top-2 scores are within `MARGIN`, plain `ValueError` when below `MIN_TABLE_CONFIDENCE`).
  - `_table_scoped_hits(columns: list[str], table_type: str) -> int`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mapping.py  (add)
import pytest

from xhs_ceramics_analytics.importing.mapping import (
    AmbiguousTableTypeError,
    guess_table_type,
)
from xhs_ceramics_analytics.importing.profile import FileProfile


def _profile(columns):
    return FileProfile(
        path=None, table_name="t", columns=columns, row_count=1, sample_rows=[]
    )


def test_below_threshold_raises_plain_valueerror():
    with pytest.raises(ValueError) as excinfo:
        guess_table_type(_profile(["完全不相关的列名"]))
    assert not isinstance(excinfo.value, AmbiguousTableTypeError)


def test_tie_between_products_and_skus_is_ambiguous():
    # "商品ID" alone hits products.product_id AND skus.product_id → 0.25 vs 0.25,
    # SAME raw hit count (1 each) → a genuine collision, still ambiguous.
    with pytest.raises(AmbiguousTableTypeError):
        guess_table_type(_profile(["商品ID"]))


def test_partial_notes_file_still_classifies_as_notes():
    # Regression guard (pre-existing test_final_review_regressions.py depends on this):
    # a column-sparse but valid notes export must NOT trip the ambiguity margin.
    # notes matches 2 signature columns (note_id + publish_time) while comments
    # matches only 1 (note_id self-matches its own target name), so on normalized
    # coverage notes 2/6 == comments 1/3 — a 0.00 gap < MARGIN — yet notes clearly
    # explains MORE real columns. The raw-hit tie-break must resolve this to notes,
    # not raise AmbiguousTableTypeError (which Task 3 would divert into needs_data,
    # leaving the notes table unbuilt and breaking account_baseline).
    assert guess_table_type(_profile(["note_id", "publish_time"])) == "notes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mapping.py -k "below_threshold or ambiguous" -v`
Expected: FAIL — `ImportError: cannot import name 'AmbiguousTableTypeError'`.

- [ ] **Step 3: Write the implementation**

In `mapping.py`, add near the top constants:

```python
MARGIN = 0.15


class AmbiguousTableTypeError(ValueError):
    """Raised when two table types score within ``MARGIN`` of each other."""
```

Replace `guess_table_type` (106-118) and delete `_canonical_column_name` (151-158; now unused). Add `_table_scoped_hits`:

```python
def guess_table_type(profile: FileProfile) -> str:
    hits = {
        table: _table_scoped_hits(profile.columns, table) for table in TABLE_SIGNATURES
    }
    scores = {
        table: hits[table] / len(signature)
        for table, signature in TABLE_SIGNATURES.items()
    }
    # Rank by normalized coverage, breaking ties by raw hit count: a type that
    # matches MORE of the file's actual columns is the better fit even when a
    # smaller signature ties it on coverage. Without this, a column-sparse notes
    # file [note_id, publish_time] scores notes 2/6 == comments 1/3 (comments'
    # note_id self-matches its target name) and is wrongly called ambiguous.
    ranked = sorted(
        scores.items(),
        key=lambda item: (item[1], hits[item[0]]),
        reverse=True,
    )
    table_type, score = ranked[0]
    runner_up_type, runner_up = (ranked[1][0], ranked[1][1]) if len(ranked) > 1 else ("", 0.0)
    if score < MIN_TABLE_CONFIDENCE:
        raise ValueError(
            f"Could not guess table type for {profile.table_name!r}; "
            f"best match {table_type!r} scored {score:.2f}."
        )
    # Only a genuine collision — within MARGIN AND matching no more real columns
    # than the runner-up — is ambiguous. A strictly higher raw-hit count resolves
    # the normalization artifact above.
    if score - runner_up < MARGIN and hits[table_type] <= hits.get(runner_up_type, 0):
        raise AmbiguousTableTypeError(
            f"Ambiguous table type for {profile.table_name!r}: "
            f"{table_type!r} ({score:.2f}, {hits[table_type]} hits) vs "
            f"{runner_up_type!r} ({runner_up:.2f}, {hits.get(runner_up_type, 0)} hits)."
        )
    return table_type


def _table_scoped_hits(columns: list[str], table_type: str) -> int:
    source_columns = [(column, _normalize_column_name(column)) for column in columns]
    signature = TABLE_SIGNATURES[table_type]
    return sum(
        1
        for target in signature
        if _alias_source_column(source_columns, table_type, target, set()) is not None
    )
```

- [ ] **Step 4: Run tests to verify they pass, and guard against regressions**

Run: `pytest tests/test_mapping.py tests/test_final_review_regressions.py -v`
Expected: new tests PASS **and every pre-existing mapping test still PASS** (notes/orders/products/skus/ad classifications and the Chinese-qianfan tests). `test_final_review_regressions.py` is included here on purpose: its `test_build_and_run_all_tolerates_partial_note_export` builds from a `[note_id, publish_time]`-only file, so it exercises the exact ambiguity edge the raw-hit tie-break fixes — running it now catches the regression at this task instead of hiding until the final `pytest -q`. The existing fixtures all classify with a top-2 gap well above 0.15 (or, when within 0.15, a strictly higher raw-hit count); if any file genuinely ties on BOTH coverage and raw hits, that is a real signature collision — fix it by widening the losing signature, **never** by lowering `MARGIN`.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py tests/test_mapping.py
git commit -m "feat(mapping): table-scoped classification with ambiguity margin"
```

---

### Task 2: Grain keys + merge-on-grain-key loader (A.2)

**Files:**
- Modify: `xhs_ceramics_analytics/importing/mapping.py` (add `GRAIN_KEYS`)
- Modify: `xhs_ceramics_analytics/db/build.py` (rewrite `build_database` + loader; remove `_load_csv_table`/`_load_dataframe_table`/`_load_csv_orders_table`/`_duckdb_csv_columns`/`_projected_columns`; add `_group_files_by_type`/`_canonical_frame`/`_combine_frames`/`_create_table_from_frame`; modify `_projected_frame`)
- Test: `tests/test_duckdb_build.py` (add tests)

**Interfaces:**
- Consumes: `guess_table_type` (Task 1), existing `_normalized_frame`/`_write_staging_csv`/`_safe_column_name`/`_unique_name`/`_existing_tables`/`_quote_identifier`.
- Produces:
  - `GRAIN_KEYS: dict[str, tuple[str, ...]]` in `mapping.py` — types listed here coalesce on their key; all others (incl. `orders`) plain-union.
  - `_group_files_by_type(con, files) -> dict[str, list[tuple[str, pd.DataFrame]]]` — each value is a list of `(file_name, canonical_frame)` pairs; the file name is carried so Task 3 can record provenance (`build_manifest`) and cross-file conflicts (`data_quality`).
  - `_canonical_frame(con, file, profile, table_type) -> pd.DataFrame`
  - `_combine_frames(frames: list[pd.DataFrame], table_type) -> pd.DataFrame` — takes bare frames (callers unpack the pairs).
  - `_create_table_from_frame(con, db_path, table_type, frame) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_duckdb_build.py  (add)
import duckdb

from xhs_ceramics_analytics.db.build import build_database


_NOTE_HEADER = "笔记id,发布时间,笔记标题,阅读次数,点赞数,收藏数"


def test_disjoint_notes_files_union_not_overwrite(tmp_path):
    (tmp_path / "notes_a.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,100,10,5\nn2,2026-04-02,标题2,200,20,8\n",
        encoding="utf-8",
    )
    (tmp_path / "notes_b.csv").write_text(
        f"{_NOTE_HEADER}\nn3,2026-04-03,标题3,300,30,9\nn4,2026-04-04,标题4,400,40,7\n",
        encoding="utf-8",
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "notes_a.csv", tmp_path / "notes_b.csv"])
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM notes").fetchone()[0] == 4  # not 2 (overwrite)
    con.close()


def test_same_key_column_views_coalesce(tmp_path):
    # both files describe note n1; each carries a column the other lacks.
    # Use never-aliased column names (扩展甲/扩展乙) so the assertion column names
    # stay stable — a real metric like 笔记支付金额 gets renamed to its canonical
    # column (note_gmv) once notes aliases are enriched (Task 6), which would break
    # this test at a later task. `_safe_column_name` keeps Chinese word chars verbatim.
    (tmp_path / "notes_a.csv").write_text(
        f"{_NOTE_HEADER},扩展甲\nn1,2026-04-01,标题1,100,10,5,999\n", encoding="utf-8"
    )
    (tmp_path / "notes_b.csv").write_text(
        f"{_NOTE_HEADER},扩展乙\nn1,2026-04-01,标题1,100,10,5,42\n", encoding="utf-8"
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "notes_a.csv", tmp_path / "notes_b.csv"])
    con = duckdb.connect(str(db))
    frame = con.execute("SELECT * FROM notes").fetchdf()
    con.close()
    assert len(frame) == 1  # one row per note_id (coalesced, not doubled)
    row = frame.iloc[0]
    assert row["扩展甲"] == 999   # filled from file A
    assert row["扩展乙"] == 42    # filled from file B
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_duckdb_build.py -k "union_not_overwrite or coalesce" -v`
Expected: FAIL — `test_disjoint...` yields 2 rows (last-file overwrite) or errors; `test_same_key...` yields 2 rows.

- [ ] **Step 3a: Add `GRAIN_KEYS` to `mapping.py`**

After `TABLE_SIGNATURES` / `FIELD_ALIASES`, add:

```python
# Types listed here coalesce on their grain key (one row per key, first-non-null
# per column). Types NOT listed (orders, products, skus, comments, calendar_events,
# content_features, ad_performance_daily) plain-union across files.
GRAIN_KEYS: dict[str, tuple[str, ...]] = {
    "notes": ("note_id",),
}
```

(Tasks 4–9 append their types' grain keys here.)

- [ ] **Step 3b: Rewrite the loader in `build.py`**

Add `from collections import defaultdict` to the imports and `GRAIN_KEYS` to the
`from xhs_ceramics_analytics.importing.mapping import (...)` block. Replace
`build_database` (25-44) and the three per-file loaders (`_load_csv_table` 54-70,
`_load_dataframe_table` 73-91, `_load_csv_orders_table` 105-126) and the now-unused
helpers `_duckdb_csv_columns` (154-156) and `_projected_columns` (159-177) with:

```python
def build_database(db_path: Path, files: list[Path]) -> None:
    con = connect(db_path)
    try:
        _drop_refresh_objects(con)
        grouped = _group_files_by_type(con, files)
        for table_type, tagged in grouped.items():
            merged = _combine_frames([frame for _, frame in tagged], table_type)
            _create_table_from_frame(con, db_path, table_type, merged)
        create_daily_sku_sales(con)
        if "notes" in _existing_tables(con):
            create_note_metrics_view(con)
        if "ad_performance_daily" in _existing_tables(con):
            create_ad_metrics_view(con)
    finally:
        con.close()


def _group_files_by_type(con, files: list[Path]) -> dict[str, list]:
    # Each value is a list of ``(file_name, canonical_frame)`` pairs. Carrying the
    # source file name here is what lets Task 3 record provenance (build_manifest)
    # and cross-file conflicts (data_quality) — the frame alone loses that.
    grouped: dict[str, list] = defaultdict(list)
    for file in files:
        profile = profile_file(file)
        table_type = guess_table_type(profile)
        grouped[table_type].append(
            (file.name, _canonical_frame(con, file, profile, table_type))
        )
    return grouped


def _canonical_frame(con, file: Path, profile: FileProfile, table_type: str):
    if file.suffix.lower() in EXCEL_SUFFIXES:
        frame = load_table(file, sheet=profile.sheet_name)
    else:
        frame = con.execute("SELECT * FROM read_csv_auto(?)", [str(file)]).fetchdf()
        profile = FileProfile(
            path=file,
            table_name=profile.table_name,
            columns=list(frame.columns),
            row_count=len(frame),
            sample_rows=profile.sample_rows,
        )
    projected = _projected_frame(frame, profile, table_type)
    return _normalized_frame(projected, table_type)


def _combine_frames(frames: list, table_type: str):
    combined = pd.concat(frames, ignore_index=True, sort=False)
    keys = GRAIN_KEYS.get(table_type)
    if not keys:
        return combined
    key_cols = [key for key in keys if key in combined.columns]
    if not key_cols:
        return combined
    merged = combined.groupby(key_cols, dropna=False, as_index=False, sort=False).first()
    ordered = [column for column in combined.columns if column in merged.columns]
    return merged[ordered]


def _create_table_from_frame(con, db_path: Path, table_type: str, frame) -> None:
    staging_path = _write_staging_csv(db_path, table_type, frame)
    con.execute(
        f"""
        CREATE TABLE {_quote_identifier(table_type)} AS
        SELECT *
        FROM read_csv_auto(?)
        """,
        [str(staging_path)],
    )
```

Replace `_projected_frame` (94-102) with a version that also de-duplicates unmapped
column collisions (the real export has ~58 columns):

```python
def _projected_frame(frame, profile: FileProfile, table_type: str):
    field_mapping = guess_field_mapping(profile, table_type)
    rename_mapping = {source: target for target, source in field_mapping.items()}
    projected = frame.rename(columns=rename_mapping)
    reserved = set(rename_mapping.values())
    used: set[str] = set()
    new_columns: list[str] = []
    for column in projected.columns:
        if column in reserved:
            new_columns.append(column)
        else:
            safe = _unique_name(_safe_column_name(column), used | reserved)
            used.add(safe)
            new_columns.append(safe)
    projected.columns = new_columns
    return projected
```

Keep `_normalized_frame`, `_write_staging_csv`, `_existing_tables`,
`_quote_identifier`, `_safe_column_name`, `_unique_name`, `_drop_refresh_objects`,
`create_daily_sku_sales` unchanged.

- [ ] **Step 4: Run tests to verify they pass, and guard against regressions**

Run: `pytest tests/test_duckdb_build.py tests/test_final_review_regressions.py -v`
Expected: new tests PASS **and every pre-existing build test still PASS**. `test_final_review_regressions.py` is included because it drives the full `build_database` path (incl. the partial `[note_id, publish_time]` note file); running it here catches loader regressions at this task, not at the final suite. The orders path is behavior-identical (CSV orders → `read_csv_auto().fetchdf()` → `_projected_frame` → `_normalized_frame`, exactly as before; Excel orders → `load_table` → same). Watch the one behavior change: non-orders CSV now round-trips through pandas + a staging CSV instead of a direct DuckDB projection — types re-infer from the staging CSV identically for null-free fixtures. If any pre-existing assertion breaks on a `100` vs `100.0`, that is the round-trip; reconcile the fixture/assert, do not revert the merge.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py xhs_ceramics_analytics/db/build.py tests/test_duckdb_build.py
git commit -m "feat(build): merge files on grain key instead of per-file overwrite"
```

---

### Task 3: Graceful degradation + provenance/conflict tables (F, A.2)

**Files:**
- Modify: `xhs_ceramics_analytics/db/build.py` (`_group_files_by_type`, `build_database`, `_drop_refresh_objects`; add `_needs_data_record`, `_create_needs_data_table`, `_detect_conflicts`, `_values_conflict`, `_coerce_number`, `_format_grain_key`, `_build_manifest_records`, `_create_data_quality_table`, `_create_build_manifest_table`, `_TABULAR_SUFFIXES`, `_DOMAIN_HINTS`, `_AUX_TABLES`, `MERGE_CONFLICT_TOLERANCE`)
- Test: `tests/test_duckdb_build.py` (add tests)

**Interfaces:**
- Consumes: `AmbiguousTableTypeError` (Task 1, a `ValueError` subclass); the `(file_name, frame)` pairs from `_group_files_by_type` (Task 2).
- Produces:
  - a `needs_data` table with columns `file, domain, reason, action`; `build_database` succeeds on any subset incl. `[]`.
  - a `build_manifest` table (`table_name, file, row_count`) — provenance: which files fed each table (spec §A.2).
  - a `data_quality` table (`table_name, grain_key, column_name, file_a, file_b, value_a, value_b`) — one row per cross-file coalesce conflict where two files disagree on a shared column of the same grain key beyond `MERGE_CONFLICT_TOLERANCE` (spec §A.2: "coalesce keeps the first-loaded and emits a data-quality caveat naming both files; identical/within-tolerance values merge silently"). Column names avoid the SQL reserved words `table`/`column`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_duckdb_build.py  (add)
def test_unclassified_file_becomes_needs_data_and_build_survives(tmp_path):
    (tmp_path / "notes.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,100,10,5\n", encoding="utf-8"
    )
    (tmp_path / "6.退款原因.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "mystery.csv").write_text("列甲,列乙\n1,2\n", encoding="utf-8")
    db = tmp_path / "d.duckdb"
    build_database(db, list(tmp_path.glob("*")))
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM notes").fetchone()[0] == 1  # good file survives
    needs = con.execute("SELECT file, domain FROM needs_data ORDER BY file").fetchdf()
    con.close()
    assert set(needs["file"]) == {"6.退款原因.png", "mystery.csv"}
    assert "退款原因" in set(needs["domain"])


def test_build_succeeds_on_empty_file_list(tmp_path):
    db = tmp_path / "d.duckdb"
    build_database(db, [])  # must not raise
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM needs_data").fetchone()[0] == 0
    con.close()


def test_build_manifest_records_contributing_files(tmp_path):
    # provenance (spec §A.2): the build logs which files fed each table.
    (tmp_path / "notes_a.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,100,10,5\n", encoding="utf-8"
    )
    (tmp_path / "notes_b.csv").write_text(
        f"{_NOTE_HEADER}\nn2,2026-04-02,标题2,200,20,8\n", encoding="utf-8"
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "notes_a.csv", tmp_path / "notes_b.csv"])
    con = duckdb.connect(str(db))
    manifest = con.execute(
        "SELECT file FROM build_manifest WHERE table_name = 'notes' ORDER BY file"
    ).fetchdf()
    con.close()
    assert list(manifest["file"]) == ["notes_a.csv", "notes_b.csv"]


def test_conflicting_grain_key_values_recorded_in_data_quality(tmp_path):
    # spec §A.2: two files describe note n1 but disagree on 阅读次数 (reads) beyond
    # tolerance. Coalesce keeps the first-loaded value; the conflict is logged
    # naming BOTH files. Identical/within-tolerance values would merge silently.
    (tmp_path / "notes_a.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,100,10,5\n", encoding="utf-8"
    )
    (tmp_path / "notes_b.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,500,10,5\n", encoding="utf-8"
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "notes_a.csv", tmp_path / "notes_b.csv"])
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM notes").fetchone()[0] == 1  # coalesced
    dq = con.execute(
        "SELECT table_name, grain_key, column_name, file_a, file_b FROM data_quality"
    ).fetchdf()
    con.close()
    assert len(dq) == 1  # only 阅读次数 differs; other shared columns match
    row = dq.iloc[0]
    assert row["table_name"] == "notes"
    assert "n1" in row["grain_key"]
    assert row["column_name"] == "reads"  # 阅读次数 canonicalizes to reads
    assert {row["file_a"], row["file_b"]} == {"notes_a.csv", "notes_b.csv"}


def test_within_tolerance_values_merge_silently(tmp_path):
    # 100 vs 103 reads = 3% < MERGE_CONFLICT_TOLERANCE (5%) → no data_quality row.
    (tmp_path / "notes_a.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,100,10,5\n", encoding="utf-8"
    )
    (tmp_path / "notes_b.csv").write_text(
        f"{_NOTE_HEADER}\nn1,2026-04-01,标题1,103,10,5\n", encoding="utf-8"
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "notes_a.csv", tmp_path / "notes_b.csv"])
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM data_quality").fetchone()[0] == 0
    con.close()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_duckdb_build.py -k "needs_data or empty_file_list or build_manifest or data_quality or within_tolerance" -v`
Expected: FAIL — build raises on the `.png` / unclassified `mystery.csv`, or `needs_data`/`build_manifest`/`data_quality` tables missing.

- [ ] **Step 3: Write the implementation**

In `build.py`, add module constants near `_DERIVED_TABLES`:

```python
_AUX_TABLES = ("needs_data", "build_manifest", "data_quality")
_TABULAR_SUFFIXES = {".csv", *EXCEL_SUFFIXES}
_DOMAIN_HINTS = (("退款原因", "退款原因"), ("人群", "人群画像"))
# Two files that both report a metric for the same grain key may round differently.
# A relative gap at or below this is treated as agreement (silent merge); above it
# is a data-quality conflict naming both files. Distinct from Task 12's refund
# reconcile tolerance, which cross-checks computed vs platform net_gmv.
MERGE_CONFLICT_TOLERANCE = 0.05
```

Update `_drop_refresh_objects` to also drop aux tables:

```python
def _drop_refresh_objects(con) -> None:
    for view in _DERIVED_VIEWS:
        con.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view)}")
    for table in [*_DERIVED_TABLES, *_AUX_TABLES, *TABLE_SIGNATURES]:
        con.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table)}")
```

Replace `_group_files_by_type` (from Task 2) so it catches errors, and update
`build_database` to create the `needs_data` table:

```python
def build_database(db_path: Path, files: list[Path]) -> None:
    con = connect(db_path)
    try:
        _drop_refresh_objects(con)
        grouped, needs_data = _group_files_by_type(con, files)
        conflicts: list[dict] = []
        manifest: list[dict] = []
        for table_type, tagged in grouped.items():
            conflicts.extend(_detect_conflicts(tagged, table_type))
            manifest.extend(_build_manifest_records(table_type, tagged))
            merged = _combine_frames([frame for _, frame in tagged], table_type)
            _create_table_from_frame(con, db_path, table_type, merged)
        _create_needs_data_table(con, db_path, needs_data)
        _create_build_manifest_table(con, db_path, manifest)
        _create_data_quality_table(con, db_path, conflicts)
        create_daily_sku_sales(con)
        if "notes" in _existing_tables(con):
            create_note_metrics_view(con)
        if "ad_performance_daily" in _existing_tables(con):
            create_ad_metrics_view(con)
    finally:
        con.close()


def _group_files_by_type(con, files: list[Path]) -> tuple[dict[str, list], list[dict]]:
    grouped: dict[str, list] = defaultdict(list)
    needs_data: list[dict] = []
    for file in files:
        if file.suffix.lower() not in _TABULAR_SUFFIXES:
            needs_data.append(_needs_data_record(file, "非表格文件（如PNG截图）", "OCR 或手工录入"))
            continue
        try:
            profile = profile_file(file)
            table_type = guess_table_type(profile)
        except ValueError as exc:  # incl. AmbiguousTableTypeError
            needs_data.append(_needs_data_record(file, str(exc), "确认导出列或手工映射"))
            continue
        grouped[table_type].append(
            (file.name, _canonical_frame(con, file, profile, table_type))
        )
    return grouped, needs_data


def _needs_data_record(file: Path, reason: str, action: str) -> dict:
    domain = "未识别文件"
    for hint, name in _DOMAIN_HINTS:
        if hint in file.name:
            domain = name
            break
    return {"file": file.name, "domain": domain, "reason": reason, "action": action}


def _create_needs_data_table(con, db_path: Path, needs_data: list[dict]) -> None:
    frame = pd.DataFrame(needs_data, columns=["file", "domain", "reason", "action"])
    _create_table_from_frame(con, db_path, "needs_data", frame)


def _build_manifest_records(table_type: str, tagged: list) -> list[dict]:
    """One provenance row per contributing file (spec §A.2)."""
    return [
        {"table_name": table_type, "file": name, "row_count": int(len(frame))}
        for name, frame in tagged
    ]


def _create_build_manifest_table(con, db_path: Path, manifest: list[dict]) -> None:
    frame = pd.DataFrame(manifest, columns=["table_name", "file", "row_count"])
    _create_table_from_frame(con, db_path, "build_manifest", frame)


def _coerce_number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values_conflict(a: object, b: object) -> bool:
    """True when two files disagree on a shared column beyond tolerance.

    Nulls never conflict — coalesce fills them. Numeric values compare by
    relative gap against ``MERGE_CONFLICT_TOLERANCE``; non-numeric by exact string.
    """
    if pd.isna(a) or pd.isna(b):
        return False
    a_num, b_num = _coerce_number(a), _coerce_number(b)
    if a_num is not None and b_num is not None:
        scale = max(abs(a_num), abs(b_num))
        if scale == 0:
            return False
        return abs(a_num - b_num) / scale > MERGE_CONFLICT_TOLERANCE
    return str(a) != str(b)


def _format_grain_key(key_cols: list[str], key: tuple) -> str:
    return ", ".join(f"{col}={value}" for col, value in zip(key_cols, key))


def _detect_conflicts(tagged: list, table_type: str) -> list[dict]:
    """Cross-file coalesce conflicts for a grain-keyed type (spec §A.2).

    For each pair of files that describe the same grain key, any shared column
    whose values disagree beyond tolerance becomes one data-quality row naming
    both files. Non-grain-keyed types (plain-union) and single-file types skip.
    """
    keys = GRAIN_KEYS.get(table_type)
    if not keys or len(tagged) < 2:
        return []
    key_cols = [key for key in keys if all(key in frame.columns for _, frame in tagged)]
    if not key_cols:
        return []
    indexed: list[tuple[str, dict]] = []
    for name, frame in tagged:
        rows = {tuple(row[col] for col in key_cols): row for _, row in frame.iterrows()}
        indexed.append((name, rows))
    conflicts: list[dict] = []
    for i in range(len(indexed)):
        name_a, rows_a = indexed[i]
        for j in range(i + 1, len(indexed)):
            name_b, rows_b = indexed[j]
            for key in set(rows_a) & set(rows_b):
                row_a, row_b = rows_a[key], rows_b[key]
                shared = (set(row_a.index) & set(row_b.index)) - set(key_cols)
                for column in sorted(shared):
                    if _values_conflict(row_a[column], row_b[column]):
                        conflicts.append(
                            {
                                "table_name": table_type,
                                "grain_key": _format_grain_key(key_cols, key),
                                "column_name": column,
                                "file_a": name_a,
                                "file_b": name_b,
                                "value_a": str(row_a[column]),
                                "value_b": str(row_b[column]),
                            }
                        )
    return conflicts


def _create_data_quality_table(con, db_path: Path, conflicts: list[dict]) -> None:
    frame = pd.DataFrame(
        conflicts,
        columns=[
            "table_name", "grain_key", "column_name",
            "file_a", "file_b", "value_a", "value_b",
        ],
    )
    _create_table_from_frame(con, db_path, "data_quality", frame)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_duckdb_build.py tests/test_final_review_regressions.py -v`
Expected: all PASS. A header-only staging CSV yields a 0-row aux table with the declared columns; the conflict scan only runs for grain-keyed types with ≥2 files, so single-file and union types add no `data_quality` rows. `test_final_review_regressions.py` re-confirms the full-build path (incl. the partial note file) still survives the added `except ValueError → needs_data` branch.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/db/build.py tests/test_duckdb_build.py
git commit -m "feat(build): needs_data degradation + build_manifest provenance + data_quality conflicts"
```

---

### Task 4: `business_overview_daily` type (B.1)

**Files:**
- Modify: `xhs_ceramics_analytics/importing/mapping.py` (`TABLE_SIGNATURES`, `FIELD_ALIASES`, `GRAIN_KEYS`)
- Create: `references/data_contract/business_overview_daily.md`
- Test: `tests/test_mapping.py`, `tests/test_duckdb_build.py`

**Interfaces:**
- Produces: table type `business_overview_daily`, grain `("date",)`; canonical columns incl. `net_gmv_pay` (退款后支付金额（支付时间）).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mapping.py  (add)
from xhs_ceramics_analytics.importing.mapping import guess_field_mapping


def test_classifies_business_overview_daily():
    profile = _profile(["时间", "支付金额", "支付订单数", "支付买家数", "客单价",
                        "退款后支付金额（支付时间）", "退款率（支付时间）"])
    assert guess_table_type(profile) == "business_overview_daily"
    mapping = guess_field_mapping(profile, "business_overview_daily")
    assert mapping["date"] == "时间"
    assert mapping["net_gmv_pay"] == "退款后支付金额（支付时间）"
    assert mapping["refund_rate_pay"] == "退款率（支付时间）"
```

```python
# tests/test_duckdb_build.py  (add)
def test_overview_column_views_merge_one_row_per_date(tmp_path):
    header = "时间,支付金额,支付订单数,支付买家数,客单价"
    (tmp_path / "core.csv").write_text(
        f"{header},退款后支付金额（支付时间）\n"
        "20260401,1000,10,8,125,900\n20260402,2000,20,15,133,1800\n",
        encoding="utf-8",
    )
    (tmp_path / "deal.csv").write_text(
        f"{header}\n20260401,1000,10,8,125\n20260402,2000,20,15,133\n", encoding="utf-8"
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "core.csv", tmp_path / "deal.csv"])
    con = duckdb.connect(str(db))
    frame = con.execute(
        "SELECT * FROM business_overview_daily ORDER BY date"
    ).fetchdf()
    con.close()
    assert len(frame) == 2  # one row per date, not 4 (no GMV double-count)
    assert frame.iloc[0]["net_gmv_pay"] == 900  # coalesced from core.csv
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mapping.py -k business_overview -v && pytest tests/test_duckdb_build.py -k overview_column_views -v`
Expected: FAIL — type not in `TABLE_SIGNATURES` (`KeyError`/wrong type).

- [ ] **Step 3: Add the type to `mapping.py`**

Add to `TABLE_SIGNATURES`:

```python
    "business_overview_daily": {"date", "gmv", "paid_orders", "paid_buyers", "aov"},
```

Add to `FIELD_ALIASES`:

```python
    "business_overview_daily": {
        "date": {"时间", "日期"},
        "gmv": {"支付金额"},
        "note_gmv": {"笔记支付金额"},
        "card_gmv": {"商卡支付金额"},
        "paid_orders": {"支付订单数"},
        "note_paid_orders": {"笔记支付订单数"},
        "card_paid_orders": {"商卡支付订单数"},
        "paid_buyers": {"支付买家数"},
        "product_visitors": {"商品访客数", "商品访问人数"},
        "aov": {"客单价"},
        "paid_units": {"支付件数"},
        "pay_conversion": {"支付转化率"},
        "pay_conversion_pv": {"支付转化率（PV）"},
        "pay_conversion_uv": {"支付转化率（UV）"},
        "add_to_cart_users": {"加购人数"},
        "add_to_cart_units": {"加购件数"},
        "refund_amount_pay": {"退款金额（支付时间）"},
        "refund_rate_pay": {"退款率（支付时间）"},
        "refund_orders_pay": {"退款订单数（支付时间）"},
        "pre_ship_refund_rate_pay": {"发货前退款率（支付时间）"},
        "post_ship_refund_rate_pay": {"发货后退款率（支付时间）"},
        "net_gmv_pay": {"退款后支付金额（支付时间）"},
        "refund_amount_refundtime": {"退款金额（退款时间）"},
        "total_visitors": {"总访客数"},
        "total_pv": {"总浏览量"},
        "product_click_rate_pv": {"商品点击率（PV）"},
        "new_add_to_cart_users": {"新增加购人数"},
        "refund_order_share_refundtime": {"退款订单占比（退款时间）"},
    },
```

Add to `GRAIN_KEYS`: `"business_overview_daily": ("date",),`

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mapping.py -v && pytest tests/test_duckdb_build.py -v`
Expected: all PASS (incl. no regression in existing classifications).

- [ ] **Step 5: Verify aliases against the real file (read-only)**

Write `/tmp/verify_overview.py` that profiles the two real overview files
(`1.核心数据汇总`, `成交/经营概览-all`) from the read-only export dir, runs
`guess_table_type` + `guess_field_mapping`, and prints DROPPED (un-canonicalized)
columns. For any dropped column that should be canonical, add its exact header to
the alias set above. Re-run Step 4. Do **not** modify the export files.

- [ ] **Step 6: Write the data-contract doc**

Create `references/data_contract/business_overview_daily.md`:

```markdown
# business_overview_daily

- **Grain / Primary Key:** `date` (int `YYYYMMDD`) — one row per day.
- **Source files:** `1.核心数据汇总` (21 col) + `成交/经营概览-all` (58 col), merged on `date` (column-view coalesce).
- **Required:** `date, gmv, paid_orders, paid_buyers, aov`.
- **Optional:** channel split (`note_gmv/card_gmv`, `note_paid_orders/card_paid_orders`), `product_visitors, paid_units, pay_conversion(_pv/_uv), add_to_cart_users/units, net_gmv_pay, refund_amount_pay, refund_rate_pay, refund_orders_pay, pre_ship_refund_rate_pay, post_ship_refund_rate_pay, refund_amount_refundtime, total_visitors, total_pv, product_click_rate_pv, new_add_to_cart_users, refund_order_share_refundtime`.
- **Join keys:** `date` → `business_overview_monthly` (rolled up).
- **Chinese aliases:** see `FIELD_ALIASES["business_overview_daily"]` in `importing/mapping.py`.
- **Caliber:** amounts carry both `_pay` (支付时间) and `_refundtime` (退款时间); rates only `_pay`.
```

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py references/data_contract/business_overview_daily.md tests/
git commit -m "feat(mapping): business_overview_daily type + grain + data contract"
```

---

### Task 5: `sku_performance` type (B.2)

**Files:** `mapping.py`; `references/data_contract/sku_performance.md`; `tests/test_mapping.py`

**Interfaces:** table type `sku_performance`, grain `("sku_id",)`; a real `skus` catalog (with `price`) still classifies as `skus`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapping.py  (add)
def test_classifies_sku_performance_and_catalog_still_skus():
    perf = _profile(["规格ID", "规格名称", "商品ID", "一级品类", "加购人数",
                     "支付金额", "客单价", "退款后支付金额（支付时间）", "退款率（支付时间）"])
    assert guess_table_type(perf) == "sku_performance"
    catalog = _profile(["规格ID", "商品ID", "规格名称", "销售价格"])
    assert guess_table_type(catalog) == "skus"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapping.py -k sku_performance -v`
Expected: FAIL — `sku_performance` not defined.

- [ ] **Step 3: Add the type to `mapping.py`**

`TABLE_SIGNATURES`: `"sku_performance": {"sku_id", "net_gmv_pay", "refund_rate_pay", "add_to_cart_users"},`

`FIELD_ALIASES`:

```python
    "sku_performance": {
        "sku_id": {"规格ID", "规格id"},
        "sku_name": {"规格名称"},
        "product_id": {"商品ID", "商品id"},
        "product_name": {"商品名称"},
        "is_channel_product": {"是否渠道商品"},
        "barcode": {"条形码", "商品条码"},
        "category_l1": {"一级品类"},
        "category_l2": {"二级品类"},
        "brand": {"品牌"},
        "add_to_cart_users": {"加购人数", "新增加购人数"},
        "add_to_cart_units": {"加购件数"},
        "wishlist_users": {"想要人数", "收藏人数"},
        "gmv": {"支付金额"},
        "paid_buyers": {"支付买家数"},
        "paid_orders": {"支付订单数"},
        "paid_units": {"支付件数"},
        "aov": {"客单价"},
        "refund_amount_pay": {"退款金额（支付时间）"},
        "refund_rate_pay": {"退款率（支付时间）"},
        "refund_orders_pay": {"退款订单数（支付时间）"},
        "pre_ship_refund_rate_pay": {"发货前退款率（支付时间）"},
        "post_ship_refund_rate_pay": {"发货后退款率（支付时间）"},
        "net_gmv_pay": {"退款后支付金额（支付时间）"},
        "refund_amount_refundtime": {"退款金额（退款时间）"},
        "refund_rate_refundtime": {"退款率（退款时间）"},
    },
```

`GRAIN_KEYS`: `"sku_performance": ("sku_id",),`

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mapping.py -v`
Expected: PASS (catalog still `skus`: 4/4 vs sku_performance 1/4).

- [ ] **Step 5: Verify against real `2.规格明细` (read-only)** — same scratch-script loop as Task 4 Step 5.

- [ ] **Step 6: Write `references/data_contract/sku_performance.md`**

```markdown
# sku_performance

- **Grain / Primary Key:** `sku_id` (规格ID) — whole-period per-SKU aggregate (no date column).
- **Source file:** `2.规格明细` (26 col). §4 商品与SKU source.
- **Required:** `sku_id`; commerce block `net_gmv_pay, refund_rate_pay, add_to_cart_users`.
- **Optional:** `sku_name, product_id, product_name, is_channel_product, barcode, category_l1, category_l2, brand, add_to_cart_units, wishlist_users, gmv, paid_buyers, paid_orders, paid_units, aov, refund_amount_pay, refund_orders_pay, pre_ship_refund_rate_pay, post_ship_refund_rate_pay, refund_amount_refundtime, refund_rate_refundtime`.
- **Join keys:** `sku_id` → `skus`/`products` catalog; `product_id` → `products`.
- **Note:** 退款后GMV (`net_gmv_pay`) is platform-given — never computed.
```

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py references/data_contract/sku_performance.md tests/test_mapping.py
git commit -m "feat(mapping): sku_performance type + grain + data contract"
```

---

### Task 6: Enrich `notes` aliases (B.3)

**Files:** `mapping.py` (extend `FIELD_ALIASES["notes"]` only — signature and grain unchanged); `references/data_contract/notes.md` (update); `tests/test_mapping.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapping.py  (add)
def test_notes_enriched_commerce_aliases():
    profile = _profile(["笔记id", "发布时间", "笔记标题", "阅读次数", "点赞数", "收藏数",
                        "笔记类型", "笔记支付金额", "笔记商品点击次数", "笔记商品点击人数"])
    assert guess_table_type(profile) == "notes"
    mapping = guess_field_mapping(profile, "notes")
    assert mapping["note_type"] == "笔记类型"
    assert mapping["note_gmv"] == "笔记支付金额"
    assert mapping["product_clicks"] == "笔记商品点击次数"
    assert mapping["product_click_users"] == "笔记商品点击人数"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapping.py -k notes_enriched -v`
Expected: FAIL — `KeyError: 'note_type'` (alias not present).

- [ ] **Step 3: Extend `FIELD_ALIASES["notes"]`**

Add these keys to the existing `notes` alias dict (keep all current keys):

```python
        "note_type": {"笔记类型"},
        "related_product_id": {"关联商品ID"},
        "related_product_name": {"关联商品名称"},
        "video_seconds": {"视频时长"},
        "note_gmv": {"笔记支付金额"},
        "note_paid_orders": {"笔记支付订单数"},
        "note_paid_buyers": {"笔记支付人数"},
        "product_clicks": {"笔记商品点击次数"},
        "product_click_rate_pv": {"笔记商品点击率（PV）"},
        "product_click_users": {"笔记商品点击人数"},
        "pay_conversion_pv": {"支付转化率（PV）"},
        "pay_conversion_uv": {"支付转化率（UV）"},
        "note_refund_amount_pay": {"笔记退款金额（支付时间）"},
        "note_refund_rate_pay": {"笔记退款率（支付时间）"},
        "note_refund_orders_pay": {"笔记退款订单数（支付时间）"},
        "add_to_cart_units": {"加购件数"},
        "to_shop_home_count": {"进店次数"},
        "to_shop_home_gmv": {"进店支付金额"},
        "to_live_count": {"进直播间次数"},
        "to_live_gmv": {"直播间支付金额"},
        "follow_clicks": {"关注按钮点击次数"},
        "danmu_count": {"弹幕数"},
        "avg_read_seconds": {"人均阅读时长"},
        "completion_rate_pv": {"完播率（PV）"},
```

(`notes` is already in `GRAIN_KEYS` as `("note_id",)` from Task 2.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mapping.py -v`
Expected: PASS.

- [ ] **Step 5: Verify against the real `4.商品笔记数据` files (read-only)** — scratch-script loop; reconcile any dropped commerce column.

- [ ] **Step 6: Update `references/data_contract/notes.md`** — add the commerce/refund/type/engagement columns to the Optional Columns + Chinese Aliases sections; note the 3 files merge on `note_id`.

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py references/data_contract/notes.md tests/test_mapping.py
git commit -m "feat(mapping): enrich notes with commerce/refund/type aliases"
```

---

### Task 7: `search_overview` + `search_terms` types (B.4, B.5)

**Files:** `mapping.py`; `references/data_contract/search_overview.md`, `search_terms.md`; `tests/test_mapping.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapping.py  (add)
def test_classifies_search_overview_and_terms():
    overview = _profile(["日期", "载体", "支付金额", "支付订单数", "支付买家数",
                         "商卡曝光人数", "商品点击人数", "商品点击率", "支付转化率"])
    assert guess_table_type(overview) == "search_overview"
    terms = _profile(["搜索词", "支付金额", "支付订单数", "支付买家数",
                      "商卡曝光人数", "商品点击人数", "商品点击率", "支付转化率"])
    assert guess_table_type(terms) == "search_terms"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapping.py -k search -v`
Expected: FAIL.

- [ ] **Step 3: Add both types to `mapping.py`**

`TABLE_SIGNATURES`:

```python
    "search_overview": {"date", "carrier", "card_impression_users", "product_click_rate", "pay_conversion"},
    "search_terms": {"search_term", "card_impression_users", "product_click_rate", "pay_conversion"},
```

`FIELD_ALIASES`:

```python
    "search_overview": {
        "date": {"日期", "时间"},
        "carrier": {"载体"},
        "gmv": {"支付金额"},
        "paid_orders": {"支付订单数"},
        "paid_buyers": {"支付买家数"},
        "card_impression_users": {"商卡曝光人数"},
        "product_click_users": {"商品点击人数"},
        "product_click_rate": {"商品点击率"},
        "pay_conversion": {"支付转化率"},
    },
    "search_terms": {
        "search_term": {"搜索词"},
        "gmv": {"支付金额"},
        "paid_orders": {"支付订单数"},
        "paid_buyers": {"支付买家数"},
        "card_impression_users": {"商卡曝光人数"},
        "product_click_users": {"商品点击人数"},
        "product_click_rate": {"商品点击率"},
        "pay_conversion": {"支付转化率"},
    },
```

`GRAIN_KEYS`:

```python
    "search_overview": ("date", "carrier"),
    "search_terms": ("search_term",),
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mapping.py -v`
Expected: PASS (search_overview beats business_overview_daily 1.0 vs 0.8 — margin 0.2 ≥ 0.15).

- [ ] **Step 5: Verify against `7.搜索总览`/`7.搜索词` (read-only).**

- [ ] **Step 6: Write `references/data_contract/search_overview.md` + `search_terms.md`** (grain, required = signature, optional = the rest, aliases pointer, per the Task 4 doc template).

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py references/data_contract/search_*.md tests/test_mapping.py
git commit -m "feat(mapping): search_overview + search_terms types"
```

---

### Task 8: `shop_page_funnel` + `shop_page_source` types (B.6, B.7)

**Files:** `mapping.py`; `references/data_contract/shop_page_funnel.md`, `shop_page_source.md`; `tests/test_mapping.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapping.py  (add)
def test_classifies_shop_page_funnel_and_source():
    funnel = _profile(["时间", "人群类型", "首购周期", "店铺页访问人数",
                       "商品点击人数", "店铺页支付人数", "访问点击转化率", "点击支付率", "访问支付率"])
    assert guess_table_type(funnel) == "shop_page_funnel"
    source = _profile(["时间", "人群类型", "首购周期", "来源页面",
                       "店铺页支付金额", "店铺页访问人数", "进店支付转化率", "人均支付金额"])
    assert guess_table_type(source) == "shop_page_source"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapping.py -k shop_page -v`
Expected: FAIL.

- [ ] **Step 3: Add both types to `mapping.py`**

`TABLE_SIGNATURES`:

```python
    "shop_page_funnel": {"shop_visitors", "shop_payers", "first_purchase_cycle"},
    "shop_page_source": {"source_page", "shop_visitors", "enter_pay_rate"},
```

`FIELD_ALIASES`:

```python
    "shop_page_funnel": {
        "date": {"时间", "日期"},
        "audience_type": {"人群类型"},
        "first_purchase_cycle": {"首购周期"},
        "shop_visitors": {"店铺页访问人数"},
        "product_click_users": {"商品点击人数"},
        "shop_payers": {"店铺页支付人数"},
        "visit_click_rate": {"访问点击转化率"},
        "click_pay_rate": {"点击支付率"},
        "visit_pay_rate": {"访问支付率"},
    },
    "shop_page_source": {
        "date": {"时间", "日期"},
        "audience_type": {"人群类型"},
        "first_purchase_cycle": {"首购周期"},
        "source_page": {"来源页面"},
        "shop_gmv": {"店铺页支付金额"},
        "shop_visitors": {"店铺页访问人数"},
        "enter_pay_rate": {"进店支付转化率"},
        "gmv_per_user": {"人均支付金额"},
    },
```

`GRAIN_KEYS`:

```python
    "shop_page_funnel": ("date", "audience_type", "first_purchase_cycle"),
    "shop_page_source": ("date", "audience_type", "first_purchase_cycle", "source_page"),
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mapping.py -v`
Expected: PASS (funnel 1.0 vs source 0.33 on the funnel file; source 1.0 vs funnel 0.67 on the source file — both margins ≥ 0.15).

- [ ] **Step 5: Verify against `8.店铺页转化漏斗`/`8.进店来源` (read-only).**

- [ ] **Step 6: Write the two data-contract docs.**

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py references/data_contract/shop_page_*.md tests/test_mapping.py
git commit -m "feat(mapping): shop_page_funnel + shop_page_source types"
```

---

### Task 9: `refund_overview` + `traffic_source` types (B.8, B.9)

**Files:** `mapping.py`; `references/data_contract/refund_overview.md`, `traffic_source.md`; `tests/test_mapping.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mapping.py  (add)
def test_classifies_refund_overview_and_traffic_source():
    refund = _profile(["统计时间", "账号类型", "账号名称", "载体", "退款金额（支付时间）",
                       "发货前退款金额（支付时间）", "退货退款金额（支付时间）", "退款人数"])
    assert guess_table_type(refund) == "refund_overview"
    traffic = _profile(["小红书号", "账号名称", "渠道", "笔记类型", "支付金额",
                        "支付订单数", "支付人数", "商品点击次数", "商品点击人数"])
    assert guess_table_type(traffic) == "traffic_source"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapping.py -k "refund_overview or traffic_source" -v`
Expected: FAIL.

- [ ] **Step 3: Add both types to `mapping.py`**

`TABLE_SIGNATURES`:

```python
    "refund_overview": {"carrier", "pre_ship_refund_amount", "return_refund_amount", "refund_users"},
    "traffic_source": {"xhs_id", "channel", "product_clicks", "product_click_users"},
```

`FIELD_ALIASES`:

```python
    "refund_overview": {
        "stat_period": {"统计时间"},
        "account_type": {"账号类型"},
        "account_name": {"账号名称"},
        "carrier": {"载体"},
        "refund_amount_pay": {"退款金额（支付时间）"},
        "post_ship_refund_amount": {"发货后退款金额（支付时间）"},
        "shipped_refundonly_amount": {"发货后仅退款金额（支付时间）"},
        "pre_ship_refund_amount": {"发货前退款金额（支付时间）"},
        "return_refund_amount": {"退货退款金额（支付时间）"},
        "refund_orders_pay": {"退款订单数（支付时间）"},
        "post_ship_refund_orders": {"发货后退款订单数（支付时间）"},
        "shipped_refundonly_orders": {"发货后仅退款订单数（支付时间）"},
        "pre_ship_refund_orders": {"发货前退款订单数（支付时间）"},
        "return_refund_orders": {"退货退款订单数（支付时间）"},
        "refund_rate_pay": {"退款率（支付时间）"},
        "post_ship_refund_rate_pay": {"发货后退款率（支付时间）"},
        "pre_ship_refund_rate_pay": {"发货前退款率（支付时间）"},
        "return_refund_rate_pay": {"退货退款率（支付时间）"},
        "refund_users": {"退款人数"},
    },
    "traffic_source": {
        "xhs_id": {"小红书号"},
        "account_name": {"账号名称"},
        "channel": {"渠道"},
        "note_type": {"笔记类型"},
        "gmv": {"支付金额"},
        "paid_orders": {"支付订单数"},
        "paid_buyers": {"支付人数"},
        "product_clicks": {"商品点击次数"},
        "product_click_users": {"商品点击人数"},
        "pay_conversion_pv": {"支付转化率（PV）"},
        "pay_conversion_uv": {"支付转化率（UV）"},
    },
```

`GRAIN_KEYS`:

```python
    "refund_overview": ("stat_period", "account_name", "carrier"),
    "traffic_source": ("xhs_id", "channel", "note_type"),
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_mapping.py -v`
Expected: PASS. This is the full 9-header regression — every real header now classifies to its own type, and all 8 legacy fixtures still classify unchanged.

- [ ] **Step 5: Verify against `6.退款分析概览`/`3.流量来源` (read-only).**

- [ ] **Step 6: Write the two data-contract docs.**

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/importing/mapping.py references/data_contract/refund_overview.md references/data_contract/traffic_source.md tests/test_mapping.py
git commit -m "feat(mapping): refund_overview + traffic_source types (all 9 real headers land)"
```

---

### Task 10: `business_overview_monthly` mart (E.1)

**Files:**
- Modify: `xhs_ceramics_analytics/db/marts.py` (add `create_business_overview_monthly`)
- Modify: `xhs_ceramics_analytics/db/build.py` (import + call it; add to `_DERIVED_TABLES`)
- Test: `tests/test_duckdb_build.py`

**Interfaces:**
- Consumes: `analytics.periods.period_month_expr` (Plan 2 Task 1), `db.sql_helpers.numeric_expr`.
- Produces: table `business_overview_monthly` with `period_month`, summed extensives, and `aov`/`refund_rate_pay` recomputed only where both operands survive.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_duckdb_build.py  (add)
def test_business_overview_monthly_rolls_up_daily(tmp_path):
    (tmp_path / "core.csv").write_text(
        "时间,支付金额,支付订单数,支付买家数,客单价\n"
        "20260401,1000,10,8,100\n20260402,2000,20,15,100\n20260501,3000,30,20,100\n",
        encoding="utf-8",
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "core.csv"])
    con = duckdb.connect(str(db))
    rows = con.execute(
        "SELECT period_month, gmv, paid_orders, aov FROM business_overview_monthly ORDER BY period_month"
    ).fetchall()
    con.close()
    assert rows[0][0] == "2026-04" and rows[0][1] == 3000 and rows[0][2] == 30
    assert rows[0][3] == 100  # aov = 3000/30
    assert rows[1][0] == "2026-05" and rows[1][1] == 3000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_duckdb_build.py -k monthly -v`
Expected: FAIL — `business_overview_monthly` does not exist.

- [ ] **Step 3: Write the mart**

In `marts.py`, add the import and function:

```python
from xhs_ceramics_analytics.analytics.periods import period_month_expr


def create_business_overview_monthly(con) -> None:
    columns = {
        row[1] for row in con.sql("PRAGMA table_info('business_overview_daily')").fetchall()
    }
    if "date" not in columns:
        return
    period = period_month_expr("date")
    gmv = numeric_expr(columns, "gmv")
    paid_orders = numeric_expr(columns, "paid_orders")
    paid_buyers = numeric_expr(columns, "paid_buyers")
    paid_units = numeric_expr(columns, "paid_units")
    refund_amount_pay = numeric_expr(columns, "refund_amount_pay")
    net_gmv_pay = numeric_expr(columns, "net_gmv_pay")
    con.execute(
        f"""
        CREATE TABLE business_overview_monthly AS
        SELECT
          {period} AS period_month,
          SUM({gmv}) AS gmv,
          SUM({paid_orders}) AS paid_orders,
          SUM({paid_buyers}) AS paid_buyers,
          SUM({paid_units}) AS paid_units,
          SUM({refund_amount_pay}) AS refund_amount_pay,
          SUM({net_gmv_pay}) AS net_gmv_pay,
          SUM({gmv}) / NULLIF(SUM({paid_orders}), 0) AS aov,
          SUM({refund_amount_pay}) / NULLIF(SUM({gmv}), 0) AS refund_rate_pay
        FROM business_overview_daily
        GROUP BY 1
        ORDER BY 1
        """
    )
```

In `build.py`: add `create_business_overview_monthly` to the marts import; add
`"business_overview_monthly"` to `_DERIVED_TABLES`; and after the
`create_daily_sku_sales(con)` call add:

```python
        if "business_overview_daily" in _existing_tables(con):
            create_business_overview_monthly(con)
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_duckdb_build.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/db/marts.py xhs_ceramics_analytics/db/build.py tests/test_duckdb_build.py
git commit -m "feat(marts): business_overview_monthly rollup"
```

---

### Task 11: Enrich `note_metrics` view (E.2)

**Files:**
- Modify: `xhs_ceramics_analytics/db/marts.py` (`create_note_metrics_view` 30-59)
- Test: `tests/test_duckdb_build.py`

**Interfaces:** `note_metrics` gains null-safe `click_to_order = note_paid_orders / product_clicks` and `gmv_per_click = note_gmv / product_clicks`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_duckdb_build.py  (add)
def test_note_metrics_derives_click_to_order(tmp_path):
    (tmp_path / "notes.csv").write_text(
        "笔记id,发布时间,笔记标题,阅读次数,点赞数,收藏数,笔记支付订单数,笔记商品点击次数,笔记支付金额\n"
        "n1,2026-04-01,标题1,1000,10,5,4,20,800\n",
        encoding="utf-8",
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [tmp_path / "notes.csv"])
    con = duckdb.connect(str(db))
    row = con.execute(
        "SELECT click_to_order, gmv_per_click FROM note_metrics WHERE note_id='n1'"
    ).fetchone()
    con.close()
    assert row[0] == 0.2   # 4 / 20
    assert row[1] == 40.0  # 800 / 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_duckdb_build.py -k click_to_order -v`
Expected: FAIL — `Referenced column "click_to_order" not found`.

- [ ] **Step 3: Extend the view**

In `create_note_metrics_view`, after the existing `shares` local, add:

```python
    product_clicks = numeric_expr(note_columns, "product_clicks")
    note_paid_orders = numeric_expr(note_columns, "note_paid_orders")
    note_gmv = numeric_expr(note_columns, "note_gmv")
```

Then extend the `SELECT`: the view's last computed column is `engagement_rate`
immediately followed by `FROM notes` — add a comma and the two new columns.
Replace exactly:

```sql
          END AS engagement_rate
        FROM notes
```

with:

```sql
          END AS engagement_rate,
          CASE WHEN {product_clicks} > 0 THEN {note_paid_orders} * 1.0 / {product_clicks} END AS click_to_order,
          CASE WHEN {product_clicks} > 0 THEN {note_gmv} * 1.0 / {product_clicks} END AS gmv_per_click
        FROM notes
```

(`numeric_expr` is already imported in `marts.py`; absent columns → `NULL`, so
pre-existing note fixtures without these columns keep passing.)

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_duckdb_build.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/db/marts.py tests/test_duckdb_build.py
git commit -m "feat(marts): note_metrics click_to_order + gmv_per_click"
```

---

### Task 12: Refund cross-check (E.4, optional but specced)

**Files:**
- Create: `xhs_ceramics_analytics/analytics/reconcile.py`
- Test: `tests/test_analytics_reconcile.py`

**Interfaces:**
- Consumes: `analytics.refund_adjust.net_gmv` (Plan 2 Task 2), `REFUND_RECONCILE_TOLERANCE`.
- Produces: `reconcile_net_gmv(gmv, refund_amount, net_gmv_pay, tolerance=REFUND_RECONCILE_TOLERANCE) -> str | None` — returns a data-quality caveat string when `|(gmv - refund) - net_gmv_pay| / gmv` exceeds tolerance, else `None`. Pure; DB wiring is deferred to a consuming §-task.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_reconcile.py
from xhs_ceramics_analytics.analytics.reconcile import (
    REFUND_RECONCILE_TOLERANCE,
    reconcile_net_gmv,
)


def test_reconcile_within_tolerance_returns_none():
    assert reconcile_net_gmv(1000.0, 100.0, 900.0) is None


def test_reconcile_beyond_tolerance_returns_caveat():
    caveat = reconcile_net_gmv(1000.0, 100.0, 500.0)
    assert caveat is not None and "退款后GMV" in caveat


def test_reconcile_missing_inputs_returns_none():
    assert reconcile_net_gmv(None, 100.0, 900.0) is None
    assert reconcile_net_gmv(0.0, 0.0, 0.0) is None


def test_tolerance_constant():
    assert REFUND_RECONCILE_TOLERANCE == 0.05
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_reconcile.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# xhs_ceramics_analytics/analytics/reconcile.py
"""Cross-check the platform-given net GMV against gmv - refund_amount."""
from xhs_ceramics_analytics.analytics.refund_adjust import net_gmv

REFUND_RECONCILE_TOLERANCE = 0.05


def reconcile_net_gmv(
    gmv: float | None,
    refund_amount: float | None,
    net_gmv_pay: float | None,
    tolerance: float = REFUND_RECONCILE_TOLERANCE,
) -> str | None:
    computed = net_gmv(gmv, refund_amount)
    if computed is None or net_gmv_pay is None or not gmv:
        return None
    if abs(computed - net_gmv_pay) / gmv <= tolerance:
        return None
    return (
        f"退款后GMV 对不上：平台值 {net_gmv_pay:.0f} 与 支付金额-退款金额 "
        f"{computed:.0f} 相差超过 {tolerance:.0%}，请核对退款口径。"
    )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_analytics_reconcile.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/reconcile.py tests/test_analytics_reconcile.py
git commit -m "feat(analytics): platform net-GMV reconciliation caveat"
```

---

### Task 13: Real-header fixtures + end-to-end build + any-subset regression (F / testing)

**Files:**
- Create: `tests/fixtures/business_overview_daily.csv`, `sku_performance.csv`, `notes_commerce.csv`, `search_overview.csv`, `search_terms.csv`, `shop_page_funnel.csv`, `shop_page_source.csv`, `refund_overview.csv`, `traffic_source.csv` (anonymized, 2-3 rows each, **headers copied exactly from the real export**, incl. `（支付时间）`)
- Test: `tests/test_real_export_build.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_real_export_build.py
import duckdb
import pytest

from xhs_ceramics_analytics.db.build import build_database

_ALL = [
    ("business_overview_daily.csv", "business_overview_daily"),
    ("sku_performance.csv", "sku_performance"),
    ("notes_commerce.csv", "notes"),
    ("search_overview.csv", "search_overview"),
    ("search_terms.csv", "search_terms"),
    ("shop_page_funnel.csv", "shop_page_funnel"),
    ("shop_page_source.csv", "shop_page_source"),
    ("refund_overview.csv", "refund_overview"),
    ("traffic_source.csv", "traffic_source"),
]


def test_full_export_yields_nine_typed_tables(fixture_dir, tmp_path):
    files = [fixture_dir / name for name, _ in _ALL]
    db = tmp_path / "d.duckdb"
    build_database(db, files)
    con = duckdb.connect(str(db))
    tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
    con.close()
    for _, table_type in _ALL:
        assert table_type in tables


@pytest.mark.parametrize("count", [0, 1, 3, 9])
def test_run_all_succeeds_on_any_subset(fixture_dir, tmp_path, count):
    files = [fixture_dir / name for name, _ in _ALL[:count]]
    db = tmp_path / f"d{count}.duckdb"
    build_database(db, files)  # must never raise on any subset
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM needs_data").fetchone()[0] == 0
    con.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_real_export_build.py -v`
Expected: FAIL — fixture files missing.

- [ ] **Step 3: Create the fixtures**

Copy the exact real headers into each CSV with 2-3 anonymized rows. Get the exact
header row per file from a read-only scratch script over the export dir
(`import openpyxl; print(next(ws.iter_rows(values_only=True)))`), then hand-write
anonymized data rows. Keep every full-width paren. Example
(`business_overview_daily.csv`):

```csv
时间,支付金额,支付订单数,支付买家数,客单价,退款后支付金额（支付时间）,退款率（支付时间）
20260401,1000,10,8,125,900,0.1
20260402,2000,20,15,133,1800,0.1
```

Create the other eight the same way (signature columns mandatory; add the
distinctive columns each type needs to out-score its neighbours).

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_real_export_build.py -v && pytest -q`
Expected: all PASS — 9 typed tables; build never raises on subsets of size 0/1/3/9.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/*.csv tests/test_real_export_build.py
git commit -m "test(build): real-header fixtures + full-export + any-subset regression"
```

---

### Task 14: Docs, manual-entry schemas, runtime mirror sync (F, rollout 7-8)

**Files:**
- Modify: `references/data_contract/_index.md` (add the 9 rows)
- Modify: `references/metric_definitions.md` (period assumption), `references/xhs_glossary.md` (caliber note)
- Create: `references/data_contract/refund_reasons.md`, `references/data_contract/audience_profile.md` (manual-entry schemas for the two PNG domains)
- Then run the runtime mirror sync + full suite

- [ ] **Step 1: Update `references/data_contract/_index.md`**

Add one row per new table (`business_overview_daily`, `sku_performance`,
`search_overview`, `search_terms`, `shop_page_funnel`, `shop_page_source`,
`refund_overview`, `traffic_source`; note `notes` enriched) with grain + source-file
+ link to its contract doc, matching the existing table format.

- [ ] **Step 2: Add the period + caliber notes**

- `references/metric_definitions.md`: append a note — "Period bucketing: `时间/日期`
  are int `YYYYMMDD`, `笔记创建时间` is a local (Asia/Shanghai) timestamp; both bucket
  to `YYYY-MM` with no timezone conversion (see `analytics/periods.py`)."
- `references/xhs_glossary.md`: append a caliber note — "Refund caliber: amounts
  carry `_pay` (支付时间) and `_refundtime` (退款时间); **rates exist only in `_pay`**.
  退款后GMV (`net_gmv_pay`) is platform-given, not computed."

- [ ] **Step 3: Create the two manual-entry schemas**

`references/data_contract/refund_reasons.md` and `audience_profile.md` — each a tiny
hand-fillable CSV schema so the operator can supply the PNG-only domains. Example
for `refund_reasons.md`:

```markdown
# refund_reasons (manual entry — 6.退款原因 is PNG-only)

Hand-fill this CSV if you want §7 refund-reason analysis; otherwise it stays needs-data.

| column | 中文 | type |
|---|---|---|
| refund_reason | 退款原因 | str |
| refund_amount | 退款金额 | float |
| refund_orders | 退款订单数 | int |

Sample: `尺寸不符,1200,8`
```

`audience_profile.md` follows the same shape (`audience_segment, share, gmv`).

- [ ] **Step 4: Run the runtime mirror sync + full suite**

Run the project's **sync-runtime** step (regenerates
`skills/data-analyze-for-zcl/assets/xhs-ca/` from the package root — see recent
`chore: sync runtime mirror` commits). Then:

Run: `ruff check . && pytest -q`
Expected: lint clean; full suite green (root + mirror).

- [ ] **Step 5: Commit**

```bash
git add references/ skills/data-analyze-for-zcl/
git commit -m "docs(data-contract): 9 real-export tables, caliber/period notes, manual-entry schemas; sync runtime"
```

---

## Self-Review (run after all tasks)

1. **Spec coverage:** A.1 table-scoped guess + margin → T1. A.2 grain keys + merge → T2; **A.2 coalesce conflict caveat (`data_quality`) + provenance log (`build_manifest`) → T3** (`_group_files_by_type` carries `(file, frame)` pairs from T2; T3 detects cross-file same-key disagreements beyond `MERGE_CONFLICT_TOLERANCE` and records which files fed each table). A.3 naming conventions → applied in T4-T9 alias maps + Global Constraints. B.1-B.9 nine types → T4 (overview), T5 (sku), T6 (notes), T7 (search×2), T8 (shop×2), T9 (refund+traffic). E.1 monthly → T10; E.2 note_metrics → T11; E.4 reconcile → T12. F needs-data → T3; manual-entry schemas + run-all-any-subset → T13/T14. Testing strategy (9 headers, merge, conflict caveat, provenance, needs-data, subset) → T1-T14. Rollout 7-8 (docs, `_index`, glossary, sync) → T14. ✅
2. **Placeholder scan:** the only "verify against the real file" steps (T4-T9 Step 5) are deliberate reconciliation loops with a concrete scratch-script action, not placeholders — the code they refine is already complete and testable.
3. **Type consistency:** `guess_table_type`/`AmbiguousTableTypeError`/`_table_scoped_hits`/`MARGIN`; `GRAIN_KEYS`; `_group_files_by_type`/`_canonical_frame`/`_combine_frames`/`_create_table_from_frame`/`_needs_data_record`/`_create_needs_data_table`; `_detect_conflicts`/`_values_conflict`/`_coerce_number`/`_format_grain_key`/`_build_manifest_records`/`_create_data_quality_table`/`_create_build_manifest_table`/`MERGE_CONFLICT_TOLERANCE`; `create_business_overview_monthly`/`period_month_expr`; `reconcile_net_gmv`/`REFUND_RECONCILE_TOLERANCE` — spelled identically across tasks. `_group_files_by_type` returns `(file, frame)` pairs from T2 onward; T3's rewrite preserves that shape. `net_gmv_pay`, `refund_rate_pay`, `product_clicks`, `note_gmv`, `note_paid_orders` canonical names consistent between mapping aliases (T4-T9) and the marts that read them (T10-T11). `data_quality`/`build_manifest` column names avoid the SQL reserved words `table`/`column`.
4. **Regression guards:** every mapping task ends with full `pytest tests/test_mapping.py`; every build task with full `pytest tests/test_duckdb_build.py`; T14 runs `ruff check . && pytest -q`. Legacy `orders` path proven behavior-identical in T2 Step 4.
5. **Dependencies:** T10 (monthly mart) and T12 (reconcile) import `xhs_ceramics_analytics.analytics.*` — Plan 2 must land first.
