from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect

SLUG = "search_efficiency_diagnosis"


def _con(tmp_path: Path):
    db_path = tmp_path / "search.duckdb"
    return connect(db_path), db_path


def _make_search_overview_min(con, rows):
    """search_overview without paid_buyers → forces forward-derivation."""
    con.execute(
        """
        CREATE TABLE search_overview (
          date DATE,
          carrier VARCHAR,
          card_impression_users DOUBLE,
          product_click_rate DOUBLE,
          pay_conversion DOUBLE
        )
        """
    )
    if rows:
        con.executemany("INSERT INTO search_overview VALUES (?, ?, ?, ?, ?)", rows)


def _make_search_overview_full(con, rows):
    """search_overview with paid_buyers → prefers real counts."""
    con.execute(
        """
        CREATE TABLE search_overview (
          date DATE,
          carrier VARCHAR,
          card_impression_users DOUBLE,
          product_click_rate DOUBLE,
          pay_conversion DOUBLE,
          gmv DOUBLE,
          paid_orders DOUBLE,
          paid_buyers DOUBLE,
          product_click_users DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO search_overview VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)


def _make_search_terms(con, rows):
    con.execute(
        """
        CREATE TABLE search_terms (
          search_term VARCHAR,
          card_impression_users DOUBLE,
          product_click_rate DOUBLE,
          pay_conversion DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO search_terms VALUES (?, ?, ?, ?)", rows)


# declining pay_conversion across 3 dates; 笔记 clearly more effective than 商卡
_MULTI_ROWS = [
    ("2026-04-30", "笔记", 4000.0, 0.5, 0.30),
    ("2026-05-31", "笔记", 3000.0, 0.5, 0.20),
    ("2026-06-30", "笔记", 3000.0, 0.5, 0.10),
    ("2026-04-30", "商卡", 4000.0, 0.2, 0.10),
    ("2026-05-31", "商卡", 3000.0, 0.2, 0.08),
    ("2026-06-30", "商卡", 3000.0, 0.2, 0.06),
]


def test_missing_search_overview_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task(SLUG, db_path)
    assert result.task_id == SLUG
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "search_overview" in result.limitations[0]


def test_carrier_finding_compares_two_carriers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    con.close()
    result = run_task(SLUG, db_path)
    titles = [f.title for f in result.findings]
    assert "载体搜索效率对比" in titles
    carriers = {r["carrier"] for r in result.tables["carrier_search_efficiency"]}
    assert carriers == {"笔记", "商卡"}
    finding = next(f for f in result.findings if f.title == "载体搜索效率对比")
    assert finding.key_numbers["carrier_high"] == "笔记"
    assert finding.key_numbers["significant"] is True
    assert finding.key_numbers["payers_source"] == "forward_derived"
    # forward-derived: never reverse-derive n = k / rate
    note_row = next(r for r in result.tables["carrier_search_efficiency"] if r["carrier"] == "笔记")
    assert note_row["impressions"] == 10000
    assert note_row["payers"] == 1050  # 600 + 300 + 150


def test_conversion_trend_reports_direction(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    con.close()
    result = run_task(SLUG, db_path)
    finding = next(f for f in result.findings if f.title == "搜索转化时间趋势")
    assert finding.key_numbers["trend_direction"] == "下降"
    assert len(result.tables["search_conversion_trend"]) == 3


def test_prefers_real_paid_buyers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_full(
        con,
        [
            # forward-derive would give 4000*0.5*0.2=400, but real paid_buyers=250
            ("2026-05-31", "笔记", 4000.0, 0.5, 0.20, 9000.0, 300.0, 250.0, 2000.0),
            ("2026-05-31", "商卡", 4000.0, 0.2, 0.05, 3000.0, 60.0, 50.0, 800.0),
        ],
    )
    con.close()
    result = run_task(SLUG, db_path)
    finding = next(f for f in result.findings if f.title == "载体搜索效率对比")
    assert finding.key_numbers["payers_source"] == "real"
    note_row = next(r for r in result.tables["carrier_search_efficiency"] if r["carrier"] == "笔记")
    assert note_row["payers"] == 250


def test_carrier_rows_use_real_counts_then_explicit_row_fallback(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_full(
        con,
        [
            ("2026-05-31", "笔记", 1000.0, 0.9, 0.9, 5000.0, 30.0, 25.0, 100.0),
            ("2026-05-31", "商卡", 1000.0, 0.2, 0.1, None, None, None, None),
        ],
    )
    con.close()

    result = run_task(SLUG, db_path)
    finding = next(f for f in result.findings if f.title == "载体搜索效率对比")
    rows = {row["carrier"]: row for row in result.tables["carrier_search_efficiency"]}

    assert finding.key_numbers["payers_source"] == "mixed"
    assert finding.key_numbers["click_users_coverage"] == {
        "real_rows": 1,
        "forward_derived_rows": 1,
        "missing_rows": 0,
    }
    assert rows["笔记"]["product_click_users"] == 100
    assert rows["笔记"]["paid_buyers"] == 25
    assert rows["笔记"]["paid_orders"] == 30
    assert rows["笔记"]["gmv"] == 5000.0
    assert rows["笔记"]["click_users_source"] == "real"
    assert rows["笔记"]["paid_buyers_source"] == "real"
    assert rows["商卡"]["product_click_users"] == 200
    assert rows["商卡"]["paid_buyers"] == 20
    assert rows["商卡"]["click_users_source"] == "forward_derived"
    assert rows["商卡"]["paid_buyers_source"] == "forward_derived"
    assert rows["商卡"]["paid_orders"] is None
    assert rows["商卡"]["gmv"] is None
    assert rows["笔记"]["click_to_pay_rate"] == 0.25
    assert rows["笔记"]["gmv_per_thousand_impressions"] == 5000.0


def test_real_daily_clicks_and_buyers_weight_search_conversion_trend(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_full(
        con,
        [
            ("2026-05-31", "笔记", 1000.0, 0.9, 0.9, None, None, 10.0, 100.0),
            ("2026-05-31", "商卡", 1000.0, 0.1, 0.1, None, None, 90.0, 900.0),
            ("2026-06-30", "笔记", 1000.0, 0.9, 0.9, None, None, 40.0, 100.0),
            ("2026-06-30", "商卡", 1000.0, 0.1, 0.1, None, None, 160.0, 900.0),
        ],
    )
    con.close()

    result = run_task(SLUG, db_path)
    rows = result.tables["search_conversion_trend"]

    assert rows[0]["avg_pay_conversion"] == 0.1
    assert rows[0]["conversion_source"] == "real_weighted"
    assert rows[1]["avg_pay_conversion"] == 0.2
    assert rows[1]["conversion_source"] == "real_weighted"


def test_search_trend_combines_real_and_row_fallback_records(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_full(
        con,
        [
            ("2026-05-31", "笔记", 1000, 0.1, 0.1, None, None, 10, 100),
            ("2026-05-31", "商卡", 9000, 1.0, 0.9, None, None, None, None),
            ("2026-06-30", "笔记", 1000, 0.1, 0.2, None, None, 20, 100),
            ("2026-06-30", "商卡", 9000, 1.0, 0.1, None, None, None, None),
        ],
    )
    con.close()

    result = run_task(SLUG, db_path)
    rows = result.tables["search_conversion_trend"]
    assert rows[0]["avg_pay_conversion"] == (10 + 8100) / (100 + 9000)
    assert rows[0]["conversion_source"] == "mixed"
    assert rows[1]["avg_pay_conversion"] == (20 + 900) / (100 + 9000)
    assert rows[1]["conversion_source"] == "mixed"


def test_search_terms_surface_full_funnel_with_real_counts(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    con.execute(
        """
        CREATE TABLE search_terms (
          search_term VARCHAR,
          card_impression_users DOUBLE,
          product_click_rate DOUBLE,
          pay_conversion DOUBLE,
          product_click_users DOUBLE,
          paid_buyers DOUBLE,
          paid_orders DOUBLE,
          gmv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO search_terms VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("真实词", 1000.0, 0.9, 0.9, 200.0, 20.0, 24.0, 6000.0),
            ("回退词", 1000.0, 0.1, 0.2, None, None, None, None),
        ],
    )
    con.close()

    result = run_task(SLUG, db_path)
    rows = {row["search_term"]: row for row in result.tables["search_term_opportunities"]}

    assert rows["真实词"]["product_click_users"] == 200
    assert rows["真实词"]["paid_buyers"] == 20
    assert rows["真实词"]["paid_orders"] == 24
    assert rows["真实词"]["gmv"] == 6000.0
    assert rows["真实词"]["click_to_pay_rate"] == 0.1
    assert rows["真实词"]["gmv_per_thousand_impressions"] == 6000.0
    assert rows["回退词"]["product_click_users"] == 100
    assert rows["回退词"]["paid_buyers"] == 20
    assert rows["回退词"]["click_users_source"] == "forward_derived"
    assert rows["回退词"]["paid_buyers_source"] == "forward_derived"


def test_single_carrier_skips_comparison_but_emits_finding(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(
        con,
        [
            ("2026-05-31", "笔记", 5000.0, 0.5, 0.20),
            ("2026-06-30", "笔记", 5000.0, 0.5, 0.10),
        ],
    )
    con.close()
    result = run_task(SLUG, db_path)
    finding = next(f for f in result.findings if f.title == "载体搜索效率对比")
    assert finding.key_numbers["significant"] is None
    assert any("载体" in lim for lim in result.limitations)


def test_empty_rows_do_not_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, [])
    con.close()
    result = run_task(SLUG, db_path)
    # Finding 1 always emitted → findings never empty
    assert result.findings
    assert "载体搜索效率对比" in [f.title for f in result.findings]


def test_search_terms_classify_opportunity_and_leak(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    _make_search_terms(
        con,
        [
            ("opp", 1000.0, 0.8, 0.5),  # rate 0.40, well above baseline
            ("leak", 1000.0, 0.1, 0.05),  # rate 0.005, well below baseline
            ("tiny", 10.0, 0.9, 0.9),  # n < 30 → small sample, unclassified
        ],
    )
    con.close()
    result = run_task(SLUG, db_path)
    finding = next(f for f in result.findings if f.title == "高机会/高流失搜索词")
    rows = {r["search_term"]: r for r in result.tables["search_term_opportunities"]}
    assert rows["opp"]["term_class"] == "opportunity"
    assert rows["leak"]["term_class"] == "leak"
    assert rows["tiny"]["term_class"] == "small_sample"
    assert finding.key_numbers["opportunity_count"] >= 1
    assert finding.key_numbers["leak_count"] >= 1
    assert finding.next_test


def test_leak_split_click_vs_conversion(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    _make_search_terms(
        con,
        [
            # low click-through, healthy conversion → click leak
            ("click_bad", 1000.0, 0.05, 0.5),
            # healthy click-through, poor conversion → conversion leak
            ("conv_bad", 1000.0, 0.5, 0.02),
            # strong on both → opportunity, lifts the baseline
            ("good", 1000.0, 0.5, 0.5),
        ],
    )
    con.close()
    result = run_task(SLUG, db_path)
    finding = next(f for f in result.findings if f.title == "高机会/高流失搜索词")
    rows = {r["search_term"]: r for r in result.tables["search_term_opportunities"]}
    assert rows["click_bad"]["leak_type"] == "click_leak"
    assert rows["conv_bad"]["leak_type"] == "conversion_leak"
    assert finding.key_numbers["click_leak_count"] >= 1
    assert finding.key_numbers["conversion_leak_count"] >= 1
    assert finding.key_numbers["click_baseline"] is not None


def test_search_terms_absent_degrades(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    con.close()
    result = run_task(SLUG, db_path)
    assert "高机会/高流失搜索词" not in [f.title for f in result.findings]
    assert any("search_terms" in lim for lim in result.limitations)


def test_every_finding_has_confounders_and_caveats(tmp_path):
    con, db_path = _con(tmp_path)
    _make_search_overview_min(con, _MULTI_ROWS)
    _make_search_terms(con, [("opp", 1000.0, 0.8, 0.5), ("leak", 1000.0, 0.1, 0.05)])
    con.close()
    result = run_task(SLUG, db_path)
    for finding in result.findings:
        assert finding.confounders
        assert finding.caveats
        assert finding.evidence_strength.value == "weak"
