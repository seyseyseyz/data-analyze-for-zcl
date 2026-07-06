# Hybrid Report Writer — Plan 1: Deterministic Facts & Intelligence Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fully-deterministic foundation of the hybrid report — computed intelligence (Welch test, Pareto curve, calendar-month GMV bridge, money/ledger/guardrail/trust primitives), the two chart changes, and a byte-deterministic `facts.json` with a golden `facts_hash` — so that a merchant narrative layer (Plan 2/3) has one trustworthy source of every number.

**Architecture:** L1 analysis modules already emit `Finding`/`AnalysisResult` (unchanged contract). New pure-Python primitives under `analytics/` and `reporting/` compute the intelligence the report needs; `reporting/facts_export.py` collects it into an immutable `FactBook` whose only number-strings are Python-owned `rendered` fields; `facts_hash` canonicalizes that book (excluding raw floats) into a stable cache key. No agents, no LLM — this whole plan runs identically on any host.

**Tech Stack:** Python 3.14, stdlib only for the math (no scipy/numpy), DuckDB (existing), Typer CLI, pytest, ruff (line-length 100), inline-SVG charts.

## Global Constraints

- Python 3.14; `.venv/bin/python` is THE interpreter for every command below.
- Ruff line-length 100.
- Modules never raise; on bad input they degrade and record — never `raise` into the report path.
- Emoji is real merchant content — never strip it.
- No `Co-Authored-By` trailer. Commit/push only on explicit user request (this plan's commit steps stage + commit locally; do not push).
- No deterministic note→order attribution anywhere; observational data caps causal evidence at WEAK.
- Efficiency/per-visitor money uses `product_visitors` (商品访客 UV) ONLY — `total_visitors` is isolated, never used in an efficiency ratio.
- Every number that reaches a report must trace to a computed fact; `facts_hash` excludes raw float `value` so float noise (8.68 vs 8.6800001) never thrashes the cache.
- Chinese, non-technical caliber in all reader-facing strings.
- Preserve all existing green tests (runtime mirror suite 278 passed + 3 skipped by design; main suite ~619).

---

## File Structure

**New (deterministic Python):**
- `xhs_ceramics_analytics/reporting/money.py` — per-visitor GMV caliber, efficiency-ceiling counterfactual, pre-ship recoverable pool.
- `xhs_ceramics_analytics/reporting/money_ledger.py` — non-additive recoverable ledger (parallel pools, no net total).
- `xhs_ceramics_analytics/reporting/guardrails.py` — threshold hint bar (observed vs policy/experience line).
- `xhs_ceramics_analytics/reporting/trust_routing.py` — 强/中/弱 confidence tag from the two evidence axes + claim kind.
- `xhs_ceramics_analytics/reporting/facts_export.py` — `Fact`/`FactBook` dataclasses, assembly from `AnalysisResult`, canonicalization + `facts_hash`, JSON serialization.

**Modified:**
- `xhs_ceramics_analytics/analytics/confidence.py` — `+ mean_diff_test` (Welch t + z-based CI, stdlib).
- `xhs_ceramics_analytics/analytics/concentration.py` — `+ cumulative_curve` (Pareto descending curve).
- `xhs_ceramics_analytics/analysis/core_business.py` — `_growth_attribution_finding` split-half → calendar-month aggregation; caliber strings updated.
- `xhs_ceramics_analytics/reporting/charts.py` — `_line` gains `suppress_aggregate`; new `_waterfall` floating-bar renderer.
- `xhs_ceramics_analytics/cli.py` — `+ facts` subcommand (emits `facts.json` + prints hash).

**Tests (new):** one test module per component under `tests/`.

---

### Task 1: Welch two-mean test (`mean_diff_test`)

**Files:**
- Modify: `xhs_ceramics_analytics/analytics/confidence.py` (append after `min_detectable_effect`)
- Test: `tests/test_analytics_mean_diff.py`

**Interfaces:**
- Consumes: existing `to_finite_float` (already imported in the module).
- Produces: `mean_diff_test(a: list[float], b: list[float], z: float = 1.96) -> dict` returning
  `{"mean_a", "mean_b", "diff", "t", "df", "significant", "ci_low", "ci_high"}`. `diff = mean_a - mean_b`.
  All-None + `significant=False` when either sample has < 2 finite values or the pooled SE is 0.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_mean_diff.py
"""Welch's two-mean test — unequal-variance t plus a z-based CI on the difference."""
import pytest

from xhs_ceramics_analytics.analytics.confidence import mean_diff_test


def test_clear_difference_is_significant():
    # Tight, well-separated samples → large |t|, significant, CI excludes 0.
    a = [10.0, 10.2, 9.8, 10.1, 9.9, 10.0, 10.1, 9.9]
    b = [8.6, 8.8, 8.5, 8.7, 8.6, 8.5, 8.7, 8.6]
    r = mean_diff_test(a, b)
    assert r["diff"] == pytest.approx(1.425, abs=0.05)
    assert r["significant"] is True
    assert r["ci_low"] > 0 and r["ci_high"] > 0


def test_overlapping_samples_not_significant():
    a = [10.0, 8.0, 12.0, 9.0, 11.0]
    b = [10.5, 8.5, 11.5, 9.5, 10.0]
    r = mean_diff_test(a, b)
    assert r["significant"] is False
    assert r["ci_low"] < 0 < r["ci_high"]


def test_degrades_on_thin_or_dirty_input():
    assert mean_diff_test([1.0], [2.0, 3.0]) == {
        "mean_a": None, "mean_b": None, "diff": None, "t": None,
        "df": None, "significant": False, "ci_low": None, "ci_high": None,
    }
    # NaN/inf dropped, not propagated.
    r = mean_diff_test([10.0, float("nan"), 10.0, 10.0], [8.0, 8.0, float("inf"), 8.0])
    assert r["diff"] == pytest.approx(2.0, abs=1e-9)


def test_zero_variance_zero_se_degrades():
    # Both samples constant and equal → SE 0 → not judgable, never divides by zero.
    r = mean_diff_test([5.0, 5.0, 5.0], [5.0, 5.0, 5.0])
    assert r["significant"] is False
    assert r["t"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_analytics_mean_diff.py -v`
Expected: FAIL — `ImportError: cannot import name 'mean_diff_test'`.

- [ ] **Step 3: Write minimal implementation**

Append to `xhs_ceramics_analytics/analytics/confidence.py`:

```python
def _finite(values: list[float]) -> list[float]:
    return [x for x in (to_finite_float(v) for v in values) if x is not None]


def _mean_var(values: list[float]) -> tuple[float, float, int]:
    n = len(values)
    mean = sum(values) / n
    var = sum((x - mean) ** 2 for x in values) / (n - 1)  # sample variance
    return mean, var, n


def mean_diff_test(a: list[float], b: list[float], z: float = 1.96) -> dict:
    """Welch's t-test for the difference of two means (a − b), plus a z-based CI.

    Compares two independent samples without assuming equal variances (e.g. 5月 vs
    6月 daily per-visitor GMV). Significance uses ``|t| >= z`` — with day-level n≈30
    per month the t critical value is ≈1.99, so the codebase's hardcoded 1.96 normal
    quantile is a deliberate, documented approximation (no scipy dependency). The CI
    is the normal-approximation ``diff ± z·SE``. Not-judgable (all-None) when either
    sample has fewer than two finite values or the pooled SE is zero. Never raises.
    """
    fa, fb = _finite(a), _finite(b)
    none = {
        "mean_a": None, "mean_b": None, "diff": None, "t": None,
        "df": None, "significant": False, "ci_low": None, "ci_high": None,
    }
    if len(fa) < 2 or len(fb) < 2:
        return none
    mean_a, var_a, na = _mean_var(fa)
    mean_b, var_b, nb = _mean_var(fb)
    se = math.sqrt(var_a / na + var_b / nb)
    if se == 0:
        return none
    diff = mean_a - mean_b
    t = diff / se
    # Welch–Satterthwaite degrees of freedom (reported for honesty; not used in the
    # normal-approx CI, but tells a reader how much the two variances differ).
    num = (var_a / na + var_b / nb) ** 2
    den = (var_a / na) ** 2 / (na - 1) + (var_b / nb) ** 2 / (nb - 1)
    df = num / den if den > 0 else None
    return {
        "mean_a": mean_a, "mean_b": mean_b, "diff": diff, "t": t, "df": df,
        "significant": abs(t) >= z, "ci_low": diff - z * se, "ci_high": diff + z * se,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_analytics_mean_diff.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/confidence.py tests/test_analytics_mean_diff.py
git commit -m "feat(analytics): add Welch mean_diff_test for day-level significance"
```

---

### Task 2: Pareto cumulative curve (`cumulative_curve`)

**Files:**
- Modify: `xhs_ceramics_analytics/analytics/concentration.py` (append after `concentration_trend`)
- Test: `tests/test_analytics_cumulative_curve.py`

**Interfaces:**
- Consumes: existing `_clean` (module-private, already defined).
- Produces: `cumulative_curve(values: list[float]) -> list[dict]` — rows sorted largest-first, each
  `{"rank": int, "cum_item_frac": float, "cum_value_share": float}`. `rank` is 1-based; the final row
  has `cum_item_frac == 1.0` and `cum_value_share == 1.0`. Empty/zero-total/negative-only base → `[]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_cumulative_curve.py
"""Descending Pareto curve — 'top X% of SKUs = Y% of GMV'."""
import pytest

from xhs_ceramics_analytics.analytics.concentration import cumulative_curve


def test_top_two_of_ten_hold_eighty_percent():
    values = [40.0, 40.0] + [2.5] * 8  # top 20% (2 of 10) = 80% of total
    curve = cumulative_curve(values)
    assert len(curve) == 10
    assert curve[0]["rank"] == 1
    assert curve[1]["cum_item_frac"] == pytest.approx(0.2)
    assert curve[1]["cum_value_share"] == pytest.approx(0.8)
    assert curve[-1]["cum_item_frac"] == pytest.approx(1.0)
    assert curve[-1]["cum_value_share"] == pytest.approx(1.0)


def test_descending_and_monotonic():
    curve = cumulative_curve([1.0, 5.0, 3.0, 2.0])
    shares = [r["cum_value_share"] for r in curve]
    assert shares == sorted(shares)  # non-decreasing
    assert shares[0] == pytest.approx(5.0 / 11.0)  # largest first


def test_degrades_on_bad_input():
    assert cumulative_curve([]) == []
    assert cumulative_curve([0.0, 0.0]) == []
    assert cumulative_curve([-1.0, -2.0]) == []


def test_order_independent_with_dirty_entries():
    assert cumulative_curve([3.0, 1.0, float("nan"), 2.0]) == cumulative_curve([1.0, 2.0, 3.0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_analytics_cumulative_curve.py -v`
Expected: FAIL — `ImportError: cannot import name 'cumulative_curve'`.

- [ ] **Step 3: Write minimal implementation**

Append to `xhs_ceramics_analytics/analytics/concentration.py`:

```python
def cumulative_curve(values: list[float]) -> list[dict]:
    """Descending Pareto curve: cumulative value share as holders join largest-first.

    Each row is ``{rank, cum_item_frac, cum_value_share}`` so a report can state
    "top X% of SKUs hold Y% of GMV". Drops None/non-finite/negative entries; an
    empty or zero-total base returns ``[]``. Deterministic: ties keep a stable
    descending order.
    """
    clean = [v for v in _clean(values) if v >= 0]
    total = sum(clean)
    if not clean or total <= 0:
        return []
    ordered = sorted(clean, reverse=True)
    n = len(ordered)
    rows: list[dict] = []
    running = 0.0
    for i, v in enumerate(ordered):
        running += v
        rows.append(
            {
                "rank": i + 1,
                "cum_item_frac": (i + 1) / n,
                "cum_value_share": running / total,
            }
        )
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_analytics_cumulative_curve.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/concentration.py tests/test_analytics_cumulative_curve.py
git commit -m "feat(analytics): add cumulative_curve for SKU Pareto head-share"
```

---

### Task 3: Calendar-month GMV bridge (kill split-half)

**Files:**
- Modify: `xhs_ceramics_analytics/analysis/core_business.py` — `_growth_attribution_finding` (693–766), `_BRIDGE_CALIBER` (795), `_bridge_conclusion` (808–839)
- Test: `tests/test_core_business_calendar_bridge.py`

**Interfaces:**
- Consumes: existing `gmv_bridge` (from `analytics.decomposition`), `to_period_month` (from `analytics.periods`, NEW import), `_table_columns`, `_fetch_all`, `_num`, `money`, `score_evidence`, `score_reliability`, `Finding`.
- Produces: unchanged return type `tuple[Finding | None, dict[str, list[dict]]]`. Behavior change:
  aggregation is by calendar month (`to_period_month(date)`), bridge runs earliest-month → latest-month,
  and caveats name the two months (e.g. `2026-05`/`2026-06`) instead of "前段/后段".

- [ ] **Step 1: Write the failing test**

```python
# tests/test_core_business_calendar_bridge.py
"""Growth attribution bridges calendar months, not an arbitrary split-half."""
from pathlib import Path

import duckdb
import pytest

from xhs_ceramics_analytics.analysis.core_business import _growth_attribution_finding


def _con_with_two_months(tmp_path: Path):
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE business_overview_daily "
        "(date INTEGER, gmv DOUBLE, paid_buyers DOUBLE, product_visitors DOUBLE)"
    )
    # 2026-05: 15 days; 2026-06: 15 days. Values chosen so ΔGMV is non-trivial.
    rows = []
    for d in range(1, 16):
        rows.append((20260500 + d, 2000.0, 20.0, 400.0))  # May
    for d in range(1, 16):
        rows.append((20260600 + d, 1700.0, 18.0, 420.0))  # June
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)", rows)
    con.close()
    return db


def test_bridge_names_calendar_months_not_halves(tmp_path):
    con = duckdb.connect(str(_con_with_two_months(tmp_path)))
    finding, tables = _growth_attribution_finding(con, [])
    con.close()
    assert finding is not None
    joined = finding.conclusion + " ".join(finding.caveats)
    assert "2026-05" in joined and "2026-06" in joined
    assert "前半程" not in joined and "前段" not in joined


def test_bridge_residual_reconciles_to_zero(tmp_path):
    con = duckdb.connect(str(_con_with_two_months(tmp_path)))
    finding, tables = _growth_attribution_finding(con, [])
    con.close()
    kn = finding.key_numbers
    total = (kn["contrib_traffic"] or 0) + (kn["contrib_conversion"] or 0) + (kn["contrib_aov"] or 0)
    assert kn["delta_gmv"] == pytest.approx(total + (kn["residual"] or 0), abs=1e-6)


def test_single_month_degrades(tmp_path):
    db = tmp_path / "one.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE business_overview_daily "
        "(date INTEGER, gmv DOUBLE, paid_buyers DOUBLE, product_visitors DOUBLE)"
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)",
        [(20260600 + d, 1700.0, 18.0, 420.0) for d in range(1, 10)],
    )
    limitations: list[str] = []
    finding, tables = _growth_attribution_finding(con, limitations)
    con.close()
    assert finding is None
    assert any("月" in msg for msg in limitations)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_core_business_calendar_bridge.py -v`
Expected: FAIL — caveats still say "前段/后段"; single-month case still splits and does not degrade.

- [ ] **Step 3: Add the `to_period_month` import**

In `xhs_ceramics_analytics/analysis/core_business.py`, extend the periods import (near line 27, alongside the existing analytics imports). If no `analytics.periods` import exists yet, add:

```python
from xhs_ceramics_analytics.analytics.periods import to_period_month
```

- [ ] **Step 4: Rewrite `_growth_attribution_finding` (693–766) to aggregate by calendar month**

Replace the body from the `rows = _fetch_all(...)` line through the `p0, p1 = _aggregate(...)` assignment with month bucketing:

```python
    rows = _fetch_all(con, "business_overview_daily")
    by_month: dict[str, dict] = {}
    for r in rows:
        month = to_period_month(r.get("date"))
        if month is None:
            continue
        agg = by_month.setdefault(month, {"gmv": 0.0, "visitors": 0.0, "buyers": 0.0})
        agg["gmv"] += _num(r.get("gmv"))
        agg["visitors"] += _num(r.get("product_visitors"))
        agg["buyers"] += _num(r.get("paid_buyers"))
    months = sorted(by_month)
    if len(months) < 2:
        limitations.append("business_overview_daily 不足两个日历月，跳过增长归因（GMV 桥）。")
        return None, {}
    first_month, last_month = months[0], months[-1]
    p0, p1 = by_month[first_month], by_month[last_month]
    bridge = gmv_bridge(p0, p1)
    bridge_rows = _bridge_rows(bridge)
    factor_zh = bridge.get("dominant_factor_zh")

    caveats = [
        f"按日历月聚合，比较 {first_month} 与 {last_month} 两个整月之间的变化。",
    ]
```

Delete the now-dead `dated`/`mid`/`early`/`late`/`_aggregate` lines and the old `caveats = [...前段/后段...]` assignment. Keep everything from `bridge_method_notes = [...]` onward, but change the `_bridge_conclusion(bridge, p0, p1)` call to pass the month labels: `_bridge_conclusion(bridge, p0, p1, first_month, last_month)`.

- [ ] **Step 5: Update `_BRIDGE_CALIBER` and `_bridge_conclusion` signature (795, 808)**

Replace the caliber constant:

```python
_BRIDGE_CALIBER = "按日历月对比，下面是两个整月之间的变化："
```

Change `_bridge_conclusion` to accept and use the month labels. Update its signature and the head string:

```python
def _bridge_conclusion(
    bridge: dict, p0: dict, p1: dict, first_month: str, last_month: str
) -> str:
    delta = bridge.get("delta_gmv")
    if delta is None:
        return _BRIDGE_CALIBER + "增长归因数据不足，无法分解 ΔGMV。"
    move = "增长" if delta > 0 else ("下滑" if delta < 0 else "持平")
    head = (
        _BRIDGE_CALIBER
        + f"{first_month} 的 GMV {money(p0['gmv'])} 元{move}至 {last_month} 的 "
        + f"{money(p1['gmv'])} 元（Δ {money(delta)} 元）"
    )
```

Leave the rest of `_bridge_conclusion` (the dominant-factor / offsetting-factor branches) unchanged.

- [ ] **Step 6: Run the new test + the existing core-business suite**

Run: `.venv/bin/python -m pytest tests/test_core_business_calendar_bridge.py tests/test_core_business.py -v`
Expected: PASS (new file 3 tests) and no regressions in `test_core_business.py`. If a `test_core_business.py` assertion hardcodes "前段/后段", update that assertion to the calendar-month wording (it is testing the same finding).

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/analysis/core_business.py tests/test_core_business_calendar_bridge.py
git commit -m "fix(core_business): bridge GMV by calendar month, not arbitrary split-half"
```

---

### Task 4: `_line` gains `suppress_aggregate`

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py` — `_line` (356–411)
- Test: `tests/test_charts_suppress_aggregate.py`

**Interfaces:**
- Consumes: existing `_line` internals unchanged.
- Produces: `_line(series, x_labels, *, de_emphasize, suppress_aggregate=False)`. When
  `suppress_aggregate=True`, the bold mean-of-series line (the only `var(--ink-strong)` element) is
  NOT drawn — used for the 剪刀差 hero where a mean of GMV-vs-per-visitor is meaningless.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_charts_suppress_aggregate.py
"""The scissors-gap hero suppresses the meaningless bold mean-of-series line."""
from xhs_ceramics_analytics.reporting import charts


def _series():
    return [
        ("GMV", [100.0, 120.0, 90.0]),
        ("人均产出", [10.0, 8.7, 8.0]),
    ]


def test_aggregate_drawn_by_default():
    svg = charts._line(_series(), ["4月", "5月", "6月"], de_emphasize=False)
    assert "var(--ink-strong)" in svg  # bold mean line present


def test_aggregate_suppressed_when_requested():
    svg = charts._line(
        _series(), ["4月", "5月", "6月"], de_emphasize=False, suppress_aggregate=True
    )
    assert "var(--ink-strong)" not in svg  # no bold mean-of-series line
    assert "var(--muted)" in svg  # the real per-series lines still render
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_charts_suppress_aggregate.py -v`
Expected: FAIL — `_line() got an unexpected keyword argument 'suppress_aggregate'`.

- [ ] **Step 3: Add the parameter and guard the aggregate block**

In `_line` (line 356), add the keyword-only parameter:

```python
def _line(
    series: list[tuple[str, list[float | None]]],
    x_labels: list[str],
    *,
    de_emphasize: bool,
    suppress_aggregate: bool = False,
) -> str:
```

Change the aggregate guard (line 405) from `if len(series) > 1:` to:

```python
    if len(series) > 1 and not suppress_aggregate:  # bold aggregate = mean at each x
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_charts_suppress_aggregate.py tests/test_report_charts.py -v`
Expected: PASS (2 new) and no chart regressions.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py tests/test_charts_suppress_aggregate.py
git commit -m "feat(charts): _line suppress_aggregate for the scissors-gap hero"
```

---

### Task 5: `_waterfall` floating-bar renderer

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/charts.py` (add `_waterfall` after `_vbar`, ~281)
- Test: `tests/test_charts_waterfall.py`

**Interfaces:**
- Consumes: existing `_frame`, `_title`, `_esc`, `_num`, `_empty_state`.
- Produces: `_waterfall(cats, values, value_texts, *, title, de_emphasize) -> str`. Each component
  floats on the running cumulative sum of a whole (top-down stacked descent), so the refund breakdown
  reads as 总额 → 发货前 / 发货后. `None` components are skipped. Empty → framed empty state.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_charts_waterfall.py
"""Refund waterfall — floating bars that descend from the total."""
from xhs_ceramics_analytics.reporting import charts


def test_waterfall_draws_one_rect_per_component():
    svg = charts._waterfall(
        ["发货前", "发货后"],
        [129019.0, 79344.0],
        ["¥12.9万", "¥7.9万"],
        title="退款结构",
        de_emphasize=False,
    )
    assert svg.count("<rect") == 2
    assert "¥12.9万" in svg and "¥7.9万" in svg


def test_second_segment_floats_below_the_first():
    # The second bar's top must sit at the first bar's cumulative height (floating),
    # so its y attribute is strictly greater than the first bar's y.
    svg = charts._waterfall(
        ["发货前", "发货后"], [129019.0, 79344.0], ["a", "b"],
        title="t", de_emphasize=False,
    )
    ys = [float(tok.split('"')[1]) for tok in svg.split("y=")[1:3]]
    assert ys[1] > ys[0]


def test_empty_degrades_to_frame():
    svg = charts._waterfall([], [], [], title="t", de_emphasize=False)
    assert "<svg" in svg  # framed empty state, never raises
    assert "<rect" not in svg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_charts_waterfall.py -v`
Expected: FAIL — `module 'charts' has no attribute '_waterfall'`.

- [ ] **Step 3: Implement `_waterfall`**

Add after `_vbar` (after line 281):

```python
def _waterfall(
    cats: list[str],
    values: list[float | None],
    value_texts: list[str],
    *,
    title: str,
    de_emphasize: bool,
) -> str:
    """Floating-bar waterfall: components stack top-down as a descent from the whole.

    Each segment (发货前 / 发货后 …) is placed at its cumulative base so the bars read
    as slices of one total rather than independent columns. Only computable segments
    are drawn; ``None`` values are skipped. Never raises — empty input frames an
    empty state. Reuses the _vbar geometry and hatch/opacity de-emphasis convention.
    """
    width, height = 308, 300
    pad_t, pad_b, pad_x = 56, 64, 20
    plot_h = height - pad_t - pad_b
    top_y = pad_t
    plotted = [
        (c, v, t) for c, v, t in zip(cats, values, value_texts) if v is not None
    ]
    if not plotted:
        return _frame(_title(title) + _empty_state(width, height), width, height)
    total = sum(v for _, v, _ in plotted) or 1.0
    slot = (width - 2 * pad_x) / len(plotted)
    bw = min(slot * 0.6, 64)
    fill = "url(#ca-hatch)" if de_emphasize else "var(--ink-strong)"
    opacity = "0.55" if de_emphasize else "1"
    body = [_title(title)]
    running = 0.0
    for i, (cat, value, text) in enumerate(plotted):
        cx = pad_x + slot * (i + 0.5)
        seg_h = (value / total) * plot_h
        y = top_y + (running / total) * plot_h  # floats on the cumulative base
        running += value
        body.append(
            f'<rect x="{_num(cx - bw / 2)}" y="{_num(y)}" '
            f'width="{_num(bw)}" height="{_num(seg_h)}" rx="4" fill="{fill}" '
            f'fill-opacity="{opacity}"><title>{_esc(cat)}：{_esc(text)}</title></rect>'
        )
        body.append(
            f'<text x="{_num(cx)}" y="{_num(y + seg_h / 2)}" text-anchor="middle" '
            f'class="ca-num">{_esc(text)}</text>'
        )
        body.append(
            f'<text x="{_num(cx)}" y="{_num(top_y + plot_h + 20)}" text-anchor="middle" '
            f'class="ca-cat">{_esc(cat)}</text>'
        )
    return _frame("".join(body), width, height)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_charts_waterfall.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/charts.py tests/test_charts_waterfall.py
git commit -m "feat(charts): add _waterfall floating-bar renderer for refund breakdown"
```

---

### Task 6: Money primitives (`money.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/money.py`
- Test: `tests/test_reporting_money.py`

**Interfaces:**
- Consumes: `to_finite_float` (from `analytics.numeric`).
- Produces:
  - `per_visitor_gmv(gmv, product_visitors) -> float | None` — efficiency ratio; `None` on non-positive/dirty.
  - `efficiency_ceiling(bridge: dict) -> dict` → `{"ceiling_gmv", "factors", "label"}`; ceiling = sum of
    the magnitudes of the *negative* conversion/AOV contributions (the optimistic recoverable if both
    drags reversed); `label` fixed to `"上限（乐观估计）"`.
  - `preship_recoverable(refund_row: dict) -> dict` → `{"amount", "caliber", "recovery_rate"}`;
    `amount = pre_ship_refund_amount`, `recovery_rate` always `None` (never estimated), `caliber` fixed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_money.py
"""Money primitives — per-visitor efficiency, ceiling counterfactual, pre-ship pool."""
import pytest

from xhs_ceramics_analytics.reporting.money import (
    efficiency_ceiling,
    per_visitor_gmv,
    preship_recoverable,
)


def test_per_visitor_gmv_uses_product_visitors():
    assert per_visitor_gmv(4000.0, 400.0) == pytest.approx(10.0)


def test_per_visitor_gmv_degrades():
    assert per_visitor_gmv(4000.0, 0.0) is None
    assert per_visitor_gmv(4000.0, None) is None
    assert per_visitor_gmv(None, 400.0) is None


def test_efficiency_ceiling_sums_negative_drags():
    bridge = {"contrib_traffic": 30000.0, "contrib_conversion": -28000.0, "contrib_aov": -34000.0}
    ceil = efficiency_ceiling(bridge)
    assert ceil["ceiling_gmv"] == pytest.approx(62000.0)  # |−28k| + |−34k|
    assert set(ceil["factors"]) == {"转化", "客单价"}
    assert ceil["label"] == "上限（乐观估计）"


def test_efficiency_ceiling_ignores_positive_factors():
    bridge = {"contrib_traffic": 30000.0, "contrib_conversion": 5000.0, "contrib_aov": -34000.0}
    ceil = efficiency_ceiling(bridge)
    assert ceil["ceiling_gmv"] == pytest.approx(34000.0)
    assert ceil["factors"] == ["客单价"]


def test_preship_recoverable_never_estimates_recovery_rate():
    pool = preship_recoverable({"pre_ship_refund_amount": 129019.0})
    assert pool["amount"] == pytest.approx(129019.0)
    assert pool["recovery_rate"] is None
    assert "发货前" in pool["caliber"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_money.py -v`
Expected: FAIL — `ModuleNotFoundError: xhs_ceramics_analytics.reporting.money`.

- [ ] **Step 3: Implement `money.py`**

```python
"""Money-sizing primitives — deterministic, caliber-honest, never over-claimed.

All three functions are pure and never raise. They encode the report's money
discipline: efficiency ratios use ``product_visitors`` only; the efficiency
"ceiling" is explicitly an optimistic upper bound (the two negative drags fully
reversed), never a forecast; the pre-ship refund pool is reported as a marginal
sum with NO recovery-rate estimate (the data has no basis for one).
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float

_FACTOR_ZH = {"conversion": "转化", "aov": "客单价"}


def per_visitor_gmv(gmv: object, product_visitors: object) -> float | None:
    """GMV per 商品访客 (the only efficiency caliber). None on non-positive/dirty UV."""
    g = to_finite_float(gmv)
    v = to_finite_float(product_visitors)
    if g is None or v is None or v <= 0:
        return None
    return g / v


def efficiency_ceiling(bridge: dict) -> dict:
    """Optimistic recoverable GMV = |negative conversion drag| + |negative AOV drag|.

    This is the sum of the two efficiency factors' *negative* contributions in the
    LMDI bridge — what GMV would return if both drags were fully reversed. It is an
    upper bound, labelled as such, never a projection.
    """
    total = 0.0
    factors: list[str] = []
    for key, zh in _FACTOR_ZH.items():
        contrib = to_finite_float(bridge.get(f"contrib_{key}"))
        if contrib is not None and contrib < 0:
            total += -contrib
            factors.append(zh)
    return {"ceiling_gmv": total, "factors": factors, "label": "上限（乐观估计）"}


def preship_recoverable(refund_row: dict) -> dict:
    """Pre-ship refund pool as a marginal sum. recovery_rate is ALWAYS None.

    The export has no cancel-reason or timing slice, so any recovery-rate estimate
    would be fabricated — we report the poolsize and explicitly decline to size the
    recoverable fraction.
    """
    amount = to_finite_float(refund_row.get("pre_ship_refund_amount"))
    return {
        "amount": amount,
        "caliber": "发货前退款池（可拦截上限，恢复率未知、不估算）",
        "recovery_rate": None,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_money.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/money.py tests/test_reporting_money.py
git commit -m "feat(reporting): money primitives (per-visitor GMV, ceiling, pre-ship pool)"
```

---

### Task 7: Non-additive ledger (`money_ledger.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/money_ledger.py`
- Test: `tests/test_reporting_money_ledger.py`

**Interfaces:**
- Consumes: `to_finite_float`.
- Produces: `non_additive_ledger(pools: list[dict]) -> dict` where each input pool is
  `{"name": str, "amount": float, "controllability": str}`; returns
  `{"rows": [...sorted by amount desc...], "net_total": None, "banner": "各池口径不同，不可相加为单一净额"}`.
  Pools with a non-finite amount are dropped.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_money_ledger.py
"""Recoverable pools are listed in parallel — never summed into one net total."""
from xhs_ceramics_analytics.reporting.money_ledger import non_additive_ledger


def test_rows_sorted_by_amount_and_no_net_total():
    ledger = non_additive_ledger([
        {"name": "发货前退款", "amount": 129019.0, "controllability": "高"},
        {"name": "误拍退款", "amount": 185851.0, "controllability": "中"},
        {"name": "退货退款", "amount": 57660.0, "controllability": "低"},
    ])
    assert ledger["net_total"] is None
    assert [r["name"] for r in ledger["rows"]] == ["误拍退款", "发货前退款", "退货退款"]
    assert "不可相加" in ledger["banner"]


def test_dirty_amount_dropped():
    ledger = non_additive_ledger([
        {"name": "a", "amount": float("nan"), "controllability": "高"},
        {"name": "b", "amount": 100.0, "controllability": "低"},
    ])
    assert [r["name"] for r in ledger["rows"]] == ["b"]


def test_empty_is_safe():
    ledger = non_additive_ledger([])
    assert ledger["rows"] == []
    assert ledger["net_total"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_money_ledger.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `money_ledger.py`**

```python
"""Non-additive recoverable ledger — parallel pools, deliberately no net total.

Different recoverable pools (发货前退款, 误拍退款, 退货退款 …) overlap and use
incompatible calibers, so summing them into a single "net recoverable" would
double-count with no ground truth for the overlap. This ledger lists them
side by side, sorted by size, with a controllability column and a banner that
states the sum is not meaningful. ``net_total`` is always ``None`` by contract.
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float

_BANNER = "各池口径不同，不可相加为单一净额"


def non_additive_ledger(pools: list[dict]) -> dict:
    """Sort pools by amount desc; drop dirty amounts; never compute a net total."""
    rows = []
    for pool in pools:
        amount = to_finite_float(pool.get("amount"))
        if amount is None:
            continue
        rows.append(
            {
                "name": pool.get("name"),
                "amount": amount,
                "controllability": pool.get("controllability"),
            }
        )
    rows.sort(key=lambda r: r["amount"], reverse=True)
    return {"rows": rows, "net_total": None, "banner": _BANNER}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_money_ledger.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/money_ledger.py tests/test_reporting_money_ledger.py
git commit -m "feat(reporting): non-additive recoverable ledger (no net total)"
```

---

### Task 8: Threshold guardrail bar (`guardrails.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/guardrails.py`
- Test: `tests/test_reporting_guardrails.py`

**Interfaces:**
- Consumes: `to_finite_float`.
- Produces: `threshold_bar(metric_key, observed, hint_line, *, hint_source="政策/经验线，非行业基准") -> dict`
  → `{"metric_key", "observed", "hint_line", "status" ∈ {"above","below","at","not_judgable"}, "hint_source"}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_guardrails.py
"""Threshold hint bar — observed value vs a labelled policy/experience line."""
from xhs_ceramics_analytics.reporting.guardrails import threshold_bar


def test_status_above_below_at():
    assert threshold_bar("refund_rate", 0.18, 0.15)["status"] == "above"
    assert threshold_bar("refund_rate", 0.12, 0.15)["status"] == "below"
    assert threshold_bar("refund_rate", 0.15, 0.15)["status"] == "at"


def test_hint_source_is_labelled_not_a_benchmark():
    bar = threshold_bar("per_visitor_gmv", 8.7, 10.0)
    assert bar["hint_source"] == "政策/经验线，非行业基准"
    assert bar["observed"] == 8.7 and bar["hint_line"] == 10.0


def test_dirty_input_not_judgable():
    assert threshold_bar("x", None, 0.15)["status"] == "not_judgable"
    assert threshold_bar("x", 0.1, float("nan"))["status"] == "not_judgable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_guardrails.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `guardrails.py`**

```python
"""Threshold hint bar — an honest 'you are here vs a hint line' for measured metrics.

The hint line is ALWAYS labelled as a policy/experience line, never an industry
benchmark (the data cannot support cross-shop benchmarking). Only measurement
metrics should be passed in. Never raises.
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float


def threshold_bar(
    metric_key: str,
    observed: object,
    hint_line: object,
    *,
    hint_source: str = "政策/经验线，非行业基准",
) -> dict:
    """Compare an observed measurement to a labelled hint line. Never a benchmark."""
    obs = to_finite_float(observed)
    hint = to_finite_float(hint_line)
    if obs is None or hint is None:
        status = "not_judgable"
    elif obs > hint:
        status = "above"
    elif obs < hint:
        status = "below"
    else:
        status = "at"
    return {
        "metric_key": metric_key,
        "observed": obs,
        "hint_line": hint,
        "status": status,
        "hint_source": hint_source,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_guardrails.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/guardrails.py tests/test_reporting_guardrails.py
git commit -m "feat(reporting): threshold guardrail bar (labelled hint line)"
```

---

### Task 9: Confidence tag routing (`trust_routing.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/trust_routing.py`
- Test: `tests/test_reporting_trust_routing.py`

**Interfaces:**
- Consumes: `EvidenceStrength`, `DescriptiveReliability` (from `evidence`).
- Produces: `confidence_tag(evidence_strength, descriptive_reliability, claim_kind) -> str` returning
  one of `"强"`/`"中"`/`"弱"`. `claim_kind ∈ {"measurement","sizing","mechanism"}`. Mechanism claims are
  ALWAYS `"弱"` (single-window causal cap). This derives the *display* tag; the gate's numeric cap
  (`claim.confidence ≤ max anchor evidence_strength`) is enforced separately in Plan 2.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_trust_routing.py
"""强/中/弱 display tag from the two evidence axes + claim kind."""
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.trust_routing import confidence_tag


def test_mechanism_is_always_weak():
    # Even a "strong-looking" mechanism claim caps at 弱 on single-window data.
    assert confidence_tag(
        EvidenceStrength.STRONG, DescriptiveReliability.HIGH, "mechanism"
    ) == "弱"


def test_high_reliability_measurement_is_strong():
    assert confidence_tag(
        EvidenceStrength.WEAK, DescriptiveReliability.HIGH, "measurement"
    ) == "强"


def test_strong_evidence_measurement_is_strong():
    assert confidence_tag(
        EvidenceStrength.STRONG, DescriptiveReliability.MEDIUM, "sizing"
    ) == "强"


def test_medium_reliability_is_medium():
    assert confidence_tag(
        EvidenceStrength.WEAK, DescriptiveReliability.MEDIUM, "measurement"
    ) == "中"


def test_low_reliability_is_weak():
    assert confidence_tag(
        EvidenceStrength.WEAK, DescriptiveReliability.LOW, "measurement"
    ) == "弱"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_trust_routing.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `trust_routing.py`**

```python
"""Route the two evidence axes + claim kind to a reader-facing 强/中/弱 tag.

The tag CALIBRATES a conclusion — it never suppresses it (bold judgments are the
North Star). A mechanism/causal claim on this single-window, no-control data is
capped at 弱 regardless of how clean the underlying numbers look. Measurement and
sizing claims earn 强 from a strong-evidence or high-descriptive-reliability
anchor, 中 from a medium anchor, else 弱. Pure function, never raises.
"""
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength

_STRONG, _MEDIUM, _WEAK = "强", "中", "弱"


def confidence_tag(
    evidence_strength: EvidenceStrength,
    descriptive_reliability: DescriptiveReliability | None,
    claim_kind: str,
) -> str:
    """Return 强/中/弱. Mechanism claims are always 弱 (single-window causal cap)."""
    if claim_kind == "mechanism":
        return _WEAK
    if (
        evidence_strength == EvidenceStrength.STRONG
        or descriptive_reliability == DescriptiveReliability.HIGH
    ):
        return _STRONG
    if descriptive_reliability == DescriptiveReliability.MEDIUM:
        return _MEDIUM
    return _WEAK
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_trust_routing.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/trust_routing.py tests/test_reporting_trust_routing.py
git commit -m "feat(reporting): 强/中/弱 confidence tag routing"
```

---

### Task 10: FactBook assembly (`facts_export.py`, part 1)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/facts_export.py`
- Test: `tests/test_facts_export_assembly.py`

**Interfaces:**
- Consumes: `AnalysisResult`, `Finding` (from `analysis.result`); `EvidenceStrength`,
  `DescriptiveReliability` (from `evidence`); `to_finite_float`.
- Produces:
  - `Fact` frozen dataclass with fields: `fact_id, value(float|None), rendered(str), metric_key,
    unit, caliber, denominator, evidence_strength, descriptive_reliability, entity_type, direction,
    pool_id=None, assumption=None`.
  - `FactBook` frozen dataclass: `facts(dict[str,Fact]), entity_registry(list[str]),
    non_additive_ledger(dict), absent_link_registry(list[str]), module_reading(dict),
    blocked_modules(list[str]), shared_spine_facts(list[str]), domain_slices(dict)`.
  - `render_cny(value) -> str` — Python-owned 万-notation money string (e.g. `208364 → "¥20.8万"`,
    `4000 → "¥4,000"`); the ONLY money-string source downstream.
  - `build_factbook(results, *, blocked_modules=(), absent_links=(), non_additive=None,
    shared_spine_facts=(), domain_slices=None) -> FactBook` — extracts one `Fact` per numeric
    `key_number` per finding (`fact_id = f"{task_id}.{key}"`, `metric_key=key`), collects entity names
    from `result.named_examples` (`name` field), and `module_reading[task_id] =
    {"conclusion","action","caveats"}` from the first finding.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_facts_export_assembly.py
"""FactBook assembly from AnalysisResult — one Fact per numeric key_number."""
import pytest

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import (
    Fact,
    build_factbook,
    render_cny,
)


def test_render_cny_wan_notation():
    assert render_cny(208364) == "¥20.8万"
    assert render_cny(4000) == "¥4,000"
    assert render_cny(None) == "—"


def _core_result() -> AnalysisResult:
    finding = Finding(
        title="增长归因",
        conclusion="GMV 下滑主要来自客单价。",
        evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=DescriptiveReliability.HIGH,
        key_numbers={"delta_gmv": -29000.0, "dominant_factor": "客单价"},
        recommended_action="回补高价礼盒占比。",
        caveats=["按日历月聚合。"],
    )
    return AnalysisResult(
        task_id="core_business_diagnosis",
        title="整体经营",
        findings=[finding],
        named_examples=[{"name": "兴安岭之夜"}, {"name": "鱼盘"}],
    )


def test_build_extracts_one_fact_per_numeric_key():
    book = build_factbook([_core_result()])
    assert "core_business_diagnosis.delta_gmv" in book.facts
    # Non-numeric key_numbers ("客单价") do not become facts.
    assert "core_business_diagnosis.dominant_factor" not in book.facts
    fact = book.facts["core_business_diagnosis.delta_gmv"]
    assert isinstance(fact, Fact)
    assert fact.value == pytest.approx(-29000.0)
    assert fact.rendered == "-¥2.9万"
    assert fact.evidence_strength == EvidenceStrength.WEAK
    assert fact.descriptive_reliability == DescriptiveReliability.HIGH


def test_build_collects_entity_registry_and_module_reading():
    book = build_factbook([_core_result()])
    assert "兴安岭之夜" in book.entity_registry and "鱼盘" in book.entity_registry
    reading = book.module_reading["core_business_diagnosis"]
    assert reading["conclusion"] == "GMV 下滑主要来自客单价。"
    assert reading["action"] == "回补高价礼盒占比。"
    assert reading["caveats"] == ["按日历月聚合。"]


def test_blocked_and_absent_links_carried():
    book = build_factbook(
        [_core_result()],
        blocked_modules=["paid_traffic_efficiency"],
        absent_links=["note→order", "退款原因"],
    )
    assert book.blocked_modules == ["paid_traffic_efficiency"]
    assert "退款原因" in book.absent_link_registry
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_facts_export_assembly.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `facts_export.py` (assembly half)**

```python
"""facts_export — the single source of every number string in the report.

An ``AnalysisResult`` list is distilled into a ``FactBook``: one immutable ``Fact``
per numeric key_number, plus the registries and ledgers the gate and writer need.
Every money/percent value is pre-rendered here by Python (``rendered``) so the
narrative layer only ever copies a string — it can never round or invent a number.
Raw floats live in ``Fact.value`` for computation but are EXCLUDED from the hash
(see Task 11) so float noise never thrashes the cache. Pure + never raises.
"""
from dataclasses import dataclass, field

from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength


@dataclass(frozen=True)
class Fact:
    fact_id: str
    value: float | None
    rendered: str
    metric_key: str
    unit: str
    caliber: str | None = None
    denominator: str | None = None
    evidence_strength: EvidenceStrength = EvidenceStrength.NOT_JUDGABLE
    descriptive_reliability: DescriptiveReliability | None = None
    entity_type: str | None = None
    direction: str | None = None
    pool_id: str | None = None
    assumption: str | None = None


@dataclass(frozen=True)
class FactBook:
    facts: dict[str, Fact] = field(default_factory=dict)
    entity_registry: list[str] = field(default_factory=list)
    non_additive_ledger: dict = field(default_factory=dict)
    absent_link_registry: list[str] = field(default_factory=list)
    module_reading: dict = field(default_factory=dict)
    blocked_modules: list[str] = field(default_factory=list)
    shared_spine_facts: list[str] = field(default_factory=list)
    domain_slices: dict = field(default_factory=dict)


def render_cny(value: object) -> str:
    """Python-owned money string. ≥1万 → 万-notation (1dp); else grouped yuan."""
    v = to_finite_float(value)
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    mag = abs(v)
    if mag >= 10000:
        return f"{sign}¥{mag / 10000:.1f}万"
    return f"{sign}¥{mag:,.0f}"


def _numeric_facts_from_finding(task_id: str, finding) -> dict[str, Fact]:
    facts: dict[str, Fact] = {}
    for key, raw in finding.key_numbers.items():
        v = to_finite_float(raw)
        if v is None:  # non-numeric (labels like "客单价") are not facts
            continue
        fact_id = f"{task_id}.{key}"
        facts[fact_id] = Fact(
            fact_id=fact_id,
            value=v,
            rendered=render_cny(v),
            metric_key=key,
            unit="cny",
            evidence_strength=finding.evidence_strength,
            descriptive_reliability=finding.descriptive_reliability,
        )
    return facts


def build_factbook(
    results: list[AnalysisResult],
    *,
    blocked_modules: tuple[str, ...] = (),
    absent_links: tuple[str, ...] = (),
    non_additive: dict | None = None,
    shared_spine_facts: tuple[str, ...] = (),
    domain_slices: dict | None = None,
) -> FactBook:
    """Distil analysis results into an immutable FactBook. Never raises."""
    facts: dict[str, Fact] = {}
    entities: list[str] = []
    module_reading: dict = {}
    for result in results:
        for finding in result.findings:
            facts.update(_numeric_facts_from_finding(result.task_id, finding))
        for example in result.named_examples:
            name = example.get("name")
            if name and name not in entities:
                entities.append(str(name))
        if result.findings:
            head = result.findings[0]
            module_reading[result.task_id] = {
                "conclusion": head.conclusion,
                "action": head.recommended_action,
                "caveats": list(head.caveats),
            }
    return FactBook(
        facts=facts,
        entity_registry=entities,
        non_additive_ledger=non_additive or {},
        absent_link_registry=list(absent_links),
        module_reading=module_reading,
        blocked_modules=list(blocked_modules),
        shared_spine_facts=list(shared_spine_facts),
        domain_slices=domain_slices or {},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_facts_export_assembly.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/facts_export.py tests/test_facts_export_assembly.py
git commit -m "feat(reporting): FactBook assembly from AnalysisResult"
```

---

### Task 11: Canonicalization + `facts_hash` (golden-hash gate)

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/facts_export.py` (append canonicalization + hash + JSON)
- Test: `tests/test_facts_hash_golden.py`

**Interfaces:**
- Consumes: `Fact`, `FactBook` (Task 10).
- Produces:
  - `canonical_payload(book: FactBook) -> dict` — a sorted-key dict containing ONLY `rendered` +
    structural/enum fields + registries/ledgers; every raw float `Fact.value` is EXCLUDED.
  - `facts_hash(book: FactBook) -> str` — `sha256` of the canonical payload serialized with
    `sort_keys=True, ensure_ascii=False, separators=(",",":")`.
  - `factbook_to_json(book: FactBook) -> str` — full JSON (INCLUDING `value`) for the narrative layer,
    also deterministic (sorted keys).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_facts_hash_golden.py
"""facts_hash is stable, excludes raw floats, and reacts to rendered/structure."""
from dataclasses import replace

from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.facts_export import (
    Fact,
    FactBook,
    canonical_payload,
    facts_hash,
    factbook_to_json,
)


def _book(value: float, rendered: str) -> FactBook:
    fact = Fact(
        fact_id="core.delta_gmv",
        value=value,
        rendered=rendered,
        metric_key="delta_gmv",
        unit="cny",
        evidence_strength=EvidenceStrength.WEAK,
        descriptive_reliability=DescriptiveReliability.HIGH,
    )
    return FactBook(
        facts={"core.delta_gmv": fact},
        entity_registry=["兴安岭之夜"],
        absent_link_registry=["note→order"],
    )


def test_hash_is_deterministic():
    assert facts_hash(_book(-29000.0, "-¥2.9万")) == facts_hash(_book(-29000.0, "-¥2.9万"))


def test_raw_float_noise_does_not_change_hash():
    # Same rendered string, float jittered → identical hash (the whole point).
    assert facts_hash(_book(-29000.0, "-¥2.9万")) == facts_hash(_book(-29000.0001, "-¥2.9万"))


def test_changed_rendered_string_changes_hash():
    assert facts_hash(_book(-29000.0, "-¥2.9万")) != facts_hash(_book(-29000.0, "-¥3.0万"))


def test_value_excluded_from_canonical_payload():
    payload = canonical_payload(_book(-29000.0, "-¥2.9万"))
    text = repr(payload)
    assert "29000" not in text  # raw float never appears
    assert "-¥2.9万" in text


def test_json_roundtrip_is_sorted_and_includes_value():
    js = factbook_to_json(_book(-29000.0, "-¥2.9万"))
    assert '"value"' in js  # full JSON keeps raw value for computation
    # sorted keys → deterministic ordering
    assert factbook_to_json(_book(-29000.0, "-¥2.9万")) == js


def test_golden_hash_pinned():
    # GOLDEN: run once, copy the printed hash below, and commit it. This is the
    # merge gate — a canonicalization change that moves the hash must be intentional.
    import xhs_ceramics_analytics.reporting.facts_export as fx
    got = facts_hash(_book(-29000.0, "-¥2.9万"))
    print("GOLDEN facts_hash:", got)
    assert got == fx._GOLDEN_TEST_HASH
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_facts_hash_golden.py -v`
Expected: FAIL — `canonical_payload`/`facts_hash`/`factbook_to_json`/`_GOLDEN_TEST_HASH` not defined.

- [ ] **Step 3: Implement canonicalization + hash**

Append to `xhs_ceramics_analytics/reporting/facts_export.py` (add `import hashlib` and `import json` at the top of the file):

```python
# Bump only with an intentional canonicalization change (moves every facts_hash).
CANONICAL_VERSION = 1


def _fact_canonical(fact: Fact) -> dict:
    """Fact fields that define identity for hashing — raw ``value`` deliberately absent."""
    return {
        "fact_id": fact.fact_id,
        "rendered": fact.rendered,
        "metric_key": fact.metric_key,
        "unit": fact.unit,
        "caliber": fact.caliber,
        "denominator": fact.denominator,
        "evidence_strength": str(fact.evidence_strength),
        "descriptive_reliability": (
            str(fact.descriptive_reliability) if fact.descriptive_reliability else None
        ),
        "entity_type": fact.entity_type,
        "direction": fact.direction,
        "pool_id": fact.pool_id,
        "assumption": fact.assumption,
    }


def canonical_payload(book: FactBook) -> dict:
    """Deterministic, float-free view of a FactBook for hashing."""
    return {
        "canonical_version": CANONICAL_VERSION,
        "facts": {fid: _fact_canonical(book.facts[fid]) for fid in sorted(book.facts)},
        "entity_registry": sorted(book.entity_registry),
        "absent_link_registry": sorted(book.absent_link_registry),
        "blocked_modules": sorted(book.blocked_modules),
        "shared_spine_facts": sorted(book.shared_spine_facts),
        "non_additive_ledger": book.non_additive_ledger,
        "domain_slices": book.domain_slices,
    }


def facts_hash(book: FactBook) -> str:
    """sha256 of the canonical (float-excluded) payload. The cache key."""
    blob = json.dumps(
        canonical_payload(book), sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fact_full(fact: Fact) -> dict:
    d = _fact_canonical(fact)
    d["value"] = fact.value  # full JSON keeps the raw value for the narrative layer
    return d


def factbook_to_json(book: FactBook) -> str:
    """Full deterministic JSON (includes raw ``value``) for downstream agents."""
    payload = {
        "facts_hash": facts_hash(book),
        "facts": {fid: _fact_full(book.facts[fid]) for fid in sorted(book.facts)},
        "entity_registry": sorted(book.entity_registry),
        "absent_link_registry": sorted(book.absent_link_registry),
        "module_reading": book.module_reading,
        "blocked_modules": sorted(book.blocked_modules),
        "shared_spine_facts": sorted(book.shared_spine_facts),
        "non_additive_ledger": book.non_additive_ledger,
        "domain_slices": book.domain_slices,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)


# GOLDEN: placeholder; replaced with the real hash in Step 4.
_GOLDEN_TEST_HASH = "PENDING"
```

- [ ] **Step 4: Record the golden hash**

Run the golden test once to print the real hash:

Run: `.venv/bin/python -m pytest tests/test_facts_hash_golden.py::test_golden_hash_pinned -s -v`
Expected: FAIL, but stdout prints `GOLDEN facts_hash: <64-hex>`. Copy that value and replace the last
line of `facts_export.py`:

```python
_GOLDEN_TEST_HASH = "<paste the 64-hex hash printed above>"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_facts_hash_golden.py -v`
Expected: PASS (6 tests).

- [ ] **Step 6: Verify cross-interpreter stability (determinism gate)**

Run: `.venv/bin/python -m pytest tests/test_facts_hash_golden.py::test_hash_is_deterministic tests/test_facts_hash_golden.py::test_raw_float_noise_does_not_change_hash -v`
Expected: PASS — confirms float jitter does not move the hash.

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/reporting/facts_export.py tests/test_facts_hash_golden.py
git commit -m "feat(reporting): facts_hash canonicalization + golden-hash merge gate"
```

---

### Task 12: `xhs-ca facts` CLI subcommand

**Files:**
- Modify: `xhs_ceramics_analytics/cli.py` (add a `facts` command after `run`)
- Test: `tests/test_cli_facts.py`

**Interfaces:**
- Consumes: `build_factbook`, `factbook_to_json`, `facts_hash` (facts_export); `TASKS`, `run_task`
  (registry); `producible_task_ids` (coverage); `outputs_dir`, `state_dir` (paths).
- Produces: a Typer command `facts` that runs the producible task set (or explicit ids), builds a
  `FactBook`, writes `outputs_dir/facts.json`, and echoes the hash. Exit 0 on success.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_facts.py
"""`xhs-ca facts` emits a deterministic facts.json with a hash."""
import json
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.db.build import build_database


def _build_db(tmp_path: Path, fixture_dir: Path) -> None:
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir(parents=True, exist_ok=True)
    build_database(
        db_path=state / "analytics.duckdb",
        files=[
            fixture_dir / "business_overview_daily.csv",
            fixture_dir / "traffic_source.csv",
        ],
    )


def test_facts_command_writes_json_and_hash(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        ["facts", "core_business_diagnosis", "--project-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    facts_json = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "facts.json"
    assert facts_json.exists()
    data = json.loads(facts_json.read_text(encoding="utf-8"))
    assert "facts_hash" in data and len(data["facts_hash"]) == 64
    assert "facts" in data


def test_facts_command_is_deterministic(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    runner = CliRunner()
    runner.invoke(app, ["facts", "core_business_diagnosis", "--project-root", str(tmp_path)])
    first = (tmp_path / ".xhs-ceramics-analytics" / "outputs" / "facts.json").read_text("utf-8")
    runner.invoke(app, ["facts", "core_business_diagnosis", "--project-root", str(tmp_path)])
    second = (tmp_path / ".xhs-ceramics-analytics" / "outputs" / "facts.json").read_text("utf-8")
    assert first == second  # byte-identical re-run
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_facts.py -v`
Expected: FAIL — `facts` command does not exist (Typer exits non-zero / "No such command").

- [ ] **Step 3: Add the `facts` command to `cli.py`**

Add after the `run` command definition (imports inside the function, matching the file's lazy-import style):

```python
@app.command()
def facts(
    tasks: Annotated[
        list[str] | None,
        typer.Argument(help="Task ids, or 'auto' for the producible set. Emits facts.json."),
    ] = None,
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None, typer.Option(help="Override local state/output root.")
    ] = None,
) -> None:
    """Build the deterministic FactBook and write outputs/facts.json (0 agents)."""
    from xhs_ceramics_analytics.analysis.coverage import producible_task_ids
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook,
        facts_hash,
        factbook_to_json,
    )

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    requested = list(tasks) if tasks else ["auto"]
    if requested == ["auto"]:
        task_ids = list(producible_task_ids(db_path))
    elif requested == ["all"]:
        task_ids = list(TASKS)
    else:
        task_ids = [t for t in requested if t in TASKS]
    results = [run_task(task_id, db_path) for task_id in task_ids]
    blocked = tuple(t for t in TASKS if t not in task_ids)
    book = build_factbook(results, blocked_modules=blocked)
    out = outputs_dir(project_root) / "facts.json"
    out.write_text(factbook_to_json(book), encoding="utf-8")
    typer.echo(f"Wrote facts: {out}")
    typer.echo(f"facts_hash: {facts_hash(book)}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_facts.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the full suite to confirm no regressions**

Run: `.venv/bin/python -m pytest -q`
Expected: all previously-green tests still pass; the new tests added across Tasks 1–12 pass.

- [ ] **Step 6: Lint**

Run: `.venv/bin/ruff check xhs_ceramics_analytics/ tests/`
Expected: no errors (line-length 100). Fix any reported issues and re-run.

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/cli.py tests/test_cli_facts.py
git commit -m "feat(cli): add facts subcommand emitting deterministic facts.json"
```

---

## Self-Review

**1. Spec coverage (Plan 1 slice of the spec):**
- `mean_diff_test` (spec §Computed intelligence "日级效率显著性"; §Testing) → Task 1. ✅
- `cumulative_curve` (spec "SKU 帕累托集中度") → Task 2. ✅
- Calendar-month GMV bridge, product_visitors denominator, split-half removed (spec §New/modified files `core_business.py`; §Testing "gmv_bridge calendar-month path residual=0") → Task 3. ✅
- `_line suppress_aggregate` (spec §Format decision (a)) → Task 4. ✅
- `_vbar` waterfall floating bars (spec §Format decision (b)) → Task 5. ✅
- `money.py` per-visitor GMV / efficiency ceiling / pre-ship pool (spec §Computed intelligence rows 1–5) → Task 6. ✅
- `money_ledger.py` non-additive ledger, no net total (spec "非叠加可回收台账"; Change #2) → Task 7. ✅
- `guardrails.py` threshold bar labelled policy/experience line (spec "阈值提示条") → Task 8. ✅
- `trust_routing.py` 强/中/弱 routing, mechanism capped weak (spec §Confidence discipline; "置信标签路由") → Task 9. ✅
- `facts_export.py` Fact/FactBook + registries + module_reading + render (spec [L2] box) → Task 10. ✅
- `facts_hash` canonicalization, raw-float excluded, golden-hash merge gate (spec §Format decision; §Testing) → Task 11. ✅
- `xhs-ca facts` subcommand (spec §New/modified `cli.py`) → Task 12. ✅

**Deferred to Plan 2/3 (explicitly out of this plan):** `factcheck_gate.py`, `narrative_render.py`,
`frozen_narrative.py`, `first_screen.py`, gate/render/finalize/skeleton CLI subcommands, orchestration
assets, `report_writer_workflow.js`, SKILL.md step 7b. The confidence *cap enforcement* (`claim.confidence
≤ max anchor`) is Plan 2 (gate); Task 9 here only derives the display tag. This split is intentional and
noted in Task 9's interface block.

**2. Placeholder scan:** No "TBD"/"implement later". The one deliberate deferred value is
`_GOLDEN_TEST_HASH = "PENDING"`, which Task 11 Step 4 replaces with a recorded hash via an explicit
run-and-copy step (standard golden-master pattern, not a placeholder left in the shipped code).

**3. Type consistency:** `Fact`/`FactBook` field names in Task 10 match their use in Task 11
(`canonical_payload`, `factbook_to_json`) and Task 12 (`book.facts`, `facts_hash(book)`).
`build_factbook` signature (Task 10) matches the call in Task 12. `mean_diff_test`/`cumulative_curve`
return-key names in the impl match the tests. `_line(..., suppress_aggregate=False)` and
`_waterfall(...)` signatures match their tests. `confidence_tag(evidence_strength,
descriptive_reliability, claim_kind)` argument order is consistent between Task 9 impl and test.

