from pathlib import Path

import pytest

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.build import build_database
from xhs_ceramics_analytics.db.duck import connect


def _db(tmp_path: Path, fixture_dir: Path) -> Path:
    db_path = tmp_path / "analytics.duckdb"
    build_database(
        db_path,
        [
            fixture_dir / "notes.csv",
            fixture_dir / "products.csv",
            fixture_dir / "skus.csv",
            fixture_dir / "orders.csv",
            fixture_dir / "content_features.csv",
            fixture_dir / "comments.csv",
            fixture_dir / "calendar_events.csv",
        ],
    )
    return db_path


def test_data_quality_task_runs(tmp_path, fixture_dir):
    result = run_task("data_quality_check", _db(tmp_path, fixture_dir))
    assert result.task_id == "data_quality_check"
    assert result.findings


def test_data_quality_excludes_internal_aux_tables(tmp_path, fixture_dir):
    # needs_data / data_quality / build_manifest / mapping_diagnostics are internal
    # build scaffolding — an empty one is normal (no diagnostics = good), not a data
    # gap. Listing them as 「空表」 to the merchant is misleading noise; exclude them.
    result = run_task("data_quality_check", _db(tmp_path, fixture_dir))
    conclusion = result.findings[0].conclusion
    for aux in ("needs_data", "data_quality", "build_manifest", "mapping_diagnostics"):
        assert aux not in conclusion


def test_account_baseline_task_reports_post_count(tmp_path, fixture_dir):
    result = run_task("account_baseline", _db(tmp_path, fixture_dir))
    assert result.tables["daily_posts"][0]["posts"] >= 1


def test_account_baseline_daily_post_dates_are_strings(tmp_path, fixture_dir):
    result = run_task("account_baseline", _db(tmp_path, fixture_dir))

    assert isinstance(result.tables["daily_posts"][0]["date"], str)


def test_note_funnel_task_reports_rates(tmp_path, fixture_dir):
    result = run_task("note_funnel", _db(tmp_path, fixture_dir))
    assert "note_funnel" in result.tables


def test_sku_lift_task_runs(tmp_path, fixture_dir):
    result = run_task("sku_counterfactual_lift", _db(tmp_path, fixture_dir))
    assert result.task_id == "sku_counterfactual_lift"
    assert result.title == "SKU 销量响应"
    assert "sku_lift" in result.tables


def test_response_curve_task_runs(tmp_path, fixture_dir):
    result = run_task("content_response_curve", _db(tmp_path, fixture_dir))
    assert result.task_id == "content_response_curve"
    assert "response_windows" in result.tables


def test_product_response_tasks_explain_evidence_reason(tmp_path, fixture_dir):
    db_path = _db(tmp_path, fixture_dir)

    for task_id in [
        "product_opportunity_matrix",
        "sku_counterfactual_lift",
        "content_response_curve",
    ]:
        result = run_task(task_id, db_path)
        assert result.findings[0].evidence_reason


def test_content_and_product_tasks_run(tmp_path, fixture_dir):
    db_path = _db(tmp_path, fixture_dir)
    for task_id, table_name in [
        ("cover_style_effect", "cover_effects"),
        ("copy_angle_effect", "copy_effects"),
        ("product_content_interaction", "product_interactions"),
        ("product_opportunity_matrix", "product_opportunities"),
    ]:
        result = run_task(task_id, db_path)
        assert result.task_id == task_id
        assert table_name in result.tables


