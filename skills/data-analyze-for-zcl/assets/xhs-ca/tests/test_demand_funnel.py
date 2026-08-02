from pathlib import Path

import pytest

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
          new_wishlist_users DOUBLE
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
        # date, add_to_cart_users, paid_buyers, new_wishlist_users
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
    assert "total_add_to_cart_users" not in kn
    assert "total_paid_buyers" not in kn
    assert abs(kn["add_to_cart_user_days"] - 6000.0) < 1e-9
    assert abs(kn["paid_buyer_days"] - 760.0) < 1e-9
    assert abs(kn["avg_daily_add_to_cart_users"] - 1200.0) < 1e-9
    assert abs(kn["avg_daily_paid_buyers"] - 152.0) < 1e-9
    expected_daily_ratio = sum([100 / 1000, 120 / 1100, 150 / 1200, 180 / 1300, 210 / 1400]) / 5
    assert kn["avg_daily_cart_to_pay"] == pytest.approx(expected_daily_ratio)
    # daily cart→pay rate climbs 10% → 15% across the window.
    assert kn["cart_to_pay_trend"] == "上升"
    assert "ci_low" not in kn and "ci_high" not in kn
    assert "日均加购" in funnel.conclusion
    assert any("逐日去重" in caveat for caveat in funnel.caveats)

    trend = result.tables["demand_funnel_trend"]
    assert len(trend) == 5
    assert trend[0]["date"] == "2026-04-01"
    assert "cart_to_pay" in trend[0]

    # Repeated users across days are unknown, so reliability uses five observed days.
    assert funnel.evidence_strength.value == "weak"
    assert funnel.descriptive_reliability is not None
    assert funnel.descriptive_reliability.value == "low"

    wishlist = next(f for f in result.findings if f.title == "心愿单需求蓄水")
    wkn = wishlist.key_numbers
    assert "total_new_wishlist" not in wkn
    assert abs(wkn["new_wishlist_user_days"] - 1320.0) < 1e-9
    assert abs(wkn["avg_daily_new_wishlist_users"] - 264.0) < 1e-9
    assert wkn["avg_daily_wishlist_to_cart"] == pytest.approx(
        sum((200 / 1000, 220 / 1100, 250 / 1200, 300 / 1300, 350 / 1400)) / 5
    )
    assert wkn["wishlist_trend"] == "上升"
    assert "日均新增" in wishlist.conclusion
    assert any("逐日去重" in caveat for caveat in wishlist.caveats)
    wtable = result.tables["wishlist_demand_trend"]
    assert len(wtable) == 5
    assert "new_wishlist_users" in wtable[0]


def test_missing_daily_distinct_values_stay_missing(tmp_path):
    con, db_path = _con(tmp_path)
    _make_full(
        con,
        [
            ("2026-04-01", 100.0, None, 20.0),
            ("2026-04-02", None, 10.0, None),
        ],
    )
    con.close()

    result = run(db_path)

    funnel = next(f for f in result.findings if f.title == "加购→成交需求漏斗")
    assert funnel.key_numbers["avg_daily_add_to_cart_users"] == 100.0
    assert funnel.key_numbers["avg_daily_paid_buyers"] == 10.0
    assert funnel.key_numbers["avg_daily_cart_to_pay"] is None
    assert funnel.key_numbers["add_to_cart_observed_days"] == 1
    assert funnel.key_numbers["paid_buyer_observed_days"] == 1
    assert funnel.key_numbers["paired_ratio_observed_days"] == 0
    assert funnel.descriptive_reliability.value == "not_applicable"
    assert funnel.recommended_action is None
    assert any("有效配对日为 0" in message for message in result.limitations)
    assert result.tables["demand_funnel_trend"] == [
        {
            "date": "2026-04-01",
            "add_to_cart_users": 100.0,
            "paid_buyers": None,
            "cart_to_pay": None,
        },
        {
            "date": "2026-04-02",
            "add_to_cart_users": None,
            "paid_buyers": 10.0,
            "cart_to_pay": None,
        },
    ]
    assert result.tables["wishlist_demand_trend"][1]["new_wishlist_users"] is None


