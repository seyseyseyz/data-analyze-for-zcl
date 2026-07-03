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


# ---- Refund outlier FDR control (D2) ----------------------------------------


def _sku(i, orders, rate, refund_orders):
    return (
        f"sku_{i}", f"name_{i}", "p", "prod", False, "杯具", "马克杯", "brand",
        100.0, 5000.0, orders, orders, orders, 100.0,
        rate, refund_orders, 0.0, 0.0, 4500.0,
    )


def test_refund_fdr_flags_only_strong_outliers(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [_sku(i, 100.0, 0.10, 10.0) for i in range(10)]  # baseline drivers
    rows.append(_sku(100, 200.0, 0.50, 100.0))  # genuinely high refund
    rows.append(_sku(101, 15.0, 0.20, 3.0))     # borderline, tiny sample
    _make_full_table(con, rows)
    con.close()

    result = run(db_path)
    refund = next(f for f in result.findings if f.title == "高退款 SKU 识别")
    kn = refund.key_numbers
    assert "fdr_survivors" in kn
    assert "expected_false_positives" in kn
    outliers = result.tables["sku_refund_outliers"]
    strong = next(r for r in outliers if r["sku_name"] == "name_100")
    assert strong["fdr_significant"] is True
    borderline = next(r for r in outliers if r["sku_name"] == "name_101")
    assert borderline["fdr_significant"] is False
    assert kn["fdr_survivors"] == 1


# ---- Conversion universe reconciliation (#12) -------------------------------


def _sku_universe(sku_id, cart, gmv, buyers):
    return (
        sku_id, f"name_{sku_id}", "p", "prod", False, "杯具", "马克杯", "brand",
        cart, gmv, buyers, buyers, buyers, 100.0,
        0.05, 1.0, 0.0, 0.0, gmv * 0.9,
    )


def test_conversion_universe_reconciles_with_gmv_universe(tmp_path):
    con, db_path = _con(tmp_path)
    # cart>0 universe = {s1, s2} (2); gmv>0 universe = {s1, s3, s4} (3).
    _make_full_table(
        con,
        [
            _sku_universe("s1", cart=10.0, gmv=1000.0, buyers=5.0),
            _sku_universe("s2", cart=8.0, gmv=0.0, buyers=0.0),   # cart, no gmv
            _sku_universe("s3", cart=0.0, gmv=500.0, buyers=3.0),  # gmv, no cart
            _sku_universe("s4", cart=0.0, gmv=300.0, buyers=2.0),  # gmv, no cart
        ],
    )
    con.close()

    result = run(db_path)
    conv = next(f for f in result.findings if f.title == "加购转化与客单价结构")
    assert conv.key_numbers["conversion_universe"] == 2
    assert conv.key_numbers["gmv_universe"] == 3
    # a caveat names both filters so the two SKU counts are reconciled explicitly
    assert any(
        "加购人数>0" in c and "GMV>0" in c and "2" in c and "3" in c
        for c in conv.caveats
    )


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
