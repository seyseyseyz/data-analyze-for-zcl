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


# ---- Rollup + overlapping-window regression (A1) --------------------------


def test_rollup_and_windows_not_double_counted(tmp_path):
    # Mirrors real shop_page_funnel: a 全部/全部 rollup plus nested 180/365 windows.
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [
            ("2026-06-01", "新客", "365天", 400.0, 20.0, 0.0, 0.0, 0.0, 0.0),
            ("2026-06-01", "新客", "180天", 410.0, 21.0, 0.0, 0.0, 0.0, 0.0),
            ("2026-06-01", "老客", "365天", 130.0, 15.0, 0.0, 0.0, 0.0, 0.0),
            ("2026-06-01", "老客", "180天", 118.0, 14.0, 0.0, 0.0, 0.0, 0.0),
            ("2026-06-01", "全部", "全部", 530.0, 35.0, 0.0, 0.0, 0.0, 0.0),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群转化对比")
    comp = result.tables["audience_conversion_comparison"]
    by_type = {r["audience_type"]: r for r in comp}
    # The 全部 rollup must not appear as a comparison group.
    assert set(by_type) == {"新客", "老客"}
    # Canonical window is 365天 — 新客 visitors == single window, not 400+410.
    assert by_type["新客"]["visitors"] == 400.0
    assert by_type["老客"]["visitors"] == 130.0
    # Overall conversion uses the platform 全部 rollup (35/530), not a summed total.
    assert abs(finding.key_numbers["overall_conversion"] - 35.0 / 530.0) < 1e-9


def test_retention_metrics_present_and_directional(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [
            ("2026-06-01", "新客", "365天", 400.0, 20.0, 0.0, 0.0, 0.0, 0.0),
            ("2026-06-01", "老客", "365天", 130.0, 15.0, 0.0, 0.0, 0.0, 0.0),
            ("2026-06-01", "全部", "全部", 530.0, 35.0, 0.0, 0.0, 0.0, 0.0),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群转化对比")
    kn = finding.key_numbers
    # New customers: 20 of 35 payers.
    assert abs(kn["new_customer_dependence"] - 20.0 / 35.0) < 1e-9
    # Old converts better (15/130 > 20/400) → premium positive.
    assert kn["repeat_conversion_premium"] > 0
    assert "新客贡献付费" in finding.conclusion


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


def test_cycle_finding_identical_nested_windows_no_spurious_weakest(tmp_path):
    # Real data: nested cumulative windows 180天 ⊂ 365天 end up numerically
    # identical. Declaring a "weakest" among equal windows and a 0.0pp gap is noise.
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [
            ("2026-06-01", "新客", "180天", 19012.0, 1109.0, 8000.0, 0.42, 0.14, 0.0583),
            ("2026-06-01", "新客", "365天", 19012.0, 1109.0, 8000.0, 0.42, 0.14, 0.0583),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "首购周期漏斗")
    # No spurious weakest declared when windows do not differ meaningfully.
    assert finding.key_numbers["weakest_cycle"] is None
    assert "无有效差异" in finding.conclusion
    assert "最弱周期为" not in finding.conclusion


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


# ---- Finding 4 customer value (contribution + concentration) --------------


def test_customer_value_contribution_and_concentration(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    # 老客 out-contributes 新客 on GMV (10000 vs 8000), and its GMV is spread across
    # three进店来源 so the source-level Gini is a real, non-degenerate number.
    _make_source(
        con,
        [
            ("新客", "首购", "搜索", 1000.0, 0.10, 6000.0),
            ("新客", "首购", "推荐", 500.0, 0.02, 2000.0),
            ("老客", "复购", "搜索", 800.0, 0.15, 5000.0),
            ("老客", "复购", "推荐", 400.0, 0.05, 1000.0),
            ("老客", "复购", "商城", 300.0, 0.20, 4000.0),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "客户价值贡献与集中度")
    rows = result.tables["audience_gmv_contribution"]
    assert {r["audience_type"] for r in rows} == {"新客", "老客"}
    # total GMV 18000 → 老客 share = 10000/18000, the top contributor
    assert rows[0]["audience_type"] == "老客"
    kn = finding.key_numbers
    assert kn["top_audience_by_gmv"] == "老客"
    assert kn["repeat_gmv_share"] > 0.5
    assert kn["repeat_source_count"] == 3
    assert kn["repeat_gmv_gini"] is not None and kn["repeat_gmv_gini"] > 0
    assert "顾客个体层面" in " ".join(finding.caveats)


def test_customer_value_skipped_without_source_table(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    con.close()
    result = run_task(TASK, db_path)
    assert "客户价值贡献与集中度" not in [f.title for f in result.findings]
    assert "audience_gmv_contribution" not in result.tables


def test_customer_value_skipped_without_gmv_column(tmp_path):
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con,
        [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)],
    )
    # shop_page_source without shop_gmv → contribution not computable, degrade.
    con.execute(
        """
        CREATE TABLE shop_page_source (
          audience_type VARCHAR, first_purchase_cycle VARCHAR,
          source_page VARCHAR, shop_visitors DOUBLE, enter_pay_rate DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO shop_page_source VALUES (?, ?, ?, ?, ?)",
        [("新客", "首购", "搜索", 1000.0, 0.10)],
    )
    con.close()
    result = run_task(TASK, db_path)
    assert "客户价值贡献与集中度" not in [f.title for f in result.findings]
    assert any("shop_gmv" in lim for lim in result.limitations)


# ---- Finding 5 composition (documented gap) -------------------------------


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


# ---- Feature 5: multi-dimensional + share-primary PNG 画像 read ------------

def _make_profile_multidim(con, rows):
    con.execute(
        """
        CREATE TABLE audience_profile (
          dimension VARCHAR, audience_segment VARCHAR, share DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO audience_profile VALUES (?, ?, ?)", rows)


def test_composition_multidim_share_primary(tmp_path):
    # The 9.人群分析 PNG gives multi-dimensional SHARES (性别/年龄/消费层级/地域) with no
    # per-bucket GMV. Transcribed into audience_profile(dimension, audience_segment, share),
    # it must produce a WEAK snapshot finding — one breakdown per dimension — not not_judgable.
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con, [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)]
    )
    _make_profile_multidim(
        con,
        [
            ("年龄", "26-30岁", 0.38),
            ("年龄", "31-35岁", 0.20),
            ("消费层级", "中", 0.57),
            ("消费层级", "高", 0.40),
            ("地域", "上海", 0.22),
        ],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群构成")
    assert finding.evidence_strength.value == "weak"
    assert finding.descriptive_reliability.value == "low"
    rows = result.tables["audience_composition"]
    assert all("dimension" in r for r in rows)
    assert {r["dimension"] for r in rows} == {"年龄", "消费层级", "地域"}
    # conclusion summarizes the top bucket per dimension by share
    assert "26-30岁" in finding.conclusion
    assert "中" in finding.conclusion
    assert finding.key_numbers["dimension_count"] == 3
    # explicit 截图识读 caveat — never precise, only directional
    assert any("截图" in c for c in finding.caveats)


def test_composition_share_only_single_dimension(tmp_path):
    # gmv is now optional — a share-only single-dimension profile still yields WEAK
    con, db_path = _con(tmp_path)
    _make_funnel_full(
        con, [("2026-06-01", "新客", "首购", 1000.0, 100.0, 400.0, 0.4, 0.25, 0.10)]
    )
    con.execute("CREATE TABLE audience_profile (audience_segment VARCHAR, share DOUBLE)")
    con.executemany(
        "INSERT INTO audience_profile VALUES (?, ?)",
        [("高客单人群", 0.6), ("尝鲜人群", 0.4)],
    )
    con.close()
    result = run_task(TASK, db_path)
    finding = next(f for f in result.findings if f.title == "人群构成")
    assert finding.evidence_strength.value == "weak"
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
