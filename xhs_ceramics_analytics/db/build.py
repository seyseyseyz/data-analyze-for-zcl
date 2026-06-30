from pathlib import Path

from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.importing.mapping import guess_table_type
from xhs_ceramics_analytics.importing.profile import profile_csv


def build_database(db_path: Path, files: list[Path]) -> None:
    con = connect(db_path)
    for file in files:
        profile = profile_csv(file)
        table_type = guess_table_type(profile)
        con.execute(
            f"CREATE OR REPLACE TABLE {table_type} AS SELECT * FROM read_csv_auto(?)",
            [str(file)],
        )
    create_daily_sku_sales(con)


def create_daily_sku_sales(con) -> None:
    existing = {row[0] for row in con.sql("SHOW TABLES").fetchall()}
    if "orders" not in existing:
        return
    con.execute(
        """
        CREATE OR REPLACE TABLE daily_sku_sales AS
        SELECT
          CAST(paid_time AS DATE) AS date,
          sku_id,
          SUM(CAST(quantity AS DOUBLE)) AS units,
          SUM(CAST(paid_amount AS DOUBLE)) AS gmv,
          COUNT(DISTINCT order_id) AS order_count
        FROM orders
        WHERE paid_time IS NOT NULL AND sku_id IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )
