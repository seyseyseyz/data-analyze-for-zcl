# Refund Structure Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the `refund_structure_diagnosis` analysis task — a 5-finding refund diagnosis (layer decomposition, carrier comparison, time trend, note-level reflection, product-level reflection) that is the skeleton module for the parallel report-module sub-project.

**Architecture:** One new analysis module `analysis/refund_diagnosis.py` exposing `run(db_path) -> AnalysisResult`, registered by one line in `analysis/registry.py`. It reads already-built DuckDB tables (`refund_overview`, `business_overview_daily`, `notes`, `content_features`, `sku_performance`, `products`), uses an internal relative baseline, reverse-derives sample sizes from `refund_orders / refund_rate`, and degrades gracefully (any missing table/column skips only its finding, never raises). One new reusable statistics helper `two_proportion` lives in `analytics/confidence.py`.

**Tech Stack:** Python 3.11+, DuckDB, existing `analytics/confidence.py` (`wilson_interval`, `min_n_guard`, `rate_band`) and `analytics/trends.py` (`mom_change`, `direction_label`), `evidence.score_evidence`, pytest.

## Global Constraints

- Interpreter is `.venv/bin/python` (bare `python` is not installed). Every command uses it.
- Line length 100 (ruff); `pythonpath=["."]` is configured, so imports are absolute `xhs_ceramics_analytics.*`.
- Immutability: helpers return new lists/dicts; never mutate inputs in place.
- All findings are observational: `has_controls=False` always → `score_evidence` never returns STRONG/MEDIUM (ceiling is WEAK). Every finding's `caveats` must state non-causality.
- Degradation is a hard requirement: a missing table or column skips only its finding and appends a reason to `AnalysisResult.limitations`; `run()` must never raise on absent data.
- Task id (slug) is exactly `refund_structure_diagnosis`; module file is `analysis/refund_diagnosis.py`; title is `退款结构诊断`.
- No new DuckDB mart; all SQL is inline in the module.
- No Co-Authored-By trailer in commits (attribution disabled globally).
- Respond to the user in Chinese during review.

---

## File Structure

- Create `xhs_ceramics_analytics/analysis/refund_diagnosis.py` — the module (`run` + 5 finding helpers + `_missing_result`/`_table_exists`/`_table_columns`/`_fetch_all` + `_LAYER_LEVERS`).
- Modify `xhs_ceramics_analytics/analytics/confidence.py` — add `two_proportion`.
- Modify `xhs_ceramics_analytics/analysis/registry.py` — import module + register task.
- Create `task_templates/refund_structure_diagnosis.md` — task documentation (mirrored by `scripts/sync-runtime`).
- Modify `tests/test_analytics_confidence.py` — `two_proportion` unit tests.
- Create `tests/test_refund_diagnosis.py` — module integration + degradation tests (tables built in-test via DuckDB for deterministic assertions, following the `test_note_funnel_returns_none_for_zero_denominators` pattern).

---

### Task 1: Branch + `two_proportion` statistics helper

**Files:**
- Modify: `xhs_ceramics_analytics/analytics/confidence.py`
- Test: `tests/test_analytics_confidence.py`

**Interfaces:**
- Consumes: existing `wilson_interval(k, n, z=1.96)` in the same file.
- Produces: `two_proportion(k1: float, n1: float, k2: float, n2: float) -> dict` returning keys `{"diff": float|None, "z": float|None, "significant": bool, "ci_overlap": bool}`. Two-proportion z-test at α=0.05 (`|z| >= 1.96`), plus a Wilson-CI overlap flag as a complementary robustness check. Returns the not-judgable shape `{"diff": None, "z": None, "significant": False, "ci_overlap": True}` when either `n <= 0` or the pooled standard error is 0.

- [ ] **Step 1: Create the branch**

```bash
git checkout -b feat/refund-structure-diagnosis
```
This stacks on `feat/ingestion-hardening` (the refund aliases/REQUIRED columns it depends on are not yet merged to main). Expected: `Switched to a new branch 'feat/refund-structure-diagnosis'`.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_analytics_confidence.py`:

```python
from xhs_ceramics_analytics.analytics.confidence import two_proportion


def test_two_proportion_significant_non_overlapping():
    r = two_proportion(30, 100, 5, 100)
    assert r["diff"] == pytest.approx(0.25, abs=0.001)
    assert r["z"] == pytest.approx(4.65, abs=0.05)
    assert r["significant"] is True
    assert r["ci_overlap"] is False


def test_two_proportion_not_significant_overlapping():
    r = two_proportion(10, 100, 12, 100)
    assert r["significant"] is False
    assert r["ci_overlap"] is True


def test_two_proportion_guards_zero_n():
    r = two_proportion(0, 0, 5, 10)
    assert r == {"diff": None, "z": None, "significant": False, "ci_overlap": True}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_analytics_confidence.py -q`
Expected: FAIL with `ImportError: cannot import name 'two_proportion'`.

- [ ] **Step 4: Implement `two_proportion`**

Append to `xhs_ceramics_analytics/analytics/confidence.py`:

```python
def two_proportion(k1: float, n1: float, k2: float, n2: float) -> dict:
    """Two-proportion z-test (alpha=0.05) plus a Wilson-CI overlap flag.

    Observational comparison of two observed rates k1/n1 vs k2/n2. Reports the
    difference, the z statistic, whether it is significant, and whether the two
    Wilson intervals overlap. Not-judgable (all-None, not significant) when either
    denominator is non-positive or the pooled standard error is zero.
    """
    if n1 <= 0 or n2 <= 0:
        return {"diff": None, "z": None, "significant": False, "ci_overlap": True}
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    z = None if se == 0 else (p1 - p2) / se
    lo1, hi1 = wilson_interval(k1, n1)
    lo2, hi2 = wilson_interval(k2, n2)
    ci_overlap = not (hi1 < lo2 or hi2 < lo1)
    return {
        "diff": p1 - p2,
        "z": z,
        "significant": z is not None and abs(z) >= 1.96,
        "ci_overlap": ci_overlap,
    }
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_analytics_confidence.py -q`
Expected: PASS (all confidence tests green).

- [ ] **Step 6: Commit**

```bash
git add xhs_ceramics_analytics/analytics/confidence.py tests/test_analytics_confidence.py
git commit -m "feat(analytics): two_proportion z-test + Wilson-overlap helper"
```

---

### Task 2: Module scaffold + registry + Finding 1 (layer decomposition)

**Files:**
- Create: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`
- Modify: `xhs_ceramics_analytics/analysis/registry.py`
- Test: `tests/test_refund_diagnosis.py`

