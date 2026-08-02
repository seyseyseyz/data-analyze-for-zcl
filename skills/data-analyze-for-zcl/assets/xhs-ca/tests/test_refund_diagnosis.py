from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "refund.duckdb"
    return connect(db_path), db_path


def _make_refund_overview(con, rows):
    con.execute(
        """
        CREATE TABLE refund_overview (
          carrier VARCHAR,
          refund_amount_pay DOUBLE,
          pre_ship_refund_amount DOUBLE,
          post_ship_refund_amount DOUBLE,
          return_refund_amount DOUBLE,
          refund_orders_pay DOUBLE,
          refund_rate_pay DOUBLE,
          refund_users DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO refund_overview VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _make_refund_overview_full_grain(con, rows):
    con.execute(
        """
        CREATE TABLE refund_overview (
          stat_period VARCHAR,
          account_name VARCHAR,
          carrier VARCHAR,
          refund_amount_pay DOUBLE,
          pre_ship_refund_amount DOUBLE,
          post_ship_refund_amount DOUBLE,
          shipped_refundonly_amount DOUBLE,
          return_refund_amount DOUBLE,
          refund_orders_pay DOUBLE,
          post_ship_refund_orders DOUBLE,
          shipped_refundonly_orders DOUBLE,
          pre_ship_refund_orders DOUBLE,
          return_refund_orders DOUBLE,
          refund_rate_pay DOUBLE,
          post_ship_refund_rate_pay DOUBLE,
          pre_ship_refund_rate_pay DOUBLE,
          return_refund_rate_pay DOUBLE,
          refund_users DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO refund_overview VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def test_missing_refund_overview_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert result.task_id == "refund_structure_diagnosis"
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "refund_overview" in result.limitations[0]


def test_layer_finding_identifies_dominant_ship_stage_not_return(tmp_path):
    con, db_path = _con(tmp_path)
    # pre=3000, post=5000 (ship-stage axis, sum 8000); return=10000 is on the
    # return-type axis and must NOT win the ship-stage dominance comparison.
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    layer = result.tables["refund_layer_breakdown"]
    finding = result.findings[0]
    kn = finding.key_numbers
    # dominant is the largest SHIP-STAGE layer (post_ship 5000 > pre_ship 3000),
    # never 退货退款 (a different axis).
    assert kn["dominant_layer"] == "post_ship"
    assert kn["dominant_share"] == 5000.0 / 8000.0  # denominator is ship-stage total
    assert {r["layer"] for r in layer} == {"pre_ship", "post_ship", "return"}
    axis = {r["layer"]: r["axis"] for r in layer}
    assert axis == {"pre_ship": "ship_stage", "post_ship": "ship_stage", "return": "return_type"}
    # ship-stage shares partition to 100%; return is measured against total refund
    ship_shares = sum(r["share"] for r in layer if r["axis"] == "ship_stage")
    assert abs(ship_shares - 1.0) < 1e-9
    # caveat spells out that 退货退款 is not additive with the ship-stage split
    assert any("退货退款" in c and "不" in c for c in finding.caveats)
    # cross-reference caveat naming the other refund modules' calibers
    assert any("退款根因诊断" in c and "渠道结构与健康诊断" in c for c in finding.caveats)
    assert finding.recommended_action  # lever text present
    assert finding.evidence_strength.value == "weak"


def test_carrier_finding_compares_two_carriers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 300.0, 0.30, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 50.0, 0.05, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    assert "载体退款率对比" in titles
    comp = result.tables["carrier_refund_comparison"]
    assert {r["carrier"] for r in comp} == {"笔记", "商卡"}
    finding = next(f for f in result.findings if f.title == "载体退款率对比")
    assert finding.key_numbers["carrier_high"] == "笔记"
    assert finding.key_numbers["significant"] is True


def test_refund_overview_preserves_grain_and_emits_available_stage_metrics(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview_full_grain(
        con,
        [
            (
                "2026-Q2",
                "账号A",
                "笔记",
                1000.0,
                400.0,
                600.0,
                200.0,
                400.0,
                100.0,
                60.0,
                20.0,
                40.0,
                40.0,
                0.10,
                0.06,
                0.04,
                0.04,
                90.0,
            ),
            (
                "2026-Q2",
                "账号A",
                "商卡",
                500.0,
                300.0,
                200.0,
                80.0,
                120.0,
                50.0,
                20.0,
                8.0,
                30.0,
                12.0,
                0.05,
                0.02,
                0.03,
                0.012,
                45.0,
            ),
        ],
    )
    con.close()

    result = run_task("refund_structure_diagnosis", db_path)
    grain_rows = result.tables["refund_overview_by_period_account_carrier"]
    assert len(grain_rows) == 2
    assert {
        tuple(r[k] for k in ("stat_period", "account_name", "carrier")) for r in grain_rows
    } == {
        ("2026-Q2", "账号A", "笔记"),
        ("2026-Q2", "账号A", "商卡"),
    }
    layers = {r["layer"]: r for r in result.tables["refund_layer_breakdown"]}
    assert layers["pre_ship"]["refund_amount"] == 700.0
    assert layers["pre_ship"]["refund_orders"] == 70.0
    assert layers["pre_ship"]["refund_rate"] == 70.0 / 2000.0
    assert layers["post_ship"]["refund_orders"] == 80.0
    assert layers["shipped_refundonly"]["refund_amount"] == 280.0
    assert layers["shipped_refundonly"]["refund_orders"] == 28.0
    assert sum(r["refund_users"] for r in grain_rows) == 135.0


def test_refund_overview_does_not_add_distinct_stat_periods(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview_full_grain(
        con,
        [
            (
                "2026-H1",
                "账号A",
                "笔记",
                1000.0,
                400.0,
                600.0,
                200.0,
                400.0,
                100.0,
                60.0,
                20.0,
                40.0,
                40.0,
                0.10,
                0.06,
                0.04,
                0.04,
                90.0,
            ),
            (
                "2026-Q2",
                "账号A",
                "商卡",
                500.0,
                300.0,
                200.0,
                80.0,
                120.0,
                50.0,
                20.0,
                8.0,
                30.0,
                12.0,
                0.05,
                0.02,
                0.03,
                0.012,
                45.0,
            ),
        ],
    )
    con.close()

    result = run_task("refund_structure_diagnosis", db_path)

    assert result.tables["refund_layer_breakdown"] == []
    assert "carrier_refund_comparison" not in result.tables
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert any("多个统计周期" in limitation for limitation in result.limitations)


def test_carrier_comparison_aggregates_duplicate_carrier_rows_within_one_period(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview_full_grain(
        con,
        [
            (
                "2026-Q2",
                "账号A",
                "笔记",
                600.0,
                240.0,
                360.0,
                120.0,
                240.0,
                60.0,
                36.0,
                12.0,
                24.0,
                24.0,
                0.12,
                0.072,
                0.048,
                0.048,
                54.0,
            ),
            (
                "2026-Q2",
                "账号B",
                "笔记",
                400.0,
                160.0,
                240.0,
                80.0,
                160.0,
                40.0,
                24.0,
                8.0,
                16.0,
                16.0,
                0.08,
                0.048,
                0.032,
                0.032,
                36.0,
            ),
            (
                "2026-Q2",
                "账号A",
                "商卡",
                500.0,
                300.0,
                200.0,
                80.0,
                120.0,
                50.0,
                20.0,
                8.0,
                30.0,
                12.0,
                0.05,
                0.02,
                0.03,
                0.012,
                45.0,
            ),
        ],
    )
    con.close()

    result = run_task("refund_structure_diagnosis", db_path)
    rows = result.tables["carrier_refund_comparison"]

    assert len(rows) == 2
    by_carrier = {r["carrier"]: r for r in rows}
    assert by_carrier["笔记"]["refund_orders"] == 100.0
    assert by_carrier["笔记"]["n"] == 1000.0
    assert by_carrier["笔记"]["refund_rate"] == 0.1


def test_carrier_refund_rate_uses_only_rows_with_rate_and_orders(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con,
        [
            ("笔记", 1000.0, 400.0, 600.0, 300.0, 10.0, 0.10, 9.0),
            ("笔记", 9000.0, 4000.0, 5000.0, 3000.0, 90.0, None, 80.0),
            ("商卡", 1000.0, 500.0, 500.0, 200.0, 5.0, 0.05, 5.0),
        ],
    )
    con.close()

    result = run_task("refund_structure_diagnosis", db_path)
    rows = {row["carrier"]: row for row in result.tables["carrier_refund_comparison"]}
    assert rows["笔记"]["refund_rate"] == 0.10
    assert rows["笔记"]["refund_orders"] == 10
    assert rows["笔记"]["rate_coverage_rows"] == 1
    assert rows["笔记"]["missing_rate_rows"] == 1


def test_carrier_finding_skipped_for_single_carrier(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0)])
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "载体退款率对比" not in [f.title for f in result.findings]
    assert any("载体" in lim for lim in result.limitations)


def _make_business_overview(con, rows):
    con.execute("CREATE TABLE business_overview_daily (date DATE, refund_rate_pay DOUBLE)")
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?)", rows)


def test_trend_finding_reports_direction(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0),
        ],
    )
    _make_business_overview(con, [("2026-04-30", 0.05), ("2026-05-31", 0.08), ("2026-06-30", 0.12)])
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "退款率时间趋势")
    assert finding.key_numbers["trend_direction"] == "上升"
    assert len(result.tables["refund_trend"]) == 3