@pytest.mark.parametrize(
    ("task_id", "dimension"),
    [
        ("cover_style_effect", "composition_type"),
        ("copy_angle_effect", "copy_angle"),
    ],
)
def test_content_effect_tasks_accept_commercial_metrics_as_evidence(
    tmp_path,
    task_id,
    dimension,
):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            f"CREATE TABLE content_features (note_id VARCHAR, {dimension} VARCHAR)"
        )
        con.execute("INSERT INTO content_features VALUES ('note-1', '场景展示')")
        con.execute(
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              impressions DOUBLE,
              product_clicks DOUBLE,
              note_paid_orders DOUBLE,
              note_gmv DOUBLE
            )
            """
        )
        con.execute("INSERT INTO notes VALUES ('note-1', 1000, 80, 8, 800)")
    finally:
        con.close()

    result = run_task(task_id, db_path)

    assert result.findings[0].evidence_strength.value == "weak"


def test_decision_and_knowledge_tasks_run(tmp_path, fixture_dir):
    db_path = _db(tmp_path, fixture_dir)
    expected = {
        "comment_demand_mining": "comment_demands",
        "content_portfolio_optimization": "portfolio_mix",
        "weekly_experiment_matrix": "experiment_plan",
        "reshoot_repost_candidates": "reshoot_candidates",
        "hypothesis_knowledge_base": "hypotheses",
        "weekly_business_review": "weekly_sections",
    }
    for task_id, table_name in expected.items():
        result = run_task(task_id, db_path)
        assert result.task_id == task_id
        assert table_name in result.tables


def test_ad_data_quality_check_reports_paid_export_readiness(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_campaign.csv"])

    result = run_task("ad_data_quality_check", db_path)

    assert result.task_id == "ad_data_quality_check"
    assert result.title == "投放数据可用性检查"
    assert result.findings[0].evidence_reason
    row = result.tables["ad_data_quality"][0]
    assert row["rows"] == 2
    assert row["detected_grain"] == "campaign"
    assert row["total_spend"] == 200
    assert row["has_click_metrics"] is True
    assert row["has_gmv_metrics"] is True


def test_ad_data_quality_check_degrades_when_ad_table_missing(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    con.close()

    result = run_task("ad_data_quality_check", db_path)

    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert result.tables["ad_data_quality"] == []
    assert "ad_performance_daily" in result.limitations[0]


def test_note_funnel_returns_none_for_zero_denominators(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              impressions INTEGER,
              reads INTEGER,
              likes INTEGER,
              collects INTEGER,
              comments INTEGER
            )
            """
        )
        con.execute(
            """
            INSERT INTO notes VALUES ('zero-denominator-note', 0, 0, 0, 0, 0)
            """
        )
    finally:
        con.close()

    result = run_task("note_funnel", db_path)
    row = result.tables["note_funnel"][0]

    assert row["read_rate"] is None
    assert row["like_rate"] is None
    assert row["collect_rate"] is None
    assert row["comment_rate"] is None


def test_note_funnel_builds_commercial_funnel_from_available_fields(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              title VARCHAR,
              note_type VARCHAR,
              video_seconds DOUBLE,
              impressions DOUBLE,
              reads DOUBLE,
              likes DOUBLE,
              collects DOUBLE,
              comments DOUBLE,
              shares DOUBLE,
              avg_read_seconds DOUBLE,
              completion_rate_pv DOUBLE,
              product_clicks DOUBLE,
              product_click_users DOUBLE,
              pay_conversion_pv DOUBLE,
              pay_conversion_uv DOUBLE,
              note_paid_orders DOUBLE,
              note_paid_buyers DOUBLE,
              note_gmv DOUBLE,
              note_refund_amount_pay DOUBLE,
              note_refund_rate_pay DOUBLE,
              add_to_cart_units DOUBLE,
              to_shop_home_count DOUBLE,
              to_shop_home_gmv DOUBLE,
              to_live_count DOUBLE,
              to_live_gmv DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "note-1",
                    "青釉杯",
                    "视频",
                    30,
                    1000,
                    500,
                    50,
                    40,
                    20,
                    50,
                    12,
                    0.6,
                    100,
                    80,
                    0.1,
                    0.08,
                    10,
                    8,
                    1000,
                    100,
                    0.1,
                    20,
                    60,
                    600,
                    10,
                    200,
                ),
                (
                    "note-2",
                    "白瓷盘",
                    "图文",
                    None,
                    1000,
                    250,
                    20,
                    10,
                    5,
                    10,
                    8,
                    0.4,
                    25,
                    20,
                    0.08,
                    0.06,
                    2,
                    2,
                    200,
                    20,
                    0.1,
                    5,
                    15,
                    120,
                    3,
                    40,
                ),
            ],
        )
    finally:
        con.close()

    result = run_task("note_funnel", db_path)
    row = result.tables["note_funnel"][0]
    summary = result.tables["note_commercial_funnel"][0]

    assert row["note_type_optional"] == "视频"
    assert row["video_seconds_optional"] == 30
    assert row["share_rate"] == pytest.approx(0.1)
    assert row["read_to_product_click"] == pytest.approx(0.2)
    assert row["product_click_to_order"] == pytest.approx(0.1)
    assert row["gmv_per_1k_impressions"] == pytest.approx(1000)
    assert row["net_note_gmv"] == pytest.approx(900)
    assert summary["impressions"] == 2000
    assert summary["reads"] == 750
    assert summary["product_clicks_optional"] == 125
    assert summary["paid_orders_optional"] == 12
    assert summary["note_gmv_optional"] == 1200
    assert summary["refund_amount_optional"] == 120
    assert summary["net_note_gmv"] == 1080
    assert summary["read_rate"] == pytest.approx(0.375)
    assert summary["read_to_product_click"] == pytest.approx(125 / 750)
    assert summary["product_click_to_order"] == pytest.approx(12 / 125)
    assert summary["gmv_per_1k_impressions"] == pytest.approx(600)
    assert any(finding.title == "笔记商业漏斗已贯通" for finding in result.findings)