**Interfaces:**
- Consumes: `AnalysisResult`, `Finding` from `analysis.result`; `connect` from `db.duck`; `EvidenceStrength`, `score_evidence` from `evidence`; `wilson_interval`, `min_n_guard`, `rate_band` from `analytics.confidence`.
- Produces: `run(db_path: Path) -> AnalysisResult` registered as `TASKS["refund_structure_diagnosis"]`; module-level `TASK_ID = "refund_structure_diagnosis"`, `TITLE = "退款结构诊断"`, `_LAYER_LEVERS: dict[str, str]`; helpers `_table_exists(con, name)->bool`, `_table_columns(con, name)->set[str]`, `_fetch_all(con, table)->list[dict]`, `_missing_result(reason)->AnalysisResult`, `_layer_finding(con, limitations)->tuple[Finding, list[dict]]`. Finding 1 emits table `refund_layer_breakdown` (rows: `layer`, `refund_amount`, `share`) and `key_numbers` `{dominant_layer, dominant_share, overall_refund_rate, ci_low, ci_high, total_refund_amount}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_refund_diagnosis.py`:

```python
from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "refund.duckdb"
    return connect(db_path), db_path


def _make_refund_overview(con, rows):
    con.execute(
        """
        CREATE TABLE refund_overview (
          carrier VARCHAR,
          refund_amount_pay DOUBLE,
          pre_ship_refund_amount DOUBLE,
          post_ship_refund_amount DOUBLE,
          return_refund_amount DOUBLE,
          refund_orders_pay DOUBLE,
          refund_rate_pay DOUBLE,
          refund_users DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO refund_overview VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def test_missing_refund_overview_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert result.task_id == "refund_structure_diagnosis"
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "refund_overview" in result.limitations[0]


def test_layer_finding_identifies_dominant_layer(tmp_path):
    con, db_path = _con(tmp_path)
    # return layer dominates total refund amount
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    layer = result.tables["refund_layer_breakdown"]
    kn = result.findings[0].key_numbers
    assert kn["dominant_layer"] == "return"
    assert {r["layer"] for r in layer} == {"pre_ship", "post_ship", "return"}
    assert result.findings[0].recommended_action  # lever text present
    assert result.findings[0].evidence_strength.value == "weak"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: FAIL with `KeyError: unknown analysis task: refund_structure_diagnosis` (task not registered yet).

- [ ] **Step 3: Create the module**

Create `xhs_ceramics_analytics/analysis/refund_diagnosis.py`:

```python
from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.confidence import (
    min_n_guard,
    rate_band,
    wilson_interval,
)
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength, score_evidence

TASK_ID = "refund_structure_diagnosis"
TITLE = "退款结构诊断"

_LAYER_COLUMNS = {
    "pre_ship": "pre_ship_refund_amount",
    "post_ship": "post_ship_refund_amount",
    "return": "return_refund_amount",
}
_LAYER_LEVERS = {
    "pre_ship": "发货前退款最高：优化下单后拦截话术、库存与发货时效、价格波动预期管理。",
    "post_ship": "发货后退款最高：排查物流破损与时效、加强客服响应与签收提醒。",
    "return": "退货退款最高：核查商品质量、尺寸色差、详情页描述相符度（陶瓷重点：开裂、色差、规格一致性）。",
}


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        if not _table_exists(con, "refund_overview"):
            return _missing_result("缺少 refund_overview 表。")
        findings: list[Finding] = []
        limitations: list[str] = []
        tables: dict[str, list[dict]] = {}

        layer_finding, layer_rows = _layer_finding(con, limitations)
        findings.append(layer_finding)
        tables["refund_layer_breakdown"] = layer_rows
    finally:
        con.close()
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=findings,
        tables=tables,
        limitations=limitations,
    )


