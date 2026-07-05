import os
from pathlib import Path

import pytest

from xhs_ceramics_analytics.analysis.refund_root_cause_diagnosis import run
from xhs_ceramics_analytics.db.duck import connect

REAL_DB_PATH = "/tmp/xhs-real-run/analytics.duckdb"


def _con(tmp_path: Path):
    db_path = tmp_path / "refund.duckdb"
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


def _make_gmv_only_table(con, rows):
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


def _make_business_overview_daily(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date BIGINT,
          pre_ship_refund_rate_pay DOUBLE,
          post_ship_refund_rate_pay DOUBLE,
          refund_rate_pay DOUBLE,
          refund_orders_pay DOUBLE,
          paid_orders DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?, ?, ?, ?, ?, ?)", rows
    )


def _build_category_price_rows():
    """8 noise categories at baseline refund rate + 1 genuinely high-refund
    category, spread across a wide AOV range for price-band quantiles."""
    rows = []
    noise_categories = [f"品类{c}" for c in "ABCDEFGH"]
    counter = 0
    for cat in noise_categories:
        for j in range(5):
            counter += 1
            rows.append(
                (
                    f"sku_{counter:03d}",
                    f"{cat}-sku{j}",
                    f"prod_{counter}",
                    f"{cat}产品",
                    False,
                    cat,
                    f"{cat}_l2",
                    "自有品牌",
                    10.0,
                    5000.0,
                    36.0,
                    40.0,
                    44.0,
                    100.0 + counter * 20,
                    2.0 / 40.0,  # refund_rate_pay ~ 5%
                    2.0,  # refund_orders_pay
                    0.10,  # pre_ship_refund_rate_pay
                    0.03,  # post_ship_refund_rate_pay
                    4500.0,
                )
            )
    high_cat = "问题品类"
    for j in range(5):
        counter += 1
        rows.append(
            (
                f"sku_{counter:03d}",
                f"{high_cat}-sku{j}",
                f"prod_{counter}",
                f"{high_cat}产品",
                False,
                high_cat,
                f"{high_cat}_l2",
                "自有品牌",
                10.0,
                5000.0,
                28.0,
                40.0,
                44.0,
                100.0 + counter * 20,
                12.0 / 40.0,  # refund_rate_pay ~ 30%
                12.0,  # refund_orders_pay
                0.10,
                0.03,
                3500.0,
            )
        )
    return rows


# ---- Required table missing -------------------------------------------------


def test_missing_sku_table_degrades_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run(db_path)
    assert result.task_id == "refund_root_cause_diagnosis"
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "sku_performance" in result.limitations[0]


# ---- Full fixture -----------------------------------------------------------


def test_full_fixture_produces_three_findings(tmp_path):
    con, db_path = _con(tmp_path)
    _make_full_table(con, _build_category_price_rows())
    con.close()

    result = run(db_path)

    assert len(result.findings) == 3
    titles = {f.title for f in result.findings}
    assert titles == {"发货前后退款分解", "品类退款分解", "价格带退款分解"}

    ship = next(f for f in result.findings if f.title == "发货前后退款分解")
    assert ship.key_numbers["dominant_stage"] == "pre_ship"
    assert ship.key_numbers["source"] == "sku_performance"
    assert ship.evidence_strength.value == "weak"
    assert ship.confounders
    assert any("这不是因果关系" in c for c in ship.caveats)

    category = next(f for f in result.findings if f.title == "品类退款分解")
    assert category.key_numbers["top_category"] == "问题品类"
    assert category.key_numbers["fdr_significant_count"] == 1
    assert category.evidence_strength.value == "weak"
    cat_rows = result.tables["refund_by_category"]
    sig_categories = {r["category_l1"] for r in cat_rows if r["fdr_significant"]}
    assert sig_categories == {"问题品类"}

    price = next(f for f in result.findings if f.title == "价格带退款分解")
    assert price.key_numbers["band_count"] == 4
    band_rows = result.tables["refund_by_price_band"]
    assert len(band_rows) == 4
    assert price.evidence_strength.value == "weak"


# ---- Only gmv column: everything degrades gracefully ------------------------


def test_gmv_only_table_degrades_all_findings(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [(f"sku_{i:02d}", 1000.0 * (i + 1)) for i in range(6)]
    _make_gmv_only_table(con, rows)
    con.close()

    result = run(db_path)

    ship = next(f for f in result.findings if f.title == "发货前后退款分解")
    assert ship.evidence_strength.value == "not_judgable"
    assert ship.key_numbers["dominant_stage"] is None

    titles = {f.title for f in result.findings}
    assert "品类退款分解" not in titles
    assert "价格带退款分解" not in titles
    assert any("category_l1" in lim for lim in result.limitations)
    assert any("aov" in lim for lim in result.limitations)


# ---- business_overview_daily preferred for ship-stage source ---------------


def test_business_overview_daily_preferred_source(tmp_path):
    con, db_path = _con(tmp_path)
    # sku_performance lacks ship-stage columns entirely.
    _make_gmv_only_table(con, [(f"sku_{i:02d}", 1000.0) for i in range(4)])
    _make_business_overview_daily(
        con,
        [
            (20260601, 0.12, 0.05, 0.17, 34.0, 200.0),
            (20260602, 0.10, 0.06, 0.16, 32.0, 200.0),
        ],
    )
    con.close()

    result = run(db_path)
    ship = next(f for f in result.findings if f.title == "发货前后退款分解")
    assert ship.key_numbers["source"] == "business_overview"
    assert ship.key_numbers["dominant_stage"] == "pre_ship"


# ---- Never raises on empty data ---------------------------------------------


def test_empty_sku_performance_does_not_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_full_table(con, [])
    con.close()
    result = run(db_path)
    assert any(f.title == "发货前后退款分解" for f in result.findings)


# ---- Real-DB smoke test ------------------------------------------------------


def test_real_db_smoke():
    if not os.path.exists(REAL_DB_PATH):
        pytest.skip("real analytics.duckdb not available")
    result = run(Path(REAL_DB_PATH))
    # NOTE: "餐饮具" is the GMV-dominant category (~884k), but the highest
    # *refund-rate* category in the real export is "陶瓷/紫砂/建盏/茶周边"
    # (~15.3% vs 餐饮具's ~14.4%) — Finding 2 ranks by rate, not GMV, so that
    # is the correct top_category here.
    category = next(f for f in result.findings if f.title == "品类退款分解")
    assert category.key_numbers["top_category"] == "陶瓷/紫砂/建盏/茶周边"
    ship = next(f for f in result.findings if f.title == "发货前后退款分解")
    assert ship.key_numbers["dominant_stage"] == "pre_ship"
