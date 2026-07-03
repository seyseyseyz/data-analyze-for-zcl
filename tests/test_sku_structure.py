from pathlib import Path

from xhs_ceramics_analytics.analysis.sku_structure import run
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "sku.duckdb"
    return connect(db_path), db_path


def _make_full_table(con, rows):
    con.execute(
        """
        CREATE TABLE sku_performance (
          sku_id VARCHAR,
          sku_name VARCHAR,
          product_id VARCHAR,
          product_name VARCHAR,
          is_channel_product BOOLEAN,
          category_l1 VARCHAR,
          category_l2 VARCHAR,
          brand VARCHAR,
          add_to_cart_users DOUBLE,
          gmv DOUBLE,
          paid_buyers DOUBLE,
          paid_orders DOUBLE,
          paid_units DOUBLE,
          aov DOUBLE,
          refund_rate_pay DOUBLE,
          refund_orders_pay DOUBLE,
          pre_ship_refund_rate_pay DOUBLE,
          post_ship_refund_rate_pay DOUBLE,
          net_gmv_pay DOUBLE
        )
        """
    )
    if rows:
        con.executemany(
            """
            INSERT INTO sku_performance VALUES
            (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def _make_partial_table(con, rows):
    con.execute(
        """
        CREATE TABLE sku_performance (
          sku_name VARCHAR,
          gmv DOUBLE
        )
        """
    )
    if rows:
        con.executemany("INSERT INTO sku_performance VALUES (?, ?)", rows)


# ---- Required table missing -------------------------------------------------


def test_missing_sku_table_degrades_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run(db_path)
    assert result.task_id == "sku_structure_diagnosis"
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "sku_performance" in result.limitations[0]


# ---- Full columns produce WEAK observational findings -----------------------


def test_full_sku_rows_produce_weak_findings(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [
        (
            f"sku_{i:02d}",
            f"陶瓷杯-{i:02d}",
            "prod_1",
            "陶瓷杯系列",
            False,
            "杯具" if i % 3 else "餐盘",
            "马克杯",
            "自有品牌",
            100.0 + i * 5,
            20000.0 - i * 1200.0,
            40.0 + i,
            50.0 + i,
            55.0 + i,
            300.0 + i * 20,
            5.0 + i * 1.5,
            2.0 + i * 0.5,
            2.0,
            3.0 + i * 0.5,
            (20000.0 - i * 1200.0) * 0.9,
        )
        for i in range(12)
    ]
    _make_full_table(con, rows)
    con.close()

    result = run(db_path)

    assert result.findings
    finding1 = next(f for f in result.findings if "集中度" in f.title)
    assert finding1.evidence_strength.value == "weak"
    assert result.tables["sku_gmv_pareto"]

    other_titles = {f.title for f in result.findings}
    assert ("高退款 SKU 识别" in other_titles) or ("加购转化与客单价结构" in other_titles)


# ---- Partial columns gate out refund/conversion findings ---------------------


def test_partial_columns_skip_gated_findings(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [(f"sku_{i:02d}", 1000.0 * (i + 1)) for i in range(5)]
    _make_partial_table(con, rows)
    con.close()

    result = run(db_path)

    titles = {f.title for f in result.findings}
    assert any("集中度" in t for t in titles)
    assert "高退款 SKU 识别" not in titles
    assert "加购转化与客单价结构" not in titles
    assert result.limitations
    finding1 = next(f for f in result.findings if "集中度" in f.title)
    assert finding1.evidence_strength.value == "weak"