def test_note_funnel_does_not_claim_full_funnel_for_partial_commerce_fields(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              impressions DOUBLE,
              reads DOUBLE,
              likes DOUBLE,
              collects DOUBLE,
              comments DOUBLE,
              note_gmv DOUBLE
            )
            """
        )
        con.execute("INSERT INTO notes VALUES ('note-1', 1000, 500, 50, 40, 20, 800)")
    finally:
        con.close()

    result = run_task("note_funnel", db_path)
    finding = next(item for item in result.findings if item.title == "笔记商业指标已扩展")

    assert finding.conclusion == "已纳入当前导出可用的商业指标：成交金额。"
    assert not any(item.title == "笔记商业漏斗已贯通" for item in result.findings)


def test_paid_traffic_efficiency_ranks_campaigns_and_budget_actions(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_campaign.csv"])

    result = run_task("paid_traffic_efficiency", db_path)

    assert result.task_id == "paid_traffic_efficiency"
    assert result.title == "投放效率分析"
    rows = result.tables["paid_traffic_efficiency"]
    assert rows[0]["campaign_name_optional"] == "青釉杯投放"
    assert rows[0]["spend"] == 200
    assert rows[0]["gmv_optional"] == 880
    assert rows[0]["orders_optional"] == 8
    assert rows[0]["order_rate_calc"] == pytest.approx(8 / 260, abs=1e-4)
    assert rows[0]["cpo_calc"] == pytest.approx(25)
    assert rows[0]["roas_calc"] == pytest.approx(4.4)
    assert rows[0]["budget_action"] == "increase"
    summary = result.tables["paid_funnel_summary"][0]
    assert summary["spend"] == 200
    assert summary["impressions"] == 10000
    assert summary["clicks"] == 260
    assert summary["orders_optional"] == 8
    assert summary["order_rate_calc"] == pytest.approx(8 / 260, abs=1e-4)
    assert summary["cpo_calc"] == pytest.approx(25)
    assert result.findings[0].recommended_action


def test_paid_traffic_expands_funnel_and_independent_hierarchy_levels(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE ad_performance_daily (
              date DATE,
              platform VARCHAR,
              campaign_name_optional VARCHAR,
              unit_name_optional VARCHAR,
              creative_name_optional VARCHAR,
              note_id_optional VARCHAR,
              product_id_optional VARCHAR,
              sku_id_optional VARCHAR,
              spend DOUBLE,
              impressions DOUBLE,
              clicks DOUBLE,
              conversions_optional DOUBLE,
              orders_optional DOUBLE,
              gmv_optional DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO ad_performance_daily VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "2026-07-01",
                    "聚光",
                    "夏季计划",
                    "杯具单元",
                    "青釉杯场景",
                    "note-1",
                    "product-1",
                    "sku-1",
                    100,
                    5000,
                    200,
                    30,
                    10,
                    500,
                ),
                (
                    "2026-07-01",
                    "聚光",
                    "夏季计划",
                    "盘具单元",
                    "白瓷盘场景",
                    "note-2",
                    "product-2",
                    "sku-2",
                    50,
                    3000,
                    100,
                    12,
                    4,
                    180,
                ),
            ],
        )
    finally:
        con.close()

    result = run_task("paid_traffic_efficiency", db_path)
    row = result.tables["paid_traffic_efficiency"][0]
    summary = result.tables["paid_funnel_summary"][0]
    hierarchy = result.tables["paid_hierarchy"]

    assert row["unit_name_optional"] == "杯具单元"
    assert row["product_id_optional"] == "product-1"
    assert row["conversions_optional"] == 30
    assert row["orders_optional"] == 10
    assert row["conversion_rate_calc"] == pytest.approx(0.15)
    assert row["order_rate_calc"] == pytest.approx(0.05)
    assert row["cpa_calc"] == pytest.approx(100 / 30, abs=1e-4)
    assert row["cpo_calc"] == pytest.approx(10)
    assert summary["spend"] == 150
    assert summary["impressions"] == 8000
    assert summary["clicks"] == 300
    assert summary["conversions_optional"] == 42
    assert summary["orders_optional"] == 14
    assert summary["gmv_optional"] == 680
    assert summary["cpm_calc"] == pytest.approx(18.75)
    assert {item["level"] for item in hierarchy} == {
        "campaign",
        "unit",
        "creative",
        "note",
        "product",
        "sku",
    }
    campaign = next(item for item in hierarchy if item["level"] == "campaign")
    assert campaign["object_name"] == "夏季计划"
    assert campaign["spend"] == 150
    assert any(finding.title == "投放漏斗已汇总" for finding in result.findings)
    assert any(finding.title == "投放层级已展开" for finding in result.findings)


def test_paid_traffic_uses_reported_roas_when_gmv_is_absent(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE ad_performance_daily (
              date DATE,
              campaign_name_optional VARCHAR,
              spend DOUBLE,
              impressions DOUBLE,
              clicks DOUBLE,
              roas_optional DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO ad_performance_daily VALUES (?, ?, ?, ?, ?, ?)",
            [
                ("2026-07-01", "计划 A", 100, 5000, 100, 4.0),
                ("2026-07-02", "计划 A", 300, 10000, 150, 2.0),
            ],
        )
    finally:
        con.close()

    result = run_task("paid_traffic_efficiency", db_path)
    row = result.tables["paid_traffic_efficiency"][0]
    summary = result.tables["paid_funnel_summary"][0]

    assert row["gmv_optional"] is None
    assert row["roas_calc"] is None
    assert row["roas_reported"] == pytest.approx(2.5)
    assert row["roas_effective"] == pytest.approx(2.5)
    assert row["roas_source"] == "reported_roas"
    assert row["cpm_calc"] == pytest.approx(400 / 15000 * 1000, abs=1e-4)
    assert summary["roas_effective"] == pytest.approx(2.5)
    assert result.findings[0].key_numbers["return_efficiency_source"] == "reported_roas"
    assert row["budget_action"] == "hold"


def test_paid_traffic_coalesces_row_level_roas_and_roi(tmp_path):
    db_path = tmp_path / "mixed-return.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE ad_performance_daily (
              date DATE,
              campaign_name_optional VARCHAR,
              spend DOUBLE,
              impressions DOUBLE,
              clicks DOUBLE,
              roas_optional DOUBLE,
              roi_optional DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO ad_performance_daily VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("2026-07-01", "计划 A", 100, 5000, 100, 4.0, None),
                ("2026-07-02", "计划 A", 100, 5000, 100, None, 4.0),
            ],
        )
    finally:
        con.close()

    result = run_task("paid_traffic_efficiency", db_path)
    row = result.tables["paid_traffic_efficiency"][0]
    assert row["roas_effective"] == pytest.approx(4)
    assert row["roas_source"] == "reported_mixed_roas_roi"
    assert row["budget_action"] == "increase"


def test_paid_traffic_efficiency_handles_weak_export(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_weak.csv"])

    result = run_task("paid_traffic_efficiency", db_path)

    assert result.findings[0].evidence_strength.value in {"weak", "not_judgable"}
    assert result.tables["paid_traffic_efficiency"][0]["budget_action"] == "needs_data"
    assert "成交金额" in result.findings[0].recommended_action


def _make_ad_daily(con, rows):
    con.execute(
        """
        CREATE TABLE ad_performance_daily (
          date DATE,
          campaign_name_optional VARCHAR,
          spend DOUBLE,
          impressions DOUBLE,
          clicks DOUBLE,
          gmv_optional DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO ad_performance_daily VALUES (?, ?, ?, ?, ?, ?)", rows)


def test_paid_traffic_elasticity_flags_saturation_point(tmp_path):
    db_path = tmp_path / "ads.duckdb"
    con = connect(db_path)
    # 16 campaigns across 4 spend quartiles; ROAS falls as spend rises so marginal
    # ROAS crosses below break-even in the 中高投放 band → saturation point.
    tiers = [(25.0, 5.0), (115.0, 3.0), (315.0, 1.5), (1015.0, 0.8)]
    rows = []
    idx = 0
    for base_spend, roas in tiers:
        for offset in (0.0, 10.0, 20.0, 30.0):
            spend = base_spend + offset
            rows.append(("2026-06-01", f"c{idx:02d}", spend, 1000.0, 100.0, spend * roas))
            idx += 1
    _make_ad_daily(con, rows)
    con.close()

    result = run_task("paid_traffic_efficiency", db_path)

    finding = next(f for f in result.findings if f.title == "投放弹性与饱和点")
    assert finding.key_numbers["saturation_band"] == "中高投放"
    assert finding.key_numbers["diminishing"] is True
    curve = result.tables["paid_spend_response"]
    assert len(curve) == 4
    assert sum(1 for r in curve if r["is_saturation"]) == 1
    saturated = next(r for r in curve if r["is_saturation"])
    assert saturated["marginal_roas"] < 1.0


def test_paid_traffic_elasticity_absent_without_gmv(tmp_path):
    db_path = tmp_path / "ads_noreturn.duckdb"
    con = connect(db_path)
    con.execute(
        """
        CREATE TABLE ad_performance_daily (
          date DATE, campaign_name_optional VARCHAR,
          spend DOUBLE, impressions DOUBLE, clicks DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO ad_performance_daily VALUES (?, ?, ?, ?, ?)",
        [("2026-06-01", f"c{i}", 100.0 * (i + 1), 1000.0, 100.0) for i in range(8)],
    )
    con.close()
    result = run_task("paid_traffic_efficiency", db_path)
    assert not any(f.title == "投放弹性与饱和点" for f in result.findings)
    assert "paid_spend_response" not in result.tables


def test_all_tasks_include_paid_traffic_tasks_when_ad_data_missing(tmp_path, fixture_dir):
    db_path = _db(tmp_path, fixture_dir)

    for task_id in ["ad_data_quality_check", "paid_traffic_efficiency"]:
        result = run_task(task_id, db_path)
        assert result.task_id == task_id
        assert result.findings


def test_ad_data_quality_check_reports_creative_export_details(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_creative.csv"])

    result = run_task("ad_data_quality_check", db_path)

    row = result.tables["ad_data_quality"][0]
    assert row["detected_grain"] == "sku"
    assert row["has_click_metrics"] is True
    assert row["creative_link_rows"] == 2


def test_paid_traffic_efficiency_uses_creative_dimension(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_creative.csv"])

    result = run_task("paid_traffic_efficiency", db_path)

    rows = result.tables["paid_traffic_efficiency"]
    assert rows
    assert "creative_name_optional" in rows[0]
    assert {row["creative_name_optional"] for row in rows} == {"青釉杯场景", "白瓷盘场景"}
