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


def test_missing_required_column_is_diagnosed_not_silent(tmp_path):
    # Purpose-built business_overview_daily WITHOUT 退款后支付金额（支付时间） (net_gmv_pay).
    # The golden fixture carries it, so we hand-build a degraded export here.
    export = tmp_path / "business_overview_daily.csv"
    export.write_text(
        "时间,支付金额,支付订单数,支付买家数,客单价,支付件数,退款金额（支付时间）\n"
        "20260401,1000,10,8,125,30,100\n",
        encoding="utf-8",
    )
    db = tmp_path / "d.duckdb"
    build_database(db, [export])  # must not raise
    con = duckdb.connect(str(db))
    diag_rows = con.execute(
        "SELECT required_column, status FROM mapping_diagnostics "
        "WHERE table_name = 'business_overview_daily'"
    ).fetchall()
    monthly_exists = "business_overview_monthly" in {
        row[0] for row in con.execute("SHOW TABLES").fetchall()
    }
    con.close()
    required_flagged = {row[0] for row in diag_rows}
    assert "net_gmv_pay" in required_flagged  # explicit, not a silent slug
    assert monthly_exists  # degrade-not-reject: the mart still builds


def test_golden_full_export_has_empty_mapping_diagnostics(fixture_dir, tmp_path):
    files = [fixture_dir / name for name, _ in _ALL]
    db = tmp_path / "d.duckdb"
    build_database(db, files)
    con = duckdb.connect(str(db))
    count = con.execute("SELECT count(*) FROM mapping_diagnostics").fetchone()[0]
    con.close()
    assert count == 0  # every Required column maps on the golden happy path
