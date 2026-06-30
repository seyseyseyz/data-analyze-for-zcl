from pathlib import Path

import duckdb

from xhs_ceramics_analytics.db.build import build_database


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
    tables = {row[0] for row in con.sql("SHOW TABLES").fetchall()}
    assert {"notes", "products", "skus", "orders", "daily_sku_sales"}.issubset(tables)
    assert con.sql("SELECT SUM(units) FROM daily_sku_sales WHERE sku_id = 's1'").fetchone()[0] == 7
