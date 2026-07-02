# Phase 1a · Plan 2 — Analytic Helpers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a small, pure, fully-unit-tested `analytics/` package — period bucketing (int-`YYYYMMDD` and timestamps), refund/net-GMV arithmetic, month-over-month trends, and honest small-sample confidence (Wilson interval + min-n guard) — that later ingestion marts and Phase-2 analysis tasks build on.

**Architecture:** Four independent modules under `xhs_ceramics_analytics/analytics/`, each < 150 lines, no I/O, no DB, no pandas. Every function is total: bad/insufficient input returns `None` (or a documented sentinel) rather than raising, so callers degrade gracefully. Comparisons speak CI-overlap, never p-values (this is observational platform data).

**Tech Stack:** Python 3.11+ stdlib only (`math`, `calendar`). pytest.

## Global Constraints

- Python **3.11+**; ruff **line-length = 100**. Type annotations on every signature.
- **No timezone conversion.** 千帆 exports are Asia/Shanghai wall-clock; int `YYYYMMDD` carries no tz. Bucket naively.
- `MIN_ORDERS_FOR_RATE = 30` (below it, a rate is not judgable / unranked).
- Division by zero or `None` inputs → return `None` ("分母不足"), never raise.
- No `Co-Authored-By` trailer on commits.
- After source changes, run **sync-runtime** (or defer to Plan 3's final task if executing all of Phase 1a together).

---

### Task 1: `analytics/periods.py` — month bucketing for int-dates and timestamps

**Files:**
- Create: `xhs_ceramics_analytics/analytics/__init__.py` (empty)
- Create: `xhs_ceramics_analytics/analytics/periods.py`
- Test: `tests/test_analytics_periods.py` (create)

**Interfaces:**
- Produces:
  - `to_period_month(value: object) -> str | None` — `20260401` / `"20260401"` / `"2026-04-01 21:11:20"` / `"2026/4/1"` → `"2026-04"`; `None`/unparseable → `None`.
  - `month_bounds(period: str) -> tuple[int, int]` — `"2026-04"` → `(20260401, 20260430)`.
  - `period_month_expr(column: str) -> str` — DuckDB SQL fragment bucketing a date column to a `"YYYY-MM"` string. Handles **both** int `YYYYMMDD` (no separators) **and** ISO date/timestamp columns (`2026-04-01` / `2026-04-01 21:11:20`), per spec §D. Used by Plan 3's monthly mart.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_periods.py
from xhs_ceramics_analytics.analytics.periods import (
    month_bounds,
    period_month_expr,
    to_period_month,
)


def test_to_period_month_from_int_yyyymmdd():
    assert to_period_month(20260401) == "2026-04"
    assert to_period_month("20260430") == "2026-04"


def test_to_period_month_from_timestamp_string():
    assert to_period_month("2026-04-01 21:11:20") == "2026-04"
    assert to_period_month("2026/4/1") == "2026-04"


def test_to_period_month_none_or_garbage_returns_none():
    assert to_period_month(None) is None
    assert to_period_month("not-a-date") is None


def test_month_bounds_handles_month_length():
    assert month_bounds("2026-04") == (20260401, 20260430)
    assert month_bounds("2026-02") == (20260201, 20260228)


def test_period_month_expr_buckets_int_and_timestamp_in_duckdb():
    import duckdb

    expr = period_month_expr("d")
    assert "CASE" in expr  # int (no '-') branch + ISO ('-') branch
    got_int = duckdb.sql(f"SELECT {expr} FROM (SELECT 20260401 AS d)").fetchone()[0]
    assert got_int == "2026-04"
    got_ts = duckdb.sql(
        f"SELECT {expr} FROM (SELECT TIMESTAMP '2026-04-01 21:11:20' AS d)"
    ).fetchone()[0]
    assert got_ts == "2026-04"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_periods.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'xhs_ceramics_analytics.analytics'`.

- [ ] **Step 3: Write the implementation**

Create empty `xhs_ceramics_analytics/analytics/__init__.py`, then:

```python
# xhs_ceramics_analytics/analytics/periods.py
"""Month-period bucketing for 千帆 exports.

Two time representations exist in the real data: int ``YYYYMMDD`` (daily report
tables) and local timestamp strings (``笔记创建时间``). Both bucket to a naive
``YYYY-MM`` string with no timezone math.
"""
import calendar


def to_period_month(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        text = str(value)
    else:
        text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}"
    normalized = text.replace("/", "-")
    parts = normalized.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1][:2].isdigit():
        year = int(parts[0])
        month = int(parts[1][:2])
        if 1 <= month <= 12 and year > 0:
            return f"{year:04d}-{month:02d}"
    return None


