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


def test_pareto_reports_gini_and_hhi_single_values(tmp_path):
    con, db_path = _con(tmp_path)
    # 12 SKUs with a steep GMV gradient → concentrated → gini well above 0.
    rows = [
        (
            f"sku_{i:02d}", f"陶瓷杯-{i:02d}", "prod_1", "陶瓷杯系列", False,
            "杯具", "马克杯", "自有品牌",
            100.0 + i * 5, 20000.0 - i * 1200.0, 40.0 + i, 50.0 + i, 55.0 + i,
            300.0 + i * 20, 5.0 + i * 1.5, 2.0 + i * 0.5, 2.0, 3.0 + i * 0.5,
            (20000.0 - i * 1200.0) * 0.9,
        )
        for i in range(12)
    ]
    _make_full_table(con, rows)
    con.close()
    result = run(db_path)
    pareto = next(f for f in result.findings if "集中度" in f.title)
    kn = pareto.key_numbers
    assert kn["gmv_gini"] is not None and 0.0 < kn["gmv_gini"] < 1.0
    assert kn["gmv_hhi"] is not None and 0.0 < kn["gmv_hhi"] <= 1.0
    # 基尼系数是方法学术语，商家可读的 conclusion 里不出现；细节搬进 evidence_reason。
    assert "基尼" not in pareto.conclusion
    assert "基尼" in pareto.evidence_reason


def test_price_band_distribution_uses_shared_caliber(tmp_path):
    con, db_path = _con(tmp_path)
    # 12 SKUs spread across a wide AOV range → 4 quantile price bands.
    rows = [
        (
            f"sku_{i:02d}", f"陶瓷杯-{i:02d}", "prod_1", "陶瓷杯系列", False,
            "杯具", "马克杯", "自有品牌",
            100.0 + i * 5, 2000.0 + i * 800.0, 40.0 + i, 50.0 + i, 55.0 + i,
            50.0 + i * 60.0, 5.0, 2.0, 2.0, 3.0,
            (2000.0 + i * 800.0) * 0.9,
        )
        for i in range(12)
    ]
    _make_full_table(con, rows)
    con.close()
    result = run(db_path)

    band = next(f for f in result.findings if f.title == "价格带分布（SKU × GMV）")
    assert band.key_numbers["band_count"] == 4
    band_rows = result.tables["sku_price_band_distribution"]
    assert len(band_rows) == 4
    # Shares are proper proportions that sum to ~1 across the four bands.
    assert abs(sum(r["gmv_share"] for r in band_rows) - 1.0) < 1e-9
    assert abs(sum(r["sku_share"] for r in band_rows) - 1.0) < 1e-9
    assert sum(r["sku_count"] for r in band_rows) == 12
    # Every band carries its AOV window + the shared band label vocabulary.
    assert band_rows[0]["band"] == "低价位"
    assert all(r["aov_low"] is not None for r in band_rows)


def test_price_band_distribution_degrades_without_aov(tmp_path):
    con, db_path = _con(tmp_path)
    _make_partial_table(con, [(f"sku_{i}", 1000.0 * (i + 1)) for i in range(6)])
    con.close()
    result = run(db_path)
    titles = {f.title for f in result.findings}
    assert "价格带分布（SKU × GMV）" not in titles
    assert any("aov" in lim for lim in result.limitations)


# ---- Price sweet spot (price band × conversion × refund) --------------------


def test_price_sweet_spot_flags_high_conversion_low_refund_band(tmp_path):
    con, db_path = _con(tmp_path)
    # 12 SKUs across 4 AOV quartile bands. The top band (i=9,10,11) converts far
    # better (0.60 vs 0.20) at a much lower refund (0.05 vs 0.20) → the sweet spot.
    rows = []
    for i in range(12):
        top = i >= 9
        rows.append(
            (
                f"sku_{i:02d}", f"陶瓷杯-{i:02d}", "prod_1", "陶瓷杯系列", False,
                "杯具", "马克杯", "自有品牌",
                100.0,                       # add_to_cart_users
                5000.0,                      # gmv
                60.0 if top else 20.0,       # paid_buyers → conversion
                70.0 if top else 25.0,       # paid_orders
                30.0,                        # paid_units
                50.0 + i * 60.0,             # aov → price band
                0.05 if top else 0.20,       # refund_rate_pay
                3.5 if top else 5.0,         # refund_orders_pay → refund rate
                2.0, 3.0,
                4500.0,
            )
        )
    _make_full_table(con, rows)
    con.close()
    result = run(db_path)

    finding = next(
        f for f in result.findings if f.title == "价格甜点（价格带 × 转化 × 退款）"
    )
    assert finding.key_numbers["sweet_spot_band"] == "高价位"
    rows_t = result.tables["sku_price_sweet_spot"]
    assert len(rows_t) == 4
    top_row = next(r for r in rows_t if r["band"] == "高价位")
    assert top_row["is_sweet_spot"] is True
    assert top_row["net_margin"] > 0.4
    # low band converts below overall and refunds above → not a sweet spot
    low_row = next(r for r in rows_t if r["band"] == "低价位")
    assert low_row["is_sweet_spot"] is False


