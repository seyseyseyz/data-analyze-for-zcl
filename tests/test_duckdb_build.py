from pathlib import Path

import duckdb
import pandas as pd
import pytest

from xhs_ceramics_analytics.db.build import build_database
from xhs_ceramics_analytics.db.marts import create_note_metrics_view


def test_build_database_creates_standard_tables(tmp_path: Path, fixture_dir: Path):
    db_path = tmp_path / "analytics.duckdb"
    build_database(
        db_path=db_path,
        files=[
            fixture_dir / "notes.csv",
            fixture_dir / "products.csv",
            fixture_dir / "skus.csv",
            fixture_dir / "orders.csv",
            fixture_dir / "content_features.csv",
            fixture_dir / "calendar_events.csv",
            fixture_dir / "comments.csv",
        ],
    )
    con = duckdb.connect(str(db_path))
    try:
        tables = {row[0] for row in con.sql("SHOW TABLES").fetchall()}
        assert {"notes", "products", "skus", "orders", "daily_sku_sales"}.issubset(
            tables
        )
        assert (
            con.sql(
                "SELECT SUM(units) FROM daily_sku_sales WHERE sku_id = 's1'"
            ).fetchone()[0]
            == 7
        )
    finally:
        con.close()


def test_build_database_refresh_removes_stale_controlled_tables(
    tmp_path: Path,
    fixture_dir: Path,
):
    db_path = tmp_path / "analytics.duckdb"
    build_database(
        db_path=db_path,
        files=[
            fixture_dir / "notes.csv",
            fixture_dir / "products.csv",
            fixture_dir / "skus.csv",
            fixture_dir / "orders.csv",
            fixture_dir / "content_features.csv",
            fixture_dir / "calendar_events.csv",
            fixture_dir / "comments.csv",
        ],
    )

    build_database(
        db_path=db_path,
        files=[
            fixture_dir / "notes.csv",
            fixture_dir / "products.csv",
            fixture_dir / "skus.csv",
        ],
    )

    con = duckdb.connect(str(db_path))
    try:
        tables = {row[0] for row in con.sql("SHOW TABLES").fetchall()}
        assert {"notes", "products", "skus"}.issubset(tables)
        assert "orders" not in tables
        assert "daily_sku_sales" not in tables
    finally:
        con.close()


