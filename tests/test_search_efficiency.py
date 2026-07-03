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
        con.executemany(
            "INSERT INTO search_overview VALUES (?, ?, ?, ?, ?)", rows
        )


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
    con.executemany(
        "INSERT INTO search_overview VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


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
    con.executemany(
        "INSERT INTO search_terms VALUES (?, ?, ?, ?)", rows
    )


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
    note_row = next(r for r in result.tables["carrier_search_efficiency"]
                    if r["carrier"] == "笔记")
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
    note_row = next(r for r in result.tables["carrier_search_efficiency"]
                    if r["carrier"] == "笔记")
    assert note_row["payers"] == 250


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
            ("opp", 1000.0, 0.8, 0.5),    # rate 0.40, well above baseline
            ("leak", 1000.0, 0.1, 0.05),  # rate 0.005, well below baseline
            ("tiny", 10.0, 0.9, 0.9),     # n < 30 → small sample, unclassified
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