def _layer_finding(con, limitations: list[str]) -> tuple[Finding, list[dict]]:
    cols = _table_columns(con, "refund_overview")
    rows = _fetch_all(con, "refund_overview")
    present = {name: col for name, col in _LAYER_COLUMNS.items() if col in cols}
    layer_rows: list[dict] = []
    total = sum(_num(r.get("refund_amount_pay")) for r in rows)
    for layer, col in present.items():
        amount = sum(_num(r.get(col)) for r in rows)
        share = amount / total if total else None
        layer_rows.append({"layer": layer, "refund_amount": amount, "share": share})
    for missing in _LAYER_COLUMNS.keys() - present.keys():
        limitations.append(f"refund_overview 缺少 {_LAYER_COLUMNS[missing]}，跳过 {missing} 层。")

    dominant = max(layer_rows, key=lambda r: r["refund_amount"], default=None)
    # overall refund rate + Wilson CI via reverse-derived paid-order base
    k = sum(_num(r.get("refund_orders_pay")) for r in rows)
    n = sum(
        _num(r.get("refund_orders_pay")) / _num(r.get("refund_rate_pay"))
        for r in rows
        if _num(r.get("refund_rate_pay")) > 0
    )
    overall_rate = k / n if n else None
    lo, hi = wilson_interval(k, n) if min_n_guard(n) else (None, None)

    dominant_layer = dominant["layer"] if dominant else None
    conclusion = (
        f"总退款 {round(total)} 元中，占比最高的是 {_layer_zh(dominant_layer)}"
        f"（{round((dominant['share'] or 0) * 100)}%）。"
        if dominant
        else "退款金额层级列缺失，无法拆解。"
    )
    caveats = ["观察性拆解，非因果；层级份额基于聚合快照。"]
    if lo is not None:
        caveats.append(f"整体退款率 {rate_band(lo, hi)}（样本 n≈{round(n)}）。")
    finding = Finding(
        title="退款主漏点层级",
        conclusion=conclusion,
        evidence_strength=score_evidence(int(n), has_controls=False, confounder_count=1),
        key_numbers={
            "dominant_layer": dominant_layer,
            "dominant_share": dominant["share"] if dominant else None,
            "overall_refund_rate": overall_rate,
            "ci_low": lo,
            "ci_high": hi,
            "total_refund_amount": total,
        },
        caveats=caveats,
        recommended_action=_LAYER_LEVERS.get(dominant_layer) if dominant_layer else None,
        evidence_reason="退款率为观察性比例，样本量以退款订单/退款率反推支付订单基数估计。",
        confounders=["促销节奏", "季节性", "品类结构"],
    )
    return finding, layer_rows


def _layer_zh(layer: str | None) -> str:
    return {"pre_ship": "发货前退款", "post_ship": "发货后退款", "return": "退货退款"}.get(
        layer, "未知层级"
    )


def _num(value) -> float:
    return float(value) if value is not None else 0.0


def _fetch_all(con, table: str) -> list[dict]:
    rel = con.sql(f"SELECT * FROM {table}")
    columns = rel.columns
    return [dict(zip(columns, row)) for row in rel.fetchall()]


def _table_exists(con, table_name: str) -> bool:
    return table_name in {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _table_columns(con, table_name: str) -> set[str]:
    return {row[1] for row in con.sql(f"PRAGMA table_info('{table_name}')").fetchall()}


def _missing_result(reason: str) -> AnalysisResult:
    return AnalysisResult(
        task_id=TASK_ID,
        title=TITLE,
        findings=[
            Finding(
                title="退款结构不可诊断",
                conclusion="需要导出 refund_overview（退款概览）数据后才能诊断退款结构。",
                evidence_strength=EvidenceStrength.NOT_JUDGABLE,
                key_numbers={},
                caveats=["退款概览缺失应视为导入缺口。"],
                recommended_action="导出退款概览（含发货前/发货后/退货退款金额）后重新构建。",
            )
        ],
        tables={"refund_layer_breakdown": []},
        limitations=[reason],
    )
```

- [ ] **Step 4: Register the task**

In `xhs_ceramics_analytics/analysis/registry.py`, add `refund_diagnosis` to the import block (keep alphabetical grouping) and add the `TASKS` entry:

```python
from xhs_ceramics_analytics.analysis import (
    account_baseline,
    ad_quality,
    comment_demand,
    copy_effect,
    cover_effect,
    data_quality,
    experiment_matrix,
    hypothesis,
    note_funnel,
    paid_traffic,
    portfolio,
    product_interaction,
    product_opportunity,
    refund_diagnosis,
    response_curve,
    reshoot,
    sku_lift,
    weekly_review,
)
```

and inside the `TASKS` dict, after the `weekly_business_review` line:

```python
    "weekly_business_review": weekly_review.run,
    "refund_structure_diagnosis": refund_diagnosis.run,
}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: PASS (both tests green).

- [ ] **Step 6: Commit**

```bash
git add xhs_ceramics_analytics/analysis/refund_diagnosis.py xhs_ceramics_analytics/analysis/registry.py tests/test_refund_diagnosis.py
git commit -m "feat(analysis): refund_structure_diagnosis module + layer-decomposition finding"
```

---

### Task 3: Finding 2 — carrier comparison (笔记 vs 商卡)

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`
- Test: `tests/test_refund_diagnosis.py`

**Interfaces:**
- Consumes: `two_proportion` from `analytics.confidence`; `_fetch_all`, `_table_columns`.
- Produces: `_carrier_finding(con, limitations) -> tuple[Finding | None, list[dict]]`. Returns `(None, [])` when the `carrier` column is absent or fewer than two carriers are present (appends a reason to `limitations`). Emits table `carrier_refund_comparison` (rows: `carrier`, `refund_rate`, `refund_orders`, `n`) and `key_numbers` `{carrier_high, diff, significant, ci_overlap}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_refund_diagnosis.py`:

```python
def test_carrier_finding_compares_two_carriers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 300.0, 0.30, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 50.0, 0.05, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    assert "载体退款率对比" in titles
    comp = result.tables["carrier_refund_comparison"]
    assert {r["carrier"] for r in comp} == {"笔记", "商卡"}
    finding = next(f for f in result.findings if f.title == "载体退款率对比")
    assert finding.key_numbers["carrier_high"] == "笔记"
    assert finding.key_numbers["significant"] is True


