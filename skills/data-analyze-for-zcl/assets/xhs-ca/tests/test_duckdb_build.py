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


def test_build_database_imports_paid_traffic_export(tmp_path: Path, fixture_dir: Path):
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[fixture_dir / "ads_campaign.csv"])

    con = duckdb.connect(str(db_path))
    try:
        tables = {row[0] for row in con.sql("SHOW TABLES").fetchall()}
        assert "ad_performance_daily" in tables
        assert "ad_metrics" in tables
        row = con.sql(
            """
            SELECT
              SUM(spend),
              SUM(impressions),
              SUM(clicks),
              SUM(gmv_optional),
              MAX(extra_field)
            FROM ad_performance_daily
            """
        ).fetchone()
        assert row == (200, 10000, 260, 880, "keep-me-too")
    finally:
        con.close()


def test_ad_metrics_calculates_null_safe_paid_rates(tmp_path: Path, fixture_dir: Path):
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path=db_path, files=[fixture_dir / "ads_campaign.csv"])

    con = duckdb.connect(str(db_path))
    try:
        row = con.sql(
            """
            SELECT ctr_calc, cpc_calc, cpm_calc, cost_per_order_calc, roas_calc
            FROM ad_metrics
            WHERE campaign_name_optional = '青釉杯投放'
              AND date = '2026-06-01'
            """
        ).fetchone()
        assert row[0] == pytest.approx(0.03)
        assert row[1] == pytest.approx(120 / 180)
        assert row[2] == pytest.approx(20)
        assert row[3] == pytest.approx(20)
        assert row[4] == pytest.approx(6)
    finally:
        con.close()


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
