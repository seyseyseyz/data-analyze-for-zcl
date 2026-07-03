from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "core.duckdb"
    return connect(db_path), db_path


def _make_business_full(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date INTEGER, gmv DOUBLE, paid_orders DOUBLE, paid_buyers DOUBLE, aov DOUBLE,
          note_gmv DOUBLE, card_gmv DOUBLE, note_paid_orders DOUBLE, card_paid_orders DOUBLE,
          product_visitors DOUBLE, paid_units DOUBLE, pay_conversion_uv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO business_overview_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows
    )


def _make_business_minimal(con, rows):
    con.execute(
        """
        CREATE TABLE business_overview_daily (
          date INTEGER, gmv DOUBLE, paid_orders DOUBLE, paid_buyers DOUBLE, aov DOUBLE
        )
        """
    )
    if rows:
        con.executemany("INSERT INTO business_overview_daily VALUES (?,?,?,?,?)", rows)


def _make_traffic(con, rows):
    con.execute(
        """
        CREATE TABLE traffic_source (
          xhs_id VARCHAR, channel VARCHAR, product_clicks DOUBLE,
          product_click_users DOUBLE, paid_buyers DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO traffic_source VALUES (?,?,?,?,?)", rows)


def _make_funnel(con, rows):
    con.execute(
        """
        CREATE TABLE shop_page_funnel (
          date INTEGER, audience_type VARCHAR, first_purchase_cycle VARCHAR,
          shop_visitors DOUBLE, product_click_users DOUBLE, shop_payers DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO shop_page_funnel VALUES (?,?,?,?,?,?)", rows)


_FULL_ROWS = [
    (20260401, 10000.0, 200.0, 180.0, 55.5, 6000.0, 4000.0, 120.0, 80.0, 2000.0, 220.0, 0.09),
    (20260402, 12000.0, 240.0, 210.0, 57.0, 7000.0, 5000.0, 150.0, 90.0, 2400.0, 260.0, 0.0875),
    (20260403, 15000.0, 300.0, 260.0, 57.6, 9000.0, 6000.0, 180.0, 120.0, 3000.0, 320.0, 0.0867),
]

_TRAFFIC_ROWS = [
    ("acc", "搜索", 1200.0, 900.0, 300.0),
    ("acc", "推荐", 2000.0, 1500.0, 200.0),
    ("acc", "搜索", 400.0, 300.0, 90.0),
]

# visitors 1000, clicks 300 (visit_click .30), payers 60 (click_pay .20, visit_pay .06)
_FUNNEL_ROWS = [
    (20260401, "新客", "首购", 700.0, 210.0, 30.0),
    (20260402, "老客", "复购", 300.0, 90.0, 30.0),
]


def test_missing_business_overview_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.task_id == "core_business_diagnosis"
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "business_overview_daily" in result.limitations[0]


def test_snapshot_finding_always_emitted_with_trend(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.findings, "findings must never be empty"
    snap = result.findings[0]
    kn = snap.key_numbers
    assert kn["total_gmv"] == 37000.0
    assert kn["total_paid_buyers"] == 650.0
    assert kn["trend_direction"] == "上升"
    assert snap.evidence_strength.value == "weak"
    assert len(result.tables["business_trend"]) == 3
    assert len(result.tables["business_snapshot"]) == 1
    assert snap.confounders  # every finding carries confounders


def test_carrier_and_channel_structure_emitted(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    _make_traffic(con, _TRAFFIC_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    assert any("载体" in t or "渠道" in t for t in titles)
    carrier = result.tables["carrier_structure"]
    assert {r["carrier"] for r in carrier} == {"note", "card"}
    note_row = next(r for r in carrier if r["carrier"] == "note")
    assert note_row["gmv"] == 22000.0
    channel = result.tables["traffic_channel_structure"]
    assert {r["channel"] for r in channel} == {"搜索", "推荐"}
    struct = next(f for f in result.findings if "载体" in f.title or "渠道" in f.title)
    # two_proportion ran on top-2 channels (real counts), reports diff
    assert "channel_diff" in struct.key_numbers


def test_funnel_finding_identifies_weakest_stage_and_audience(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    _make_funnel(con, _FUNNEL_ROWS)
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    funnel = next(f for f in result.findings if "漏斗" in f.title)
    assert funnel.key_numbers["weakest_stage"] == "click_pay"
    assert funnel.recommended_action  # lever text present
    stages = result.tables["shop_funnel_stages"]
    assert {r["stage"] for r in stages} == {"visit_click", "click_pay", "visit_pay"}
    aud = result.tables["audience_conversion"]
    assert {r["audience_type"] for r in aud} == {"新客", "老客"}


def test_optional_tables_missing_degrades_without_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(
        con,
        [
            (20260401, 10000.0, 200.0, 180.0, 55.5),
            (20260402, 12000.0, 240.0, 210.0, 57.0),
        ],
    )
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    # snapshot still emitted; carrier/channel/funnel skipped with limitations
    assert any("快照" in t or "经营" in t for t in titles)
    assert "carrier_structure" not in result.tables
    assert "shop_funnel_stages" not in result.tables
    assert result.limitations  # degradations logged


def test_single_row_skips_trend_without_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(con, [(20260401, 10000.0, 200.0, 180.0, 55.5)])
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    assert result.findings  # never empty
    assert "business_trend" not in result.tables or len(
        result.tables.get("business_trend", [])
    ) <= 1
    assert any("趋势" in lim for lim in result.limitations)


def test_empty_business_overview_does_not_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_minimal(con, [])
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    # required table exists but empty: still emits Finding 1, no exception
    assert result.findings
    assert result.findings[0].key_numbers.get("total_gmv") in (0.0, None)


def test_channel_share_only_without_paid_buyers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_business_full(con, _FULL_ROWS)
    con.execute(
        """
        CREATE TABLE traffic_source (
          xhs_id VARCHAR, channel VARCHAR, product_clicks DOUBLE,
          product_click_users DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO traffic_source VALUES (?,?,?,?)",
        [("acc", "搜索", 1200.0, 900.0), ("acc", "推荐", 2000.0, 1500.0)],
    )
    con.close()
    result = run_task("core_business_diagnosis", db_path)
    channel = result.tables["traffic_channel_structure"]
    assert {r["channel"] for r in channel} == {"搜索", "推荐"}
    struct = next(f for f in result.findings if "载体" in f.title or "渠道" in f.title)
    # no two_proportion without paid_buyers counts
    assert struct.key_numbers.get("channel_diff") is None