def month_bounds(period: str) -> tuple[int, int]:
    year, month = (int(part) for part in period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    start = year * 10000 + month * 100 + 1
    end = year * 10000 + month * 100 + last_day
    return (start, end)


def period_month_expr(column: str) -> str:
    """SQL that buckets a date column to a ``'YYYY-MM'`` string.

    Handles both representations in the export: int ``YYYYMMDD`` (daily report
    tables, no separators) and ISO date/timestamp columns (``2026-04-01`` /
    ``2026-04-01 21:11:20``). Detection is by the presence of a ``-`` separator
    in the text form: ISO forms take the first 7 chars; int forms splice.
    """
    text = f"CAST({column} AS VARCHAR)"
    return (
        f"CASE WHEN strpos({text}, '-') > 0 THEN substr({text}, 1, 7) "
        f"ELSE substr({text}, 1, 4) || '-' || substr({text}, 5, 2) END"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analytics_periods.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/__init__.py xhs_ceramics_analytics/analytics/periods.py tests/test_analytics_periods.py
git commit -m "feat(analytics): period-month bucketing for int-dates and timestamps"
```

---

### Task 2: `analytics/refund_adjust.py` — net GMV and refund rates

**Files:**
- Create: `xhs_ceramics_analytics/analytics/refund_adjust.py`
- Test: `tests/test_analytics_refund_adjust.py` (create)

**Interfaces:**
- Produces:
  - `net_gmv(gmv: float | None, refund_amount: float | None) -> float | None`
  - `refund_rate(refund_amount: float | None, gmv: float | None) -> float | None`
  - `refund_order_rate(refund_orders: float | None, paid_orders: float | None) -> float | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_refund_adjust.py
from xhs_ceramics_analytics.analytics.refund_adjust import (
    net_gmv,
    refund_order_rate,
    refund_rate,
)


def test_net_gmv_subtracts_refund():
    assert net_gmv(1000.0, 150.0) == 850.0


def test_refund_rate_is_amount_over_gmv():
    assert refund_rate(150.0, 1000.0) == 0.15


def test_refund_order_rate():
    assert refund_order_rate(3, 20) == 0.15


def test_none_or_zero_denominator_returns_none():
    assert net_gmv(None, 10.0) is None
    assert refund_rate(10.0, 0) is None
    assert refund_rate(10.0, None) is None
    assert refund_order_rate(3, 0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_refund_adjust.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# xhs_ceramics_analytics/analytics/refund_adjust.py
"""Refund-adjusted GMV and refund rates.

Used mainly as a cross-check: the 千帆 platform already ships ``net_gmv_pay``
(退款后支付金额) and ``refund_rate_pay`` (退款率（支付时间）) per SKU/day.
"""


def net_gmv(gmv: float | None, refund_amount: float | None) -> float | None:
    if gmv is None or refund_amount is None:
        return None
    return gmv - refund_amount


def refund_rate(refund_amount: float | None, gmv: float | None) -> float | None:
    if refund_amount is None or not gmv:
        return None
    return refund_amount / gmv


def refund_order_rate(
    refund_orders: float | None, paid_orders: float | None
) -> float | None:
    if refund_orders is None or not paid_orders:
        return None
    return refund_orders / paid_orders
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analytics_refund_adjust.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/refund_adjust.py tests/test_analytics_refund_adjust.py
git commit -m "feat(analytics): net-GMV and refund-rate helpers with safe denominators"
```

---

### Task 3: `analytics/trends.py` — pct-change and month-over-month deltas

**Files:**
- Create: `xhs_ceramics_analytics/analytics/trends.py`
- Test: `tests/test_analytics_trends.py` (create)

**Interfaces:**
- Produces:
  - `pct_change(old: float | None, new: float | None) -> float | None`
  - `direction_label(delta: float | None) -> str` — `"上升"` / `"下降"` / `"持平"` (`|delta|` under `1e-9` → 持平; `None` → 持平).
  - `mom_change(series: list[tuple[str, float]]) -> list[dict]` — series of `(period, value)` sorted ascending → per-period `{"period", "value", "delta", "pct", "direction"}` (first period has `delta=None, pct=None, direction="持平"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_trends.py
from xhs_ceramics_analytics.analytics.trends import direction_label, mom_change, pct_change


def test_pct_change():
    assert pct_change(100.0, 120.0) == 0.2
    assert pct_change(0, 5.0) is None
    assert pct_change(None, 5.0) is None


def test_direction_label():
    assert direction_label(0.2) == "上升"
    assert direction_label(-0.2) == "下降"
    assert direction_label(0.0) == "持平"
    assert direction_label(None) == "持平"


def test_mom_change_builds_per_period_deltas():
    rows = mom_change([("2026-04", 100.0), ("2026-05", 120.0), ("2026-06", 90.0)])
    assert rows[0] == {
        "period": "2026-04", "value": 100.0, "delta": None, "pct": None, "direction": "持平"
    }
    assert rows[1]["delta"] == 20.0
    assert rows[1]["pct"] == 0.2
    assert rows[1]["direction"] == "上升"
    assert rows[2]["direction"] == "下降"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_trends.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# xhs_ceramics_analytics/analytics/trends.py
"""Month-over-month trend helpers (observational; report direction, not p-values)."""

_EPS = 1e-9


def pct_change(old: float | None, new: float | None) -> float | None:
    if new is None or not old:
        return None
    return (new - old) / old


def direction_label(delta: float | None) -> str:
    if delta is None or abs(delta) < _EPS:
        return "持平"
    return "上升" if delta > 0 else "下降"


def mom_change(series: list[tuple[str, float]]) -> list[dict]:
    rows: list[dict] = []
    previous: float | None = None
    for period, value in series:
        delta = None if previous is None else value - previous
        pct = None if previous is None else pct_change(previous, value)
        rows.append(
            {
                "period": period,
                "value": value,
                "delta": delta,
                "pct": pct,
                "direction": direction_label(delta),
            }
        )
        previous = value
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analytics_trends.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/trends.py tests/test_analytics_trends.py
git commit -m "feat(analytics): pct-change and month-over-month trend helpers"
```

---

### Task 4: `analytics/confidence.py` — Wilson interval + small-sample guard

**Files:**
- Create: `xhs_ceramics_analytics/analytics/confidence.py`
- Test: `tests/test_analytics_confidence.py` (create)

**Interfaces:**
- Produces:
  - `MIN_ORDERS_FOR_RATE = 30`
  - `wilson_interval(k: float, n: float, z: float = 1.96) -> tuple[float, float]` — `(lo, hi)` clamped to `[0, 1]`; `n <= 0` → `(0.0, 0.0)`.
  - `min_n_guard(n: float | None) -> bool` — `True` iff `n` is not `None` and `n >= MIN_ORDERS_FOR_RATE`.
  - `rate_band(lo: float, hi: float) -> str` — plain-language band, e.g. `"约 24%–76%"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analytics_confidence.py
import pytest

from xhs_ceramics_analytics.analytics.confidence import (
    MIN_ORDERS_FOR_RATE,
    min_n_guard,
    rate_band,
    wilson_interval,
)


def test_wilson_known_value():
    lo, hi = wilson_interval(5, 10)
    assert lo == pytest.approx(0.2366, abs=0.001)
    assert hi == pytest.approx(0.7634, abs=0.001)


def test_wilson_clamps_and_handles_zero_n():
    assert wilson_interval(0, 0) == (0.0, 0.0)
    lo, hi = wilson_interval(0, 5)
    assert lo == 0.0 and 0.0 < hi < 1.0


def test_min_n_guard():
    assert min_n_guard(MIN_ORDERS_FOR_RATE) is True
    assert min_n_guard(29) is False
    assert min_n_guard(None) is False


def test_rate_band_reads_as_percent_range():
    assert rate_band(0.2366, 0.7634) == "约 24%–76%"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_analytics_confidence.py -v`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

```python
# xhs_ceramics_analytics/analytics/confidence.py
"""Honest small-sample confidence for observed rates.

Feeds ``evidence.py`` rather than duplicating its enum. Below
``MIN_ORDERS_FOR_RATE`` a rate is not judgable and should be left unranked.
"""
import math

MIN_ORDERS_FOR_RATE = 30


def wilson_interval(k: float, n: float, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (0.0, 0.0)
    p = k / n
    denom = 1 + z**2 / n
    center = (p + z**2 / (2 * n)) / denom
    margin = (z / denom) * math.sqrt(p * (1 - p) / n + z**2 / (4 * n**2))
    return (max(0.0, center - margin), min(1.0, center + margin))


def min_n_guard(n: float | None) -> bool:
    return n is not None and n >= MIN_ORDERS_FOR_RATE


def rate_band(lo: float, hi: float) -> str:
    return f"约 {round(lo * 100)}%–{round(hi * 100)}%"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_analytics_confidence.py -v && pytest -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/analytics/confidence.py tests/test_analytics_confidence.py
git commit -m "feat(analytics): Wilson interval, min-n guard, plain-language rate band"
```

---

## Self-Review (run after all tasks)

1. **Spec coverage (Section D):** `periods.py` (int-YYYYMMDD & timestamp, no tz shift, `period_month_expr`) → Task 1. `refund_adjust.py` (net_gmv/refund_rate/refund_order_rate, None on ÷0) → Task 2. `trends.py` (pct_change/mom_change/direction_label) → Task 3. `confidence.py` (wilson_interval/min_n_guard/rate_band + `MIN_ORDERS_FOR_RATE`) → Task 4. ✅
   - Spec §D says `period_month_expr` handles **both int `YYYYMMDD` and date/timestamp**. Task 1 satisfies this two ways: the Python `to_period_month` normalizes both int and timestamp strings, and the SQL `period_month_expr` uses a `CASE` on the `-` separator so DuckDB buckets int columns (daily marts) and TIMESTAMP columns (`笔记创建时间`) alike — proven by `test_period_month_expr_buckets_int_and_timestamp_in_duckdb`.
2. **Placeholder scan:** none — every function fully implemented.
3. **Type consistency:** `to_period_month`/`month_bounds`/`period_month_expr`, `net_gmv`/`refund_rate`/`refund_order_rate`, `pct_change`/`mom_change`/`direction_label`, `wilson_interval`/`min_n_guard`/`rate_band` used with identical names/signatures wherever Plan 3 consumes them (`period_month_expr` in the monthly mart).
4. **Purity:** no module imports pandas/duckdb/os; safe for direct unit testing.
