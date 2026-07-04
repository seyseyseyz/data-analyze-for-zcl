from pathlib import Path

from xhs_ceramics_analytics.analysis.demand_funnel import run
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "demand.duckdb"
    return connect(db_path), db_path


def _make_full(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date VARCHAR,
          add_to_cart_users DOUBLE,
          paid_buyers DOUBLE,
          "新增加入心愿单人数" DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?, ?)", rows)


def _make_funnel_only(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date VARCHAR,
          add_to_cart_users DOUBLE,
          paid_buyers DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?, ?)", rows)


# ---- Required table missing -------------------------------------------------


def test_missing_table_degrades_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run(db_path)
    assert result.task_id == "demand_funnel_diagnosis"
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "business_overview_daily" in result.limitations[0]


# ---- Full: funnel + trend + wishlist ----------------------------------------


def test_funnel_and_wishlist_surface(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [
        # date, add_to_cart_users, paid_buyers, 新增加入心愿单人数
        ("2026-04-01", 1000.0, 100.0, 200.0),
        ("2026-04-02", 1100.0, 120.0, 220.0),
        ("2026-04-03", 1200.0, 150.0, 250.0),
        ("2026-04-04", 1300.0, 180.0, 300.0),
        ("2026-04-05", 1400.0, 210.0, 350.0),
    ]
    _make_full(con, rows)
    con.close()

    result = run(db_path)

    funnel = next(f for f in result.findings if f.title == "加购→成交需求漏斗")
    kn = funnel.key_numbers
    assert abs(kn["total_add_to_cart_users"] - 6000.0) < 1e-9
    assert abs(kn["total_paid_buyers"] - 760.0) < 1e-9
    assert abs(kn["cart_to_pay"] - (760.0 / 6000.0)) < 1e-9
    # daily cart→pay rate climbs 10% → 15% across the window.
    assert kn["cart_to_pay_trend"] == "上升"

    trend = result.tables["demand_funnel_trend"]
    assert len(trend) == 5
    assert trend[0]["date"] == "2026-04-01"
    assert "cart_to_pay" in trend[0]

    # Orthogonal axes: observational so causal evidence is weak, yet the 6000-cart
    # sample with a tight Wilson CI makes it a HIGH-reliability description.
    assert funnel.evidence_strength.value == "weak"
    assert funnel.descriptive_reliability is not None
    assert funnel.descriptive_reliability.value == "high"

    wishlist = next(f for f in result.findings if f.title == "心愿单需求蓄水")
    wkn = wishlist.key_numbers
    assert abs(wkn["total_new_wishlist"] - 1320.0) < 1e-9
    assert wkn["wishlist_trend"] == "上升"
    wtable = result.tables["wishlist_demand_trend"]
    assert len(wtable) == 5
    assert "new_wishlist_users" in wtable[0]


# ---- Wishlist degrades when column absent -----------------------------------


def test_wishlist_degrades_when_column_absent(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_only(
        con,
        [
            ("2026-04-01", 1000.0, 100.0),
            ("2026-04-02", 1100.0, 120.0),
        ],
    )
    con.close()
    result = run(db_path)
    titles = {f.title for f in result.findings}
    assert "加购→成交需求漏斗" in titles
    assert "心愿单需求蓄水" not in titles
    assert "wishlist_demand_trend" not in result.tables


# ---- Funnel degrades when cart column absent --------------------------------


def test_funnel_degrades_not_judgable_when_cart_absent(tmp_path):
    con, db_path = _con(tmp_path)
    con.execute(
        'CREATE TABLE business_overview_daily (date VARCHAR, "新增加入心愿单人数" DOUBLE)'
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?, ?)",
        [("2026-04-01", 200.0), ("2026-04-02", 220.0)],
    )
    con.close()
    result = run(db_path)
    funnel = next(f for f in result.findings if "漏斗" in f.title)
    assert funnel.evidence_strength.value == "not_judgable"
    # wishlist still surfaces independently
    assert "心愿单需求蓄水" in {f.title for f in result.findings}
