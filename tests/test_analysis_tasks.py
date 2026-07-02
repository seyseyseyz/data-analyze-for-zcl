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
    assert rows[0]["roas_calc"] == pytest.approx(4.4)
    assert rows[0]["budget_action"] == "increase"
    assert result.findings[0].recommended_action


def test_paid_traffic_efficiency_handles_weak_export(tmp_path, fixture_dir):
    db_path = tmp_path / "analytics.duckdb"
    build_database(db_path, [fixture_dir / "ads_weak.csv"])

    result = run_task("paid_traffic_efficiency", db_path)

    assert result.findings[0].evidence_strength.value in {"weak", "not_judgable"}
    assert result.tables["paid_traffic_efficiency"][0]["budget_action"] == "needs_data"
    assert "成交金额" in result.findings[0].recommended_action


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