def test_trend_finding_skipped_without_business_overview(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "退款率时间趋势" not in [f.title for f in result.findings]
    assert any("business_overview_daily" in lim for lim in result.limitations)


def _make_notes(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR, title VARCHAR,
          note_refund_rate_pay DOUBLE, note_paid_orders DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO notes VALUES (?, ?, ?, ?)", rows)


def _make_content_features(con, rows):
    con.execute(
        """
        CREATE TABLE content_features (
          note_id VARCHAR, composition_type VARCHAR,
          scene_hint VARCHAR, copy_angle VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO content_features VALUES (?, ?, ?, ?)", rows)


def _refund_overview_two(con):
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0),
        ],
    )


def test_note_finding_flags_high_refund_and_feature(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    # two clearly high-refund notes share composition 'flatlay'; low-refund notes differ
    _make_notes(
        con,
        [
            ("n1", "高退款A", 0.40, 100.0),
            ("n2", "高退款B", 0.38, 100.0),
            ("n3", "低退款C", 0.03, 100.0),
            ("n4", "低退款D", 0.02, 100.0),
        ],
    )
    _make_content_features(
        con,
        [
            ("n1", "flatlay", "kitchen", "price"),
            ("n2", "flatlay", "studio", "quality"),
            ("n3", "closeup", "kitchen", "story"),
            ("n4", "closeup", "outdoor", "story"),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "笔记退款反思")
    assert finding.key_numbers["high_refund_note_count"] >= 1
    ids = {r["note_id"] for r in result.tables["high_refund_notes"]}
    assert {"n1", "n2"} <= ids


def test_note_finding_degrades_without_content_features(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_notes(con, [("n1", "高退款A", 0.40, 100.0), ("n2", "低退款B", 0.02, 100.0)])
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "笔记退款反思")
    assert finding.key_numbers["top_feature"] is None
    assert any("特征" in c for c in finding.caveats)


def test_refund_reason_breakdown_uses_manual_reason_table(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    con.execute(
        "CREATE TABLE refund_reasons (refund_reason VARCHAR, refund_amount DOUBLE, refund_orders DOUBLE)"
    )
    con.executemany(
        "INSERT INTO refund_reasons VALUES (?, ?, ?)",
        [("尺寸不符", 1200, 8), ("破损", 800, 4), ("尺寸不符", 300, 2)],
    )
    con.close()

    result = run_task("refund_structure_diagnosis", db_path)
    rows = result.tables["refund_reason_breakdown"]
    assert rows[0]["refund_reason"] == "尺寸不符"
    assert rows[0]["refund_amount"] == 1500
    assert rows[0]["refund_orders"] == 10
    assert rows[0]["amount_share"] == 1500 / 2300
    assert any(f.title == "退款原因结构" for f in result.findings)


def _make_sku_performance(con, rows):
    con.execute(
        """
        CREATE TABLE sku_performance (
          product_id VARCHAR, product_name VARCHAR,
          gmv DOUBLE, net_gmv_pay DOUBLE,
          refund_rate_pay DOUBLE, refund_orders_pay DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO sku_performance VALUES (?, ?, ?, ?, ?, ?)", rows)


def _make_products(con, rows):
    con.execute(
        """
        CREATE TABLE products (
          product_id VARCHAR, vessel_type VARCHAR,
          series VARCHAR, category VARCHAR, price_band VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO products VALUES (?, ?, ?, ?, ?)", rows)


def test_product_finding_flags_high_refund_and_feature(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_sku_performance(
        con,
        [
            ("p1", "青釉杯", 10000.0, 6000.0, 0.40, 100.0),
            ("p2", "白瓷盘", 9000.0, 5500.0, 0.39, 100.0),
            ("p3", "茶壶", 8000.0, 7800.0, 0.02, 100.0),
        ],
    )
    _make_products(
        con,
        [
            ("p1", "杯", "青釉", "杯具", "50-100"),
            ("p2", "盘", "青釉", "盘具", "50-100"),
            ("p3", "壶", "白瓷", "壶具", "100-200"),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "产品退款反思")
    ids = {r["product_id"] for r in result.tables["product_refund_concentration"]}
    assert {"p1", "p2", "p3"} == ids
    assert finding.key_numbers["high_refund_product_count"] >= 1
    assert finding.key_numbers["top_feature"] is not None


def test_product_finding_degrades_without_products(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_sku_performance(
        con,
        [
            ("p1", "青釉杯", 10000.0, 6000.0, 0.40, 100.0),
            ("p2", "茶壶", 8000.0, 7800.0, 0.02, 100.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "产品退款反思")
    assert finding.key_numbers["top_feature"] is None
    assert any("特征" in c for c in finding.caveats)


def test_product_finding_skipped_without_sku_performance(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "产品退款反思" not in [f.title for f in result.findings]
    assert any("sku_performance" in lim for lim in result.limitations)
