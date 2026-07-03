from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect

TASK = "audience_structure_diagnosis"


def _con(tmp_path: Path):
    db_path = tmp_path / "audience.duckdb"
    return connect(db_path), db_path


def _make_funnel_full(con, rows):
    con.execute(
        """
        CREATE TABLE shop_page_funnel (
          date DATE,
          audience_type VARCHAR,
          first_purchase_cycle VARCHAR,
          shop_visitors DOUBLE,
          shop_payers DOUBLE,
          product_click_users DOUBLE,
          visit_click_rate DOUBLE,
          click_pay_rate DOUBLE,
          visit_pay_rate DOUBLE
        )
        """
    )
    if rows:
        con.executemany(
            "INSERT INTO shop_page_funnel VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
        )


def _make_funnel_no_audience(con, rows):
    con.execute(
        """
        CREATE TABLE shop_page_funnel (
          date DATE,
          first_purchase_cycle VARCHAR,
          shop_visitors DOUBLE,
          shop_payers DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO shop_page_funnel VALUES (?, ?, ?, ?)", rows
    )


def _make_source(con, rows):
    con.execute(
        """
        CREATE TABLE shop_page_source (
          audience_type VARCHAR,
          first_purchase_cycle VARCHAR,
          source_page VARCHAR,
          shop_visitors DOUBLE,
          enter_pay_rate DOUBLE,
          shop_gmv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO shop_page_source VALUES (?, ?, ?, ?, ?, ?)", rows
    )


def _make_profile(con, rows):
    con.execute(
        """
        CREATE TABLE audience_profile (
          audience_segment VARCHAR, share DOUBLE, gmv DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO audience_profile VALUES (?, ?, ?)", rows)


# ---- Required table missing -----------------------------------------------


def test_missing_shop_page_funnel_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task(TASK, db_path)
    assert result.task_id == TASK
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "shop_page_funnel" in result.limitations[0]


# ---- Finding 1 always emitted ---------------------------------------------


def test_conversion_finding_compares_audiences(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [
            ("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10),
            ("2026-06-01", "老客", "复购", 1000.0, 300.0, 500.0, 0.5, 0.60, 0.30),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群转化对比")
    kn = finding.key_numbers
    assert kn["group_count"] == 2
    assert kn["diff"] is not None
    assert kn["significant"] is True
    comp = result.tables["audience_conversion_comparison"]
    assert {r["audience_type"] for r in comp} == {"新客", "老客"}
    assert finding.confounders  # observational confounders present
    assert finding.recommended_action  # lever present


def test_conversion_falls_back_without_audience_type(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_no_audience(
        con,
        [
            ("2026-06-01", "首购", 1000.0, 120.0),
            ("2026-06-02", "复购", 800.0, 160.0),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群转化对比")
    assert finding.key_numbers["overall_conversion"] is not None
    assert any("audience_type" in lim for lim in result.limitations)


def test_single_audience_group_falls_back(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群转化对比")
    assert finding.key_numbers["overall_conversion"] is not None
    assert "diff" not in finding.key_numbers or finding.key_numbers.get("diff") is None


# ---- Finding 2 first purchase cycle ---------------------------------------


def test_cycle_finding_reports_weakest_cycle(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [
            ("2026-06-01", "新客", "首购", 1000.0, 50.0, 400.0, 0.4, 0.10, 0.05),
            ("2026-06-01", "老客", "复购", 1000.0, 300.0, 500.0, 0.5, 0.60, 0.30),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "首购周期漏斗")
    rows = result.tables["first_purchase_cycle_funnel"]
    assert {r["first_purchase_cycle"] for r in rows} == {"首购", "复购"}
    assert finding.key_numbers["weakest_cycle"] == "首购"


# ---- Finding 3 source structure -------------------------------------------


def test_source_finding_ranks_sources(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    _make_source(
        con,
        [
            ("新客", "首购", "搜索", 1000.0, 0.10, 8000.0),
            ("新客", "首购", "推荐", 500.0, 0.02, 1000.0),
            ("新客", "首购", "商城", 300.0, 0.15, 3000.0),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "进店来源结构")
    rows = result.tables["shop_source_structure"]
    assert {r["source_page"] for r in rows} == {"搜索", "推荐", "商城"}
    assert finding.key_numbers["top_source"] == "搜索"


def test_source_finding_skipped_without_table(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    con.close()
    result = run_task(TASK, db_path)
    assert "进店来源结构" not in [f.title for f in result.findings]
    assert any("shop_page_source" in lim for lim in result.limitations)


# ---- Finding 4 composition (documented gap) -------------------------------


def test_composition_gap_notice_without_profile(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群构成")
    assert finding.evidence_strength.value == "not_judgable"
    assert "手工录入" in finding.conclusion
    assert "audience_profile" in finding.conclusion


def test_composition_real_when_profile_present(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    _make_profile(con, [("高客单人群", 0.6, 60000.0), ("尝鲜人群", 0.4, 40000.0)])
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群构成")
    rows = result.tables["audience_composition"]
    assert {r["audience_segment"] for r in rows} == {"高客单人群", "尝鲜人群"}
    assert finding.key_numbers["top_segment"] == "高客单人群"


# ---- Never raises on empty / dirty data -----------------------------------


def test_empty_funnel_does_not_raise(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(con, [])
    con.close()
    result = run_task(TASK, db_path)
    # Finding 1 always emitted; Finding 4 always emitted; nothing raised.
    assert any(f.title == "人群转化对比" for f in result.findings)
    assert any(f.title == "人群构成" for f in result.findings)


def test_findings_never_empty_and_always_has_conversion(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)],
    )
    con.close()
    result = run_task(TASK, db_path)
    assert len(result.findings) >= 1
    assert result.findings[0].title == "人群转化对比"