def test_all_null_daily_distinct_values_are_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    _make_full(
        con,
        [
            ("2026-04-01", None, None, None),
            ("2026-04-02", None, None, None),
        ],
    )
    con.close()

    result = run(db_path)

    funnel = next(f for f in result.findings if f.title == "加购→成交需求漏斗")
    assert funnel.key_numbers["add_to_cart_user_days"] is None
    assert funnel.key_numbers["paid_buyer_days"] is None
    assert funnel.key_numbers["avg_daily_add_to_cart_users"] is None
    assert funnel.key_numbers["avg_daily_paid_buyers"] is None
    assert funnel.evidence_strength.value == "not_judgable"
    assert funnel.recommended_action is None
    assert "日均加购 0 人" not in funnel.conclusion
    assert "日均支付买家 0 人" not in funnel.conclusion
    assert "日均加购数据不足" in funnel.conclusion
    assert "日均支付买家数据不足" in funnel.conclusion

    wishlist = next(f for f in result.findings if f.title == "心愿单需求蓄水")
    assert wishlist.key_numbers["new_wishlist_user_days"] is None
    assert wishlist.key_numbers["avg_daily_new_wishlist_users"] is None
    assert wishlist.evidence_strength.value == "not_judgable"
    assert wishlist.recommended_action is None
    assert "心愿单日均新增 0 人" not in wishlist.conclusion
    assert "心愿单日均新增数据不足" in wishlist.conclusion
    assert any("心愿单有效观察日为 0" in message for message in result.limitations)


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
    con.execute("CREATE TABLE business_overview_daily (date VARCHAR, new_wishlist_users DOUBLE)")
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


def test_product_visitor_to_cart_to_pay_daily_stage_facts(tmp_path):
    con, db_path = _con(tmp_path)
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date VARCHAR,
          product_visitors DOUBLE,
          add_to_cart_users DOUBLE,
          paid_buyers DOUBLE,
          new_wishlist_users DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?, ?, ?, ?, ?)",
        [
            ("2026-04-01", 1000.0, 100.0, 20.0, 10.0),
            ("2026-04-02", 2000.0, 300.0, 60.0, 20.0),
        ],
    )
    con.close()

    result = run(db_path)

    funnel = next(f for f in result.findings if f.title == "加购→成交需求漏斗")
    assert funnel.key_numbers["avg_daily_product_visitors"] == 1500.0
    assert funnel.key_numbers["avg_daily_product_to_cart"] == pytest.approx(0.125)
    assert funnel.key_numbers["avg_daily_cart_to_pay"] == pytest.approx(0.2)
    assert any("不是严格的用户漏斗" in caveat for caveat in funnel.caveats)
    assert result.tables["demand_funnel_trend"] == [
        {
            "date": "2026-04-01",
            "product_visitors": 1000.0,
            "add_to_cart_users": 100.0,
            "paid_buyers": 20.0,
            "product_to_cart": 0.1,
            "cart_to_pay": 0.2,
        },
        {
            "date": "2026-04-02",
            "product_visitors": 2000.0,
            "add_to_cart_users": 300.0,
            "paid_buyers": 60.0,
            "product_to_cart": 0.15,
            "cart_to_pay": 0.2,
        },
    ]


def test_product_to_cart_keeps_its_daily_fact_when_payment_is_missing(tmp_path):
    con, db_path = _con(tmp_path)
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date VARCHAR,
          product_visitors DOUBLE,
          add_to_cart_users DOUBLE,
          paid_buyers DOUBLE
        )
        """
    )
    con.execute("INSERT INTO business_overview_daily VALUES ('2026-04-01', 1000.0, 100.0, NULL)")
    con.close()

    result = run(db_path)
    funnel = next(f for f in result.findings if f.title == "加购→成交需求漏斗")

    assert funnel.key_numbers["avg_daily_product_to_cart"] == 0.1
    assert result.tables["demand_funnel_trend"][0]["product_to_cart"] == 0.1
    assert result.tables["demand_funnel_trend"][0]["cart_to_pay"] is None