def test_build_database_maps_spaced_order_headers(tmp_path: Path):
    orders_path = tmp_path / "orders_export.csv"
    orders_path.write_text(
        "Order ID,Paid Time,SKU ID,Quantity,Paid Amount\n"
        "o1,2026-06-01 10:00:00,s1,2,258\n"
        "o2,2026-06-01 11:00:00,s1,3,387\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[orders_path])

    con = duckdb.connect(str(db_path))
    try:
        assert (
            con.sql(
                "SELECT SUM(units) FROM daily_sku_sales WHERE sku_id = 's1'"
            ).fetchone()[0]
            == 5
        )
        order_columns = {
            row[1] for row in con.sql("PRAGMA table_info('orders')").fetchall()
        }
        assert {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"}.issubset(
            order_columns
        )
    finally:
        con.close()


def test_build_database_uses_duckdb_columns_for_duplicate_headers(tmp_path: Path):
    orders_path = tmp_path / "orders_export.csv"
    orders_path.write_text(
        "Order ID,Paid Time,SKU ID,Quantity,Paid Amount,Extra,Extra\n"
        "o1,2026-06-01 10:00:00,s1,2,258,first,second\n"
        "o2,2026-06-01 11:00:00,s1,4,516,third,fourth\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[orders_path])

    con = duckdb.connect(str(db_path))
    try:
        assert (
            con.sql(
                "SELECT SUM(units) FROM daily_sku_sales WHERE sku_id = 's1'"
            ).fetchone()[0]
            == 6
        )
        order_columns = {
            row[1] for row in con.sql("PRAGMA table_info('orders')").fetchall()
        }
        assert {"extra", "extra_1"}.issubset(order_columns)
    finally:
        con.close()


def test_build_database_imports_qianfan_order_excel(tmp_path: Path):
    orders_path = tmp_path / "qianfan_orders.xlsx"
    with pd.ExcelWriter(orders_path) as writer:
        pd.DataFrame({"说明": ["汇总页"]}).to_excel(writer, sheet_name="汇总", index=False)
        pd.DataFrame(
            [
                ["导出时间", None, None, None, None],
                ["订单号", "支付时间", "规格ID", "商品数量", "支付金额"],
                ["o1", "2026-06-01 10:00:00", "s1", 2, 258],
                ["o2", "2026-06-01 11:00:00", "s1", 3, 387],
            ]
        ).to_excel(writer, sheet_name="订单明细", index=False, header=False)
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[orders_path])

    con = duckdb.connect(str(db_path))
    try:
        assert (
            con.sql(
                "SELECT SUM(units) FROM daily_sku_sales WHERE sku_id = 's1'"
            ).fetchone()[0]
            == 5
        )
        assert (tmp_path / "staging" / "orders.normalized.csv").exists()
        order_columns = {
            row[1] for row in con.sql("PRAGMA table_info('orders')").fetchall()
        }
        assert {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"}.issubset(
            order_columns
        )
    finally:
        con.close()


def test_build_database_normalizes_order_values_before_loading(tmp_path: Path):
    orders_path = tmp_path / "qianfan_orders.xlsx"
    with pd.ExcelWriter(orders_path) as writer:
        pd.DataFrame(
            [
                ["订单号", "支付时间", "规格ID", "商品数量", "支付金额"],
                ["o1", "2026-06-01 10:00:00", "s1", "1,000", "¥1,298.50"],
                ["o2", "2026-06-01 11:00:00", "s1", "2", "--"],
            ]
        ).to_excel(writer, sheet_name="订单明细", index=False, header=False)
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[orders_path])

    con = duckdb.connect(str(db_path))
    try:
        row = con.sql(
            "SELECT SUM(quantity), SUM(paid_amount) FROM orders WHERE sku_id = 's1'"
        ).fetchone()
        assert row == (1002, pytest.approx(1298.5))
        sales = con.sql(
            "SELECT SUM(units), SUM(gmv) FROM daily_sku_sales WHERE sku_id = 's1'"
        ).fetchone()
        assert sales == (1002, pytest.approx(1298.5))
    finally:
        con.close()


def test_create_daily_sku_sales_excludes_refunded_order_lines(tmp_path: Path):
    orders_path = tmp_path / "orders_export.csv"
    orders_path.write_text(
        "Order ID,Paid Time,SKU ID,Quantity,Paid Amount,Refund Status\n"
        "o1,2026-06-01 10:00:00,s1,2,258,\n"
        "o2,2026-06-01 11:00:00,s1,3,387,refunded\n"
        "o3,2026-06-01 12:00:00,s1,4,516,已退款\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[orders_path])

    con = duckdb.connect(str(db_path))
    try:
        sales = con.sql(
            "SELECT SUM(units), SUM(gmv), SUM(order_count) FROM daily_sku_sales WHERE sku_id = 's1'"
        ).fetchone()
        assert sales == (2, pytest.approx(258), 1)
    finally:
        con.close()


def test_create_note_metrics_view_allows_missing_shares(tmp_path: Path):
    con = duckdb.connect(str(tmp_path / "analytics.duckdb"))
    try:
        con.execute(
            """
            CREATE TABLE notes AS
            SELECT
              'n1' AS note_id,
              100 AS impressions,
              10 AS reads,
              2 AS likes,
              3 AS collects,
              1 AS comments
            """
        )

        create_note_metrics_view(con)

        assert (
            con.sql("SELECT engagement_rate FROM note_metrics").fetchone()[0]
            == pytest.approx(0.6)
        )
    finally:
        con.close()
