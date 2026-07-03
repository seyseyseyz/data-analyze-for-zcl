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
          "笔记支付买家数" DOUBLE,
          "商卡支付买家数" DOUBLE,
          "笔记商品访客数" DOUBLE,
          "商卡商品访客数" DOUBLE,
          "笔记退款后支付金额_支付时间" DOUBLE,
          "商卡退款后支付金额_支付时间" DOUBLE,
          "笔记客单价" DOUBLE,
          "商卡客单价" DOUBLE,
          "笔记退款订单数_支付时间" DOUBLE,
          "商卡退款订单数_支付时间" DOUBLE,
          "笔记退款率_支付时间" DOUBLE,
          "商卡退款率_支付时间" DOUBLE,
          "笔记发货前退款率_支付时间" DOUBLE,
          "商卡发货前退款率_支付时间" DOUBLE,
          "笔记发货后退款率_支付时间" DOUBLE,
          "商卡发货后退款率_支付时间" DOUBLE
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
            300.0, 600.0,  # note_gmv, card_gmv
            10.0, 20.0,  # note_paid_orders, card_paid_orders
            10.0, 20.0,  # 笔记支付买家数, 商卡支付买家数
            200.0, 250.0,  # 笔记商品访客数, 商卡商品访客数
            280.0, 580.0,  # 笔记退款后支付金额_支付时间, 商卡退款后支付金额_支付时间
            30.0, 30.0,  # 笔记客单价, 商卡客单价
            2.0, 1.0,  # 笔记退款订单数_支付时间, 商卡退款订单数_支付时间
            0.20, 0.05,  # 笔记退款率_支付时间, 商卡退款率_支付时间
            0.15, 0.03,  # 笔记发货前退款率_支付时间, 商卡发货前退款率_支付时间
            0.05, 0.02,  # 笔记发货后退款率_支付时间, 商卡发货后退款率_支付时间
        ),
        (
            20260602,
            250.0, 550.0,
            8.0, 18.0,
            8.0, 18.0,
            180.0, 230.0,
            230.0, 530.0,
            31.0, 30.5,
            1.0, 1.0,
            0.18, 0.06,
            0.14, 0.04,
            0.04, 0.02,
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
        assert any("观察性" in c for c in f.caveats)


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


# ---- Real DB smoke check ------------------------------------------------


def test_real_db_smoke():
    if not os.path.exists(REAL_DB_PATH):
        pytest.skip(f"real DB not available at {REAL_DB_PATH}")
    result = channel_structure_diagnosis.run(Path(REAL_DB_PATH))
    assert len(result.findings) == 3
    scale = next(f for f in result.findings if f.title == "渠道收入与规模对比")
    assert scale.key_numbers["dominant_carrier"] == "card"