def test_carrier_finding_skipped_for_single_carrier(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "载体退款率对比" not in [f.title for f in result.findings]
    assert any("载体" in lim for lim in result.limitations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: FAIL (`载体退款率对比` finding not produced; KeyError on `carrier_refund_comparison`).

- [ ] **Step 3: Implement `_carrier_finding` and wire it into `run`**

Add the import at the top of `refund_diagnosis.py` (extend the existing confidence import):

```python
from xhs_ceramics_analytics.analytics.confidence import (
    min_n_guard,
    rate_band,
    two_proportion,
    wilson_interval,
)
```

In `run`, insert immediately after the layer block (before `finally`):

```python
        carrier_finding, carrier_rows = _carrier_finding(con, limitations)
        if carrier_finding is not None:
            findings.append(carrier_finding)
            tables["carrier_refund_comparison"] = carrier_rows
```

Add the helper:

```python
def _carrier_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    cols = _table_columns(con, "refund_overview")
    if "carrier" not in cols:
        limitations.append("refund_overview 缺少 carrier 列，跳过载体对比。")
        return None, []
    rows = _fetch_all(con, "refund_overview")
    by_carrier: list[dict] = []
    for r in rows:
        rate = _num(r.get("refund_rate_pay"))
        orders = _num(r.get("refund_orders_pay"))
        n = round(orders / rate) if rate > 0 else 0
        by_carrier.append(
            {
                "carrier": r.get("carrier"),
                "refund_rate": rate,
                "refund_orders": orders,
                "n": n,
            }
        )
    if len({c["carrier"] for c in by_carrier}) < 2:
        limitations.append("refund_overview 只有单一载体，跳过载体对比。")
        return None, []
    top2 = sorted(by_carrier, key=lambda c: c["refund_rate"], reverse=True)[:2]
    a, b = top2[0], top2[1]
    test = two_proportion(a["refund_orders"], a["n"], b["refund_orders"], b["n"])
    sig = "显著" if test["significant"] else "不显著"
    conclusion = (
        f"{a['carrier']} 退款率（{round(a['refund_rate'] * 100)}%）高于 "
        f"{b['carrier']}（{round(b['refund_rate'] * 100)}%），差异{sig}。"
    )
    finding = Finding(
        title="载体退款率对比",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(a["n"] + b["n"]), has_controls=False, confounder_count=1
        ),
        key_numbers={
            "carrier_high": a["carrier"],
            "diff": test["diff"],
            "significant": test["significant"],
            "ci_overlap": test["ci_overlap"],
        },
        caveats=[
            "观察性对比，非因果；样本量以退款订单/退款率反推。",
            "显著性用两样本比例 z 检验，辅以 Wilson 区间重叠判断。",
        ],
        evidence_reason="载体间退款率差异用两样本比例检验，观察性。",
        confounders=["载体流量结构", "客群差异"],
    )
    return finding, by_carrier
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: PASS (all four tests green).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analysis/refund_diagnosis.py tests/test_refund_diagnosis.py
git commit -m "feat(analysis): refund carrier comparison finding (two-proportion test)"
```

---

### Task 4: Finding 3 — refund-rate time trend

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`
- Test: `tests/test_refund_diagnosis.py`

**Interfaces:**
- Consumes: `mom_change`, `direction_label` from `analytics.trends`; `_table_exists`, `_table_columns`.
- Produces: `_trend_finding(con, limitations) -> tuple[Finding | None, list[dict]]`. Returns `(None, [])` when `business_overview_daily` is absent or lacks `refund_rate_pay`/`date`, or when fewer than two periods exist (append reason to `limitations`). Emits table `refund_trend` (rows: `period`, `refund_rate`) and `key_numbers` `{trend_direction, first_rate, last_rate}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_refund_diagnosis.py`:

```python
def _make_business_overview(con, rows):
    con.execute(
        "CREATE TABLE business_overview_daily (date DATE, refund_rate_pay DOUBLE)"
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?)", rows)


def test_trend_finding_reports_direction(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
              ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0)]
    )
    _make_business_overview(
        con, [("2026-04-30", 0.05), ("2026-05-31", 0.08), ("2026-06-30", 0.12)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "退款率时间趋势")
    assert finding.key_numbers["trend_direction"] == "上升"
    assert len(result.tables["refund_trend"]) == 3


def test_trend_finding_skipped_without_business_overview(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
              ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "退款率时间趋势" not in [f.title for f in result.findings]
    assert any("business_overview_daily" in lim for lim in result.limitations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: FAIL (`退款率时间趋势` finding missing; StopIteration in the trend test).

- [ ] **Step 3: Implement `_trend_finding` and wire it into `run`**

Add the import near the other analytics import in `refund_diagnosis.py`:

```python
from xhs_ceramics_analytics.analytics.trends import direction_label, mom_change
```

In `run`, insert after the carrier block:

```python
        trend_finding, trend_rows = _trend_finding(con, limitations)
        if trend_finding is not None:
            findings.append(trend_finding)
            tables["refund_trend"] = trend_rows
```

Add the helper:

```python
def _trend_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "business_overview_daily"):
        limitations.append("缺少 business_overview_daily 表，跳过退款率时间趋势。")
        return None, []
    cols = _table_columns(con, "business_overview_daily")
    if "refund_rate_pay" not in cols or "date" not in cols:
        limitations.append("business_overview_daily 缺少 date/refund_rate_pay，跳过趋势。")
        return None, []
    result = con.sql(
        """
        SELECT CAST(date AS VARCHAR) AS period, AVG(CAST(refund_rate_pay AS DOUBLE)) AS rate
        FROM business_overview_daily
        WHERE refund_rate_pay IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """
    )
    trend_rows = [{"period": p, "refund_rate": rate} for p, rate in result.fetchall()]
    if len(trend_rows) < 2:
        limitations.append("退款率序列不足两期，跳过趋势。")
        return None, []
    series = [(r["period"], r["refund_rate"]) for r in trend_rows]
    steps = mom_change(series)
    overall_delta = series[-1][1] - series[0][1]
    direction = direction_label(overall_delta)
    finding = Finding(
        title="退款率时间趋势",
        conclusion=(
            f"退款率从 {round(series[0][1] * 100)}% {direction}到 "
            f"{round(series[-1][1] * 100)}%（{len(series)} 期）。"
        ),
        evidence_strength=score_evidence(len(series), has_controls=False, confounder_count=1),
        key_numbers={
            "trend_direction": direction,
            "first_rate": series[0][1],
            "last_rate": series[-1][1],
        },
        caveats=["观察性趋势，非因果；仅报告方向与幅度，未做显著性检验。"],
        evidence_reason="逐期退款率走势，观察性描述。",
        confounders=["促销周期", "季节性"],
        appendix=str(steps),
    )
    return finding, trend_rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analysis/refund_diagnosis.py tests/test_refund_diagnosis.py
git commit -m "feat(analysis): refund-rate time-trend finding"
```

---

### Task 5: Finding 4 — note-level refund reflection

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`
- Test: `tests/test_refund_diagnosis.py`

**Interfaces:**
- Consumes: `wilson_interval`, `min_n_guard`; `_table_exists`, `_table_columns`, `_fetch_all`.
- Produces: `_note_finding(con, limitations) -> tuple[Finding | None, list[dict]]`. Returns `(None, [])` when `notes` is absent or lacks `note_refund_rate_pay` (append reason). Flags high-refund notes whose Wilson lower bound (from k = round(rate × note_paid_orders), n = note_paid_orders) exceeds the paid-order-weighted baseline rate. When `content_features` exists, LEFT JOINs it and reports the most over-represented `composition_type`/`scene_hint`/`copy_angle` value among the high-refund cohort. Emits table `high_refund_notes` (rows: `note_id`, `title`, `note_refund_rate`, `n`, `composition_type`, `scene_hint`, `copy_angle`) and `key_numbers` `{high_refund_note_count, baseline_rate, top_feature}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_refund_diagnosis.py`:

```python
def _make_notes(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR, title VARCHAR,
          note_refund_rate_pay DOUBLE, note_paid_orders DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO notes VALUES (?, ?, ?, ?)", rows)


def _make_content_features(con, rows):
    con.execute(
        """
        CREATE TABLE content_features (
          note_id VARCHAR, composition_type VARCHAR,
          scene_hint VARCHAR, copy_angle VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO content_features VALUES (?, ?, ?, ?)", rows)


def _refund_overview_two(con):
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
              ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0)]
    )


def test_note_finding_flags_high_refund_and_feature(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    # two clearly high-refund notes share composition 'flatlay'; low-refund notes differ
    _make_notes(
        con,
        [
            ("n1", "高退款A", 0.40, 100.0),
            ("n2", "高退款B", 0.38, 100.0),
            ("n3", "低退款C", 0.03, 100.0),
            ("n4", "低退款D", 0.02, 100.0),
        ],
    )
    _make_content_features(
        con,
        [
            ("n1", "flatlay", "kitchen", "price"),
            ("n2", "flatlay", "studio", "quality"),
            ("n3", "closeup", "kitchen", "story"),
            ("n4", "closeup", "outdoor", "story"),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "笔记退款反思")
    assert finding.key_numbers["high_refund_note_count"] >= 1
    ids = {r["note_id"] for r in result.tables["high_refund_notes"]}
    assert {"n1", "n2"} <= ids


def test_note_finding_degrades_without_content_features(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_notes(con, [("n1", "高退款A", 0.40, 100.0), ("n2", "低退款B", 0.02, 100.0)])
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "笔记退款反思")
    assert finding.key_numbers["top_feature"] is None
    assert any("特征" in c for c in finding.caveats)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: FAIL (`笔记退款反思` finding missing).

- [ ] **Step 3: Implement `_note_finding` and wire it into `run`**

In `run`, insert after the trend block:

```python
        note_finding, note_rows = _note_finding(con, limitations)
        if note_finding is not None:
            findings.append(note_finding)
            tables["high_refund_notes"] = note_rows
```

Add the helper (and a small `_top_feature` utility):

```python
_NOTE_FEATURES = ("composition_type", "scene_hint", "copy_angle")


def _note_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "notes"):
        limitations.append("缺少 notes 表，跳过笔记退款反思。")
        return None, []
    cols = _table_columns(con, "notes")
    if "note_refund_rate_pay" not in cols:
        limitations.append("notes 缺少 note_refund_rate_pay，跳过笔记退款反思。")
        return None, []
    has_features = _table_exists(con, "content_features")
    if has_features:
        rows = con.sql(
            """
            SELECT n.note_id, n.title, n.note_refund_rate_pay AS rate,
                   n.note_paid_orders AS paid,
                   f.composition_type, f.scene_hint, f.copy_angle
            FROM notes n LEFT JOIN content_features f USING (note_id)
            WHERE n.note_refund_rate_pay IS NOT NULL
            """
        ).fetchall()
        columns = ["note_id", "title", "rate", "paid",
                   "composition_type", "scene_hint", "copy_angle"]
    else:
        rows = con.sql(
            """
            SELECT note_id, title, note_refund_rate_pay AS rate, note_paid_orders AS paid
            FROM notes WHERE note_refund_rate_pay IS NOT NULL
            """
        ).fetchall()
        columns = ["note_id", "title", "rate", "paid"]
    records = [dict(zip(columns, r)) for r in rows]

    total_k = sum(_num(r["rate"]) * _num(r["paid"]) for r in records)
    total_n = sum(_num(r["paid"]) for r in records)
    baseline = total_k / total_n if total_n else 0.0

    high: list[dict] = []
    for r in records:
        paid = _num(r["paid"])
        rate = _num(r["rate"])
        k = round(rate * paid)
        lo, _ = wilson_interval(k, paid)
        if min_n_guard(paid) and lo > baseline:
            high.append(
                {
                    "note_id": r["note_id"],
                    "title": r["title"],
                    "note_refund_rate": rate,
                    "n": paid,
                    "composition_type": r.get("composition_type"),
                    "scene_hint": r.get("scene_hint"),
                    "copy_angle": r.get("copy_angle"),
                }
            )

    top_feature = _top_feature(high, _NOTE_FEATURES) if has_features else None
    caveats = ["观察性反思，非因果——高退款笔记的共有特征仅供假设生成。"]
    if not has_features:
        caveats.append("缺少 content_features，仅列高退款笔记，无法归因特征。")
    conclusion = (
        f"共 {len(high)} 篇笔记退款率显著高于基线（{round(baseline * 100)}%）。"
        + (f" 高退款笔记更多集中在 {top_feature}。" if top_feature else "")
    )
    finding = Finding(
        title="笔记退款反思",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_n), has_controls=False, confounder_count=1
        ),
        key_numbers={
            "high_refund_note_count": len(high),
            "baseline_rate": baseline,
            "top_feature": top_feature,
        },
        caveats=caveats,
        evidence_reason="以 Wilson 下界高于加权基线判定高退款笔记，避免小样本误报。",
        confounders=["选品差异", "定价", "客群"],
        next_test="对疑似高退款特征做重拍/A-B 验证后复测退款率。",
    )
    return finding, high


def _top_feature(cohort: list[dict], feature_keys: tuple[str, ...]) -> str | None:
    best: tuple[str, str, int] | None = None
    for key in feature_keys:
        counts: dict[str, int] = {}
        for r in cohort:
            value = r.get(key)
            if value is not None:
                counts[value] = counts.get(value, 0) + 1
        for value, count in counts.items():
            if best is None or count > best[2]:
                best = (key, value, count)
    return f"{best[0]}={best[1]}" if best else None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analysis/refund_diagnosis.py tests/test_refund_diagnosis.py
git commit -m "feat(analysis): note-level refund reflection finding"
```

---

### Task 6: Finding 5 — product-level refund reflection

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`
- Test: `tests/test_refund_diagnosis.py`

**Interfaces:**
- Consumes: `wilson_interval`, `min_n_guard`, `_top_feature`, `_num`, `_table_exists`, `_table_columns`.
- Produces: `_product_finding(con, limitations) -> tuple[Finding | None, list[dict]]`. Returns `(None, [])` when `sku_performance` is absent or lacks `refund_rate_pay`/`product_id` (append reason). Aggregates `sku_performance` to `product_id`; refund amount = `SUM(gmv) - SUM(net_gmv_pay)`; ranks by refund amount (Pareto `amount_share`), flags high-refund products by refund rate vs the gmv-implied baseline (Wilson-guarded when `refund_orders_pay` present, else flagged by rate with a caveat). LEFT JOINs `products` for `vessel_type`/`series`/`category`/`price_band` reflection when present. Emits table `product_refund_concentration` (rows: `product_id`, `product_name`, `refund_amount`, `amount_share`, `refund_rate`, `n`, `vessel_type`, `series`, `category`, `price_band`) and `key_numbers` `{high_refund_product_count, top_products_amount_share, baseline_rate, top_feature}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_refund_diagnosis.py`:

```python
def _make_sku_performance(con, rows):
    con.execute(
        """
        CREATE TABLE sku_performance (
          product_id VARCHAR, product_name VARCHAR,
          gmv DOUBLE, net_gmv_pay DOUBLE,
          refund_rate_pay DOUBLE, refund_orders_pay DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO sku_performance VALUES (?, ?, ?, ?, ?, ?)", rows
    )


def _make_products(con, rows):
    con.execute(
        """
        CREATE TABLE products (
          product_id VARCHAR, vessel_type VARCHAR,
          series VARCHAR, category VARCHAR, price_band VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", rows)


def test_product_finding_flags_high_refund_and_feature(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_sku_performance(
        con,
        [
            ("p1", "青釉杯", 10000.0, 6000.0, 0.40, 100.0),
            ("p2", "白瓷盘", 9000.0, 5500.0, 0.39, 100.0),
            ("p3", "茶壶", 8000.0, 7800.0, 0.02, 100.0),
        ],
    )
    _make_products(
        con,
        [
            ("p1", "杯", "青釉", "杯具", "50-100"),
            ("p2", "盘", "青釉", "盘具", "50-100"),
            ("p3", "壶", "白瓷", "壶具", "100-200"),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "产品退款反思")
    ids = {r["product_id"] for r in result.tables["product_refund_concentration"]}
    assert {"p1", "p2", "p3"} == ids
    assert finding.key_numbers["high_refund_product_count"] >= 1
    assert finding.key_numbers["top_feature"] is not None


def test_product_finding_degrades_without_products(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_sku_performance(
        con, [("p1", "青釉杯", 10000.0, 6000.0, 0.40, 100.0),
              ("p2", "茶壶", 8000.0, 7800.0, 0.02, 100.0)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "产品退款反思")
    assert finding.key_numbers["top_feature"] is None
    assert any("特征" in c for c in finding.caveats)


def test_product_finding_skipped_without_sku_performance(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "产品退款反思" not in [f.title for f in result.findings]
    assert any("sku_performance" in lim for lim in result.limitations)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: FAIL (`产品退款反思` finding missing).

- [ ] **Step 3: Implement `_product_finding` and wire it into `run`**

In `run`, insert after the note block:

```python
        product_finding, product_rows = _product_finding(con, limitations)
        if product_finding is not None:
            findings.append(product_finding)
            tables["product_refund_concentration"] = product_rows
```

Add the helper:

```python
_PRODUCT_FEATURES = ("vessel_type", "series", "category", "price_band")


def _product_finding(con, limitations: list[str]) -> tuple[Finding | None, list[dict]]:
    if not _table_exists(con, "sku_performance"):
        limitations.append("缺少 sku_performance 表，跳过产品退款反思。")
        return None, []
    cols = _table_columns(con, "sku_performance")
    if "refund_rate_pay" not in cols or "product_id" not in cols:
        limitations.append("sku_performance 缺少 product_id/refund_rate_pay，跳过产品退款反思。")
        return None, []
    has_orders = "refund_orders_pay" in cols
    has_products = _table_exists(con, "products")
    orders_expr = "SUM(CAST(refund_orders_pay AS DOUBLE))" if has_orders else "NULL"
    gmv_expr = "SUM(CAST(gmv AS DOUBLE))" if "gmv" in cols else "NULL"
    net_expr = "SUM(CAST(net_gmv_pay AS DOUBLE))" if "net_gmv_pay" in cols else "NULL"
    agg = con.sql(
        f"""
        SELECT product_id, ANY_VALUE(product_name) AS product_name,
               {gmv_expr} AS gmv, {net_expr} AS net_gmv,
               AVG(CAST(refund_rate_pay AS DOUBLE)) AS rate,
               {orders_expr} AS refund_orders
        FROM sku_performance GROUP BY product_id
        """
    ).fetchall()
    columns = ["product_id", "product_name", "gmv", "net_gmv", "rate", "refund_orders"]
    records = [dict(zip(columns, r)) for r in agg]

    attrs: dict[str, dict] = {}
    if has_products:
        pcols = _table_columns(con, "products")
        sel = ", ".join(f for f in _PRODUCT_FEATURES if f in pcols)
        if sel:
            for r in con.sql(f"SELECT product_id, {sel} FROM products").fetchall():
                keys = ["product_id"] + [f for f in _PRODUCT_FEATURES if f in pcols]
                attrs[r[0]] = dict(zip(keys, r))

    total_refund = sum(_num(r["gmv"]) - _num(r["net_gmv"]) for r in records)
    total_k = sum(_num(r["rate"]) * _num(r["refund_orders"]) for r in records) if has_orders else 0.0
    total_n = sum(_num(r["refund_orders"]) for r in records) if has_orders else 0.0
    baseline = (total_k / total_n) if total_n else (
        sum(_num(r["rate"]) for r in records) / len(records) if records else 0.0
    )

    product_rows: list[dict] = []
    high: list[dict] = []
    for r in records:
        refund_amount = _num(r["gmv"]) - _num(r["net_gmv"])
        rate = _num(r["rate"])
        n = _num(r["refund_orders"])
        attr = attrs.get(r["product_id"], {})
        row = {
            "product_id": r["product_id"],
            "product_name": r["product_name"],
            "refund_amount": refund_amount,
            "amount_share": refund_amount / total_refund if total_refund else None,
            "refund_rate": rate,
            "n": n if has_orders else None,
            "vessel_type": attr.get("vessel_type"),
            "series": attr.get("series"),
            "category": attr.get("category"),
            "price_band": attr.get("price_band"),
        }
        product_rows.append(row)
        if has_orders and n > 0:
            lo, _ = wilson_interval(round(rate * n), n)
            flagged = min_n_guard(n) and lo > baseline
        else:
            flagged = rate > baseline
        if flagged:
            high.append(row)

    product_rows.sort(key=lambda r: r["refund_amount"], reverse=True)
    top_feature = _top_feature(high, _PRODUCT_FEATURES) if has_products else None
    top_share = sum(r["amount_share"] or 0 for r in product_rows[:3])
    caveats = ["观察性反思，非因果——高退款产品的共有特征仅供假设生成。"]
    if not has_products:
        caveats.append("缺少 products，仅列高退款产品，无法归因特征。")
    if not has_orders:
        caveats.append("缺少 refund_orders_pay，产品退款率未做订单量 Wilson 守卫。")
    conclusion = (
        f"高退款产品 {len(high)} 个，退款金额前三占 {round(top_share * 100)}%。"
        + (f" 高退款集中在 {top_feature}。" if top_feature else "")
    )
    finding = Finding(
        title="产品退款反思",
        conclusion=conclusion,
        evidence_strength=score_evidence(
            int(total_n) if has_orders else len(records),
            has_controls=False,
            confounder_count=1,
        ),
        key_numbers={
            "high_refund_product_count": len(high),
            "top_products_amount_share": top_share,
            "baseline_rate": baseline,
            "top_feature": top_feature,
        },
        caveats=caveats,
        recommended_action="对高退款产品优先做质量抽检 / 详情页尺寸与色差描述修订，评估下架或换供应。",
        evidence_reason="产品退款金额=支付-退款后支付；高退款以退款率对比基线（有订单量时 Wilson 守卫）。",
        confounders=["品类结构", "定价带", "上新周期"],
        next_test="对疑似器型/系列做质量抽检或描述修订后复测退款率。",
    )
    return finding, product_rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_refund_diagnosis.py -q`
Expected: PASS (all refund-module tests green).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analysis/refund_diagnosis.py tests/test_refund_diagnosis.py
git commit -m "feat(analysis): product-level refund reflection finding"
```

---

### Task 7: Task template + runtime mirror + full-suite verification

**Files:**
- Create: `task_templates/refund_structure_diagnosis.md`
- Modify (generated): `skills/data-analyze-for-zcl/assets/xhs-ca/**` (via `scripts/sync-runtime`)

**Interfaces:**
- Consumes: the finished module and its findings.
- Produces: task documentation following the existing template shape (`account_baseline.md`), plus a regenerated runtime mirror.

- [ ] **Step 1: Write the task template**

Create `task_templates/refund_structure_diagnosis.md`:

```markdown
# refund_structure_diagnosis

**Slug**: `refund_structure_diagnosis`  |  **Module**: `xhs_ceramics_analytics/analysis/refund_diagnosis.py`  |  **Registry**: registry.py

## Purpose

诊断退款结构并定位杆杆：把总退款拆为发货前/发货后/退货三层，比较载体（笔记/商卡）退款率，报告退款率时间趋势，并两方面下钻——哪些笔记、哪些产品退款高及其共有特征。全程内部相对基准，观察性、非因果。

## Required tables & fields

- `refund_overview` (required) — `refund_amount_pay`, `pre_ship_refund_amount`, `post_ship_refund_amount`, `return_refund_amount`, `refund_orders_pay`, `refund_rate_pay`, `carrier`
- `business_overview_daily` (optional) — `date`, `refund_rate_pay`（趋势）
- `notes` (optional) — `note_refund_rate_pay`, `note_paid_orders`, `title`（笔记反思）
- `content_features` (optional) — `composition_type`, `scene_hint`, `copy_angle`（笔记特征）
- `sku_performance` (optional) — `product_id`, `gmv`, `net_gmv_pay`, `refund_rate_pay`, `refund_orders_pay`（产品反思）
- `products` (optional) — `vessel_type`, `series`, `category`, `price_band`（产品特征）

## Method

1. 无 `refund_overview` → NOT_JUDGABLE。
2. Finding 1 层级拆解：三层金额份额 + 整体退款率 Wilson CI（n 由 refund_orders/refund_rate 反推）+ 陶瓷杆杆。
3. Finding 2 载体对比：两载体退款率 `two_proportion` 检验（<2 载体则跳过）。
4. Finding 3 时间趋势：`business_overview_daily` 逐期退款率方向（<2 期或缺表则跳过）。
5. Finding 4 笔记反思：Wilson 下界 > 加权基线判高退款笔记；有 content_features 则报过度代表特征。
6. Finding 5 产品反思：sku_performance 聚合到 product_id，退款金额 Pareto + 高退款标记（有订单量则 Wilson 守卫）；有 products 则报过度代表特征。

## Thresholds & evidence

- 所有 finding `has_controls=False` → 证据强度上限 WEAK。
- `min_n_guard` = 30 退款订单（`MIN_ORDERS_FOR_RATE`）。
- 显著性：两样本比例 z 检验 |z|>=1.96，辅以 Wilson 区间重叠。

## Output

- Tables: `refund_layer_breakdown`, `carrier_refund_comparison`, `refund_trend`, `high_refund_notes`, `product_refund_concentration`（缺源则不建对应表）。
- Findings: 退款主漏点层级 / 载体退款率对比 / 退款率时间趋势 / 笔记退款反思 / 产品退款反思。

## Common failure modes

- 无 refund_overview → NOT_JUDGABLE，limitations 记原因。
- 单一载体 / 无 business_overview_daily / 无 notes / 无 content_features / 无 sku_performance / 无 products → 对应 finding 跳过或降级，其余照常。

## Cross-links

- Reference: [../references/data_contract.md](../references/data_contract.md)
- Skeleton for: §2 核心经营 / §5 搜索 / §6 人群 报告模块。
```

- [ ] **Step 2: Run the full root test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — the prior baseline (281 passed) plus the new refund-module tests and `two_proportion` tests, 0 failures.

- [ ] **Step 3: Regenerate the runtime mirror**

Run: `.venv/bin/python scripts/sync-runtime`
Expected: mirror updated under `skills/data-analyze-for-zcl/assets/xhs-ca/` (module, registry, template copied).

- [ ] **Step 4: Verify the mirror suite**

Run: `cd skills/data-analyze-for-zcl/assets/xhs-ca && ../../../../.venv/bin/python -m pytest -q; cd - >/dev/null`
Expected: `N passed, 3 skipped` (0 failures). The 3 skips are the pre-existing structural skips (`test_bootstrap_runtime.py`, `test_project_foundation.py`) — expected, not a regression.

- [ ] **Step 5: Commit**

```bash
git add task_templates/refund_structure_diagnosis.md skills/data-analyze-for-zcl/assets/xhs-ca
git commit -m "docs(task): refund_structure_diagnosis template + sync runtime mirror"
```

---

## Self-Review

**1. Spec coverage:**
- Module contract/location/registration → Task 2. ✅
- `two_proportion` helper → Task 1. ✅
- Finding 1 layer decomposition + Wilson + lever → Task 2. ✅
- Finding 2 carrier two-proportion → Task 3. ✅
- Finding 3 time trend → Task 4. ✅
- Finding 4 note reflection (4a flag + 4b feature; degrade w/o content_features) → Task 5. ✅
- Finding 5 product reflection (5a Pareto/flag + 5b feature; degrade w/o products; skip w/o sku_performance) → Task 6. ✅
- Ceramics lever lookup → `_LAYER_LEVERS` in Task 2. ✅
- Degradation matrix (6 branches + NOT_JUDGABLE) → tests across Tasks 2–6. ✅
- Output tables (5) → emitted across Tasks 2–6. ✅
- Evidence honesty (WEAK ceiling, caveats) → every finding. ✅
- Internal relative baseline, reverse-derived n → Findings 1/2/4/5. ✅
- No new mart → all inline SQL. ✅
- Template + mirror → Task 7. ✅

**2. Placeholder scan:** No TBD/TODO; every code step shows complete code; every test shows assertions. ✅

**3. Type consistency:** `run(db_path)->AnalysisResult`; each `_*_finding(con, limitations)->tuple[Finding|None, list[dict]]`; `_top_feature(cohort, feature_keys)->str|None` defined in Task 5 and reused in Task 6; `_num`/`_fetch_all`/`_table_exists`/`_table_columns` defined in Task 2 and reused throughout; `two_proportion` return keys match between Task 1 and Task 3 usage. ✅

## Notes for the executor

- Tasks 2–6 all edit the same module and test file **sequentially** — this is intentional (skeleton is built in one lane; parallelism is reserved for the later §2/§5/§6 modules that clone this shape).
- The `notes` table for Finding 4 comes from a commerce-style export (`note_refund_rate_pay` etc.); tests build it directly for deterministic assertions rather than depending on fixture contents.
- `run()` grows by one guarded block per task; keep the block order layer → carrier → trend → note → product so finding indices are stable.
