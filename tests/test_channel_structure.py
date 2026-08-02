import os
from pathlib import Path

import pytest

from xhs_ceramics_analytics.analysis import channel_structure_diagnosis
from xhs_ceramics_analytics.db.duck import connect

TASK = "channel_structure_diagnosis"

REAL_DB_PATH = "/tmp/xhs-real-run/analytics.duckdb"


def _con(tmp_path: Path):
    db_path = tmp_path / "channel.duckdb"
    return connect(db_path), db_path


def _make_full(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date BIGINT,
          note_gmv DOUBLE,
          card_gmv DOUBLE,
          note_paid_orders DOUBLE,
          card_paid_orders DOUBLE,
          note_paid_buyers DOUBLE,
          card_paid_buyers DOUBLE,
          note_product_visitors DOUBLE,
          card_product_visitors DOUBLE,
          note_net_gmv_pay DOUBLE,
          card_net_gmv_pay DOUBLE,
          note_aov DOUBLE,
          card_aov DOUBLE,
          note_refund_orders_pay DOUBLE,
          card_refund_orders_pay DOUBLE,
          note_refund_rate_pay DOUBLE,
          card_refund_rate_pay DOUBLE,
          note_pre_ship_refund_rate_pay DOUBLE,
          card_pre_ship_refund_rate_pay DOUBLE,
          note_post_ship_refund_rate_pay DOUBLE,
          card_post_ship_refund_rate_pay DOUBLE
        )
        """
    )
    if rows:
        placeholders = ", ".join(["?"] * 21)
        con.executemany(f"INSERT INTO business_overview_daily VALUES ({placeholders})", rows)


def _make_gmv_only(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date BIGINT,
          note_gmv DOUBLE,
          card_gmv DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?)", rows)


def _make_no_gmv(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date BIGINT,
          paid_orders DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?)", rows)


# ---- Required table missing -------------------------------------------------


def test_missing_business_overview_daily_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = channel_structure_diagnosis.run(db_path)
    assert result.task_id == TASK
    assert result.title == channel_structure_diagnosis.TITLE
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "business_overview_daily" in result.limitations[0]


# ---- Full fixture: all 3 findings emitted -----------------------------------


def test_full_fixture_emits_all_findings(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [
        (
            20260601,
            300.0,
            600.0,  # note_gmv, card_gmv
            10.0,
            20.0,  # note_paid_orders, card_paid_orders
            10.0,
            20.0,  # note_paid_buyers, card_paid_buyers
            200.0,
            250.0,  # note_product_visitors, card_product_visitors
            280.0,
            580.0,  # note_net_gmv_pay, card_net_gmv_pay
            30.0,
            30.0,  # note_aov, card_aov
            2.0,
            1.0,  # note_refund_orders_pay, card_refund_orders_pay
            0.20,
            0.05,  # note_refund_rate_pay, card_refund_rate_pay
            0.15,
            0.03,  # note_pre_ship_refund_rate_pay, card_pre_ship_refund_rate_pay
            0.05,
            0.02,  # note_post_ship_refund_rate_pay, card_post_ship_refund_rate_pay
        ),
        (
            20260602,
            250.0,
            550.0,
            8.0,
            18.0,
            8.0,
            18.0,
            180.0,
            230.0,
            230.0,
            530.0,
            31.0,
            30.5,
            1.0,
            1.0,
            0.18,
            0.06,
            0.14,
            0.04,
            0.04,
            0.02,
        ),
    ]
    _make_full(con, rows)
    con.close()

    result = channel_structure_diagnosis.run(db_path)
    assert result.task_id == TASK
    assert len(result.findings) == 3

    scale = next(f for f in result.findings if f.title == "渠道收入与规模对比")
    assert scale.key_numbers["dominant_carrier"] == "card"
    assert scale.evidence_strength.value == "weak"
    assert scale.confounders

    conv = next(f for f in result.findings if f.title == "渠道转化与客单对比")
    assert conv.key_numbers["conversion_source"] == "count"
    assert conv.key_numbers["note_conversion"] is not None
    assert conv.key_numbers["card_conversion"] is not None
    assert conv.key_numbers["conv_diff"] is not None

    refund = next(f for f in result.findings if f.title == "渠道退款健康")
    assert refund.key_numbers["note_refund_rate"] is not None
    assert refund.key_numbers["card_refund_rate"] is not None
    assert refund.key_numbers["refund_diff"] is not None
    assert refund.key_numbers["higher_refund_carrier"] == "note"

    for f in result.findings:
        assert f.confounders
        assert any("这不是因果关系" in c for c in f.caveats)


# ---- Missing note_gmv/card_gmv -> Finding 1 NOT_JUDGABLE --------------------


def test_missing_gmv_columns_makes_scale_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    _make_no_gmv(con, [(20260601, 5.0)])
    con.close()
    result = channel_structure_diagnosis.run(db_path)
    scale = next(f for f in result.findings if f.title == "渠道收入与规模对比")
    assert scale.evidence_strength.value == "not_judgable"
    assert result.tables["channel_scale"] == []
    assert any("note_gmv" in lim or "card_gmv" in lim for lim in result.limitations)


# ---- Empty DB (table absent) -> _missing_result -----------------------------


def test_empty_db_never_raises(tmp_path):
    db_path = tmp_path / "does_not_exist.duckdb"
    result = channel_structure_diagnosis.run(db_path)
    assert result.task_id == TASK
    assert result.title == channel_structure_diagnosis.TITLE
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"


# ---- Only gmv columns present -> Findings 2 & 3 skipped ---------------------


def test_gmv_only_skips_conversion_and_refund(tmp_path):
    con, db_path = _con(tmp_path)
    _make_gmv_only(
        con,
        [
            (20260601, 300.0, 600.0),
            (20260602, 250.0, 550.0),
        ],
    )
    con.close()
    result = channel_structure_diagnosis.run(db_path)
    titles = {f.title for f in result.findings}
    assert "渠道收入与规模对比" in titles
    assert "渠道转化与客单对比" not in titles
    assert "渠道退款健康" not in titles
    assert any("转化" in lim for lim in result.limitations)
    assert any("退款" in lim for lim in result.limitations)


# ---- Never raises on empty rows ---------------------------------------------


def test_empty_rows_do_not_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_full(con, [])
    con.close()
    result = channel_structure_diagnosis.run(db_path)
    assert any(f.title == "渠道收入与规模对比" for f in result.findings)


def test_channel_daily_fact_and_traffic_source_matrix(tmp_path):
    con, db_path = _con(tmp_path)
    _make_full(
        con,
        [
            (
                20260601,
                300.0,
                600.0,
                10.0,
                20.0,
                10.0,
                20.0,
                200.0,
                250.0,
                280.0,
                580.0,
                30.0,
                30.0,
                2.0,
                1.0,
                0.20,
                0.05,
                0.15,
                0.03,
                0.05,
                0.02,
            )
        ],
    )
    con.execute(
        """
        CREATE TABLE traffic_source (
          xhs_id VARCHAR,
          account_name VARCHAR,
          channel VARCHAR,
          note_type VARCHAR,
          gmv DOUBLE,
          paid_orders DOUBLE,
          paid_buyers DOUBLE,
          product_clicks DOUBLE,
          product_click_users DOUBLE,
          pay_conversion_pv DOUBLE,
          pay_conversion_uv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO traffic_source VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("x1", "店铺", "搜索", "图文", 500, 10, 8, 200, 100, 0.05, 0.08),
            ("x1", "店铺", "搜索", "图文", 300, 5, 4, 100, 50, 0.05, 0.08),
        ],
    )
    con.close()

    result = channel_structure_diagnosis.run(db_path)

    daily = result.tables["carrier_daily_fact"]
    source = result.tables["traffic_source_efficiency"][0]
    assert len(daily) == 2
    note = next(row for row in daily if row["carrier"] == "note")
    assert note["date"] == "2026-06-01"
    assert note["pay_conversion"] == pytest.approx(0.05)
    assert note["refund_rate"] == pytest.approx(0.2)
    assert source["channel"] == "搜索"
    assert source["gmv"] == 800
    assert source["uv_pay_conversion_calc"] == pytest.approx(12 / 150)
    assert source["pv_pay_conversion_reported"] == pytest.approx(0.05)
    assert source["gmv_per_buyer"] == pytest.approx(800 / 12)
    assert any(f.title == "流量来源与内容类型效率" for f in result.findings)


# ---- Real DB smoke check ------------------------------------------------


def test_real_db_smoke():
    if not os.path.exists(REAL_DB_PATH):
        pytest.skip(f"real DB not available at {REAL_DB_PATH}")
    result = channel_structure_diagnosis.run(Path(REAL_DB_PATH))
    assert len(result.findings) == 3
    scale = next(f for f in result.findings if f.title == "渠道收入与规模对比")
    assert scale.key_numbers["dominant_carrier"] == "card"
