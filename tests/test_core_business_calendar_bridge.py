"""Period GMV attribution must not sum daily-distinct people."""

from pathlib import Path

import duckdb

from xhs_ceramics_analytics.analysis.core_business import _growth_attribution_finding


def _con_with_two_months(tmp_path: Path):
    db = tmp_path / "t.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        "CREATE TABLE business_overview_daily "
        "(date INTEGER, gmv DOUBLE, paid_buyers DOUBLE, product_visitors DOUBLE)"
    )
    rows = []
    for day in range(1, 16):
        rows.append((20260500 + day, 2000.0, 20.0, 400.0))
    for day in range(1, 16):
        rows.append((20260600 + day, 1700.0, 18.0, 420.0))
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)", rows)
    con.close()
    return db


def test_two_month_daily_distinct_counts_degrade_instead_of_bridging(tmp_path):
    con = duckdb.connect(str(_con_with_two_months(tmp_path)))
    limitations: list[str] = []

    finding, tables = _growth_attribution_finding(con, limitations)

    con.close()
    assert finding is None
    assert tables == {}
    assert any(
        "日级去重" in message and "期间唯一人数" in message and "跳过增长归因" in message
        for message in limitations
    )


def test_bridge_degrades_when_distinct_source_columns_are_missing(tmp_path):
    db = tmp_path / "missing-uv.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE business_overview_daily (date INTEGER, gmv DOUBLE)")
    limitations: list[str] = []

    finding, tables = _growth_attribution_finding(con, limitations)

    con.close()
    assert finding is None
    assert tables == {}
    assert any("缺 product_visitors 或 paid_buyers" in message for message in limitations)