def test_price_sweet_spot_degrades_without_refund_column(tmp_path):
    con, db_path = _con(tmp_path)
    # sku_performance with price + conversion but no refund columns → three-dim
    # table not computable, finding skipped with a limitation.
    con.execute(
        """
        CREATE TABLE sku_performance (
          sku_name VARCHAR, aov DOUBLE,
          add_to_cart_users DOUBLE, paid_buyers DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO sku_performance VALUES (?, ?, ?, ?)",
        [(f"sku_{i}", 100.0 + i * 50, 100.0, 30.0) for i in range(6)],
    )
    con.close()
    result = run(db_path)
    titles = {f.title for f in result.findings}
    assert "价格甜点（价格带 × 转化 × 退款）" not in titles
    assert any("价格甜点" in lim for lim in result.limitations)


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


# ---- L2 category drill-down (revenue vs refund) -----------------------------


def _sku_l2(sku_id, l2, gmv, orders, refund_orders, rate):
    return (
        sku_id, f"name_{sku_id}", "p", "prod", False, "陶瓷", l2, "brand",
        100.0, gmv, orders, orders, orders, 100.0,
        rate, refund_orders, 0.0, 0.0, gmv * 0.9,
    )


def test_l2_drilldown_separates_high_revenue_from_high_refund(tmp_path):
    con, db_path = _con(tmp_path)
    # 餐具: 800k GMV @ 5% refund (high revenue, healthy).
    # 陶瓶: 200k GMV @ 20% refund (low revenue, refund hotspot).
    rows = [
        _sku_l2("a1", "餐具", 400000.0, 1000.0, 50.0, 0.05),
        _sku_l2("a2", "餐具", 300000.0, 800.0, 40.0, 0.05),
        _sku_l2("a3", "餐具", 100000.0, 200.0, 10.0, 0.05),
        _sku_l2("b1", "陶瓶", 100000.0, 500.0, 100.0, 0.20),
        _sku_l2("b2", "陶瓶", 60000.0, 300.0, 60.0, 0.20),
        _sku_l2("b3", "陶瓶", 40000.0, 200.0, 40.0, 0.20),
    ]
    _make_full_table(con, rows)
    con.close()

    result = run(db_path)

    l2 = next(f for f in result.findings if f.title == "二级品类结构（营收 vs 退款）")
    kn = l2.key_numbers
    assert kn["top_gmv_category_l2"] == "餐具"
    assert abs(kn["top_gmv_category_l2_share"] - 0.8) < 1e-9
    # The refund hotspot is a DIFFERENT L2 than the revenue leader — the whole point.
    assert kn["top_refund_category_l2"] == "陶瓶"
    assert abs(kn["top_refund_category_l2_rate"] - 0.20) < 1e-9
    assert kn["category_l2_count"] == 2

    table = result.tables["sku_category_l2_mix"]
    assert [r["category_l2"] for r in table] == ["餐具", "陶瓶"]
    top = table[0]
    assert abs(top["gmv"] - 800000.0) < 1e-9
    assert abs(top["gmv_share"] - 0.8) < 1e-9
    assert abs(top["refund_rate"] - 0.05) < 1e-9


def test_l2_drilldown_degrades_when_column_absent(tmp_path):
    con, db_path = _con(tmp_path)
    # Table with gmv but NO category_l2 column → L2 finding degrades away silently.
    con.execute("CREATE TABLE sku_performance (sku_name VARCHAR, gmv DOUBLE)")
    con.executemany(
        "INSERT INTO sku_performance VALUES (?, ?)",
        [(f"sku_{i}", 1000.0 * (i + 1)) for i in range(5)],
    )
    con.close()

    result = run(db_path)
    assert "二级品类结构（营收 vs 退款）" not in {f.title for f in result.findings}
    assert "sku_category_l2_mix" not in result.tables
