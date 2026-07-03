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
    # required canonical columns must survive to the built table, not linger as
    # un-canonicalized Chinese slugs (e.g. refund_users from 退款人数（支付时间）)
    refund_cols = {row[0] for row in con.execute("DESCRIBE refund_overview").fetchall()}
    con.close()
    for _, table_type in _ALL:
        assert table_type in tables
    assert "refund_users" in refund_cols


@pytest.mark.parametrize("count", [0, 1, 3, 9])
def test_run_all_succeeds_on_any_subset(fixture_dir, tmp_path, count):
    files = [fixture_dir / name for name, _ in _ALL[:count]]
    db = tmp_path / f"d{count}.duckdb"
    build_database(db, files)  # must never raise on any subset
    con = duckdb.connect(str(db))
    assert con.execute("SELECT count(*) FROM needs_data").fetchone()[0] == 0
    con.close()
