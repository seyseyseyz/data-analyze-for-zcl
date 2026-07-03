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
