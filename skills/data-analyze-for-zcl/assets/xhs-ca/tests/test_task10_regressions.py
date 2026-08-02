from pathlib import Path

import pytest

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def test_cover_effect_uses_feature_counts_without_notes(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE content_features (
              note_id VARCHAR,
              composition_type VARCHAR,
              copy_angle VARCHAR
            )
            """
        )
        con.execute(
            """
            INSERT INTO content_features VALUES
              ('n1', 'single_product', 'lifestyle'),
              ('n2', 'single_product', 'gift'),
              ('n3', 'table_setting', 'lifestyle')
            """
        )
    finally:
        con.close()

    result = run_task("cover_style_effect", db_path)

    assert result.tables["cover_effects"][0]["composition_type"] == "single_product"
    assert result.tables["cover_effects"][0]["notes"] == 2
    assert result.tables["cover_effects"][0]["avg_reads"] is None
    assert result.limitations == ["笔记指标不可用，封面排序仅使用特征计数。"]


def test_copy_effect_missing_metric_columns_does_not_crash(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE content_features (
              note_id VARCHAR,
              copy_angle VARCHAR
            )
            """
        )
        con.execute("INSERT INTO content_features VALUES ('n1', 'gift')")
        con.execute("CREATE TABLE notes (note_id VARCHAR, reads INTEGER)")
        con.execute("INSERT INTO notes VALUES ('n1', 100)")
    finally:
        con.close()

    result = run_task("copy_angle_effect", db_path)
    row = result.tables["copy_effects"][0]

    assert row["copy_angle"] == "gift"
    assert row["avg_reads"] == 100
    assert row["avg_collects"] is None
    assert result.limitations == ["notes 表的阅读/收藏指标不完整。"]


def test_content_grouping_uses_full_commercial_metrics_and_note_sample_size(tmp_path: Path):
    db_path = tmp_path / "content-commerce.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE content_features (
              note_id VARCHAR,
              composition_type VARCHAR,
              copy_angle VARCHAR
            )
            """
        )
        con.executemany(
            "INSERT INTO content_features VALUES (?, ?, ?)",
            [
                ("n1", "single_product", "gift"),
                ("n2", "single_product", "gift"),
                ("n3", "table_setting", "lifestyle"),
            ],
        )
        con.execute(
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              impressions DOUBLE,
              reads DOUBLE,
              collects DOUBLE,
              product_clicks DOUBLE,
              note_paid_orders DOUBLE,
              note_gmv DOUBLE,
              note_refund_amount_pay DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("n1", 1000, 500, 50, 100, 10, 1000, 100),
                ("n2", 500, 200, 20, 40, 4, 400, 40),
                ("n3", 800, 240, 12, 24, 2, 160, 32),
            ],
        )
    finally:
        con.close()

    cover = run_task("cover_style_effect", db_path)
    copy = run_task("copy_angle_effect", db_path)
    portfolio = run_task("content_portfolio_optimization", db_path)

    single = next(
        row for row in cover.tables["cover_effects"] if row["composition_type"] == "single_product"
    )
    gift = next(row for row in copy.tables["copy_effects"] if row["copy_angle"] == "gift")
    mix = next(row for row in portfolio.tables["portfolio_mix"] if row["copy_angle"] == "gift")
    assert single["notes"] == 2
    assert single["read_rate"] == pytest.approx(700 / 1500, abs=1e-4)
    assert single["read_to_product_click"] == pytest.approx(140 / 700, abs=1e-4)
    assert single["product_click_to_order"] == pytest.approx(14 / 140, abs=1e-4)
    assert single["gmv_per_1k_impressions"] == pytest.approx(1400 / 1500 * 1000, abs=1e-4)
    assert single["net_note_gmv"] == 1260
    assert gift["notes"] == 2
    assert mix["paid_orders"] == 14
    assert cover.findings[0].key_numbers["notes"] == 3


def test_content_product_effects_degrade_when_feature_columns_missing(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE content_features (note_id VARCHAR)")
        con.execute("INSERT INTO content_features VALUES ('n1')")
    finally:
        con.close()

    for task_id, table_name in [
        ("cover_style_effect", "cover_effects"),
        ("copy_angle_effect", "copy_effects"),
        ("product_content_interaction", "product_interactions"),
    ]:
        result = run_task(task_id, db_path)
        assert result.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
        assert result.tables[table_name] == []
        assert result.limitations


def test_product_interaction_without_links_is_content_feature_hypothesis(tmp_path: Path):
    db_path = tmp_path / "content-only-interaction.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE content_features (
              note_id VARCHAR,
              composition_type VARCHAR,
              copy_angle VARCHAR
            )
            """
        )
        con.execute("INSERT INTO content_features VALUES ('n1', 'single', 'gift')")
        con.execute("CREATE TABLE notes (note_id VARCHAR, reads DOUBLE, collects DOUBLE)")
        con.execute("INSERT INTO notes VALUES ('n1', 100, 10)")
    finally:
        con.close()

    result = run_task("product_content_interaction", db_path)
    finding = result.findings[0]

    assert result.task_id == "product_content_interaction"
    assert "product_interactions" in result.tables
    assert "内容特征组合" in finding.title
    assert "商品" not in finding.conclusion
    assert "显式 note-SKU 关联" in " ".join(finding.caveats)


def test_product_interaction_ignores_unrelated_note_sku_links(tmp_path: Path):
    db_path = tmp_path / "unrelated-link.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            "CREATE TABLE content_features (note_id VARCHAR, composition_type VARCHAR, copy_angle VARCHAR)"
        )
        con.execute("INSERT INTO content_features VALUES ('n1', 'single', 'gift')")
        con.execute("CREATE TABLE notes (note_id VARCHAR, reads DOUBLE, collects DOUBLE)")
        con.execute("INSERT INTO notes VALUES ('n1', 100, 10)")
        con.execute("CREATE TABLE note_sku_links (note_id VARCHAR, sku_id VARCHAR)")
        con.execute("INSERT INTO note_sku_links VALUES ('other-note', 's1')")
    finally:
        con.close()

    result = run_task("product_content_interaction", db_path)
    assert result.findings[0].title == "内容特征组合假设"
    assert all("sku_id" not in row for row in result.tables["product_interactions"])


@pytest.mark.parametrize(
    ("task_id", "table_name"),
    [
        ("cover_style_effect", "cover_effects"),
        ("copy_angle_effect", "copy_effects"),
        ("product_content_interaction", "product_interactions"),
    ],
)
def test_content_effects_report_unmatched_note_metrics(
    tmp_path: Path,
    task_id: str,
    table_name: str,
):
    db_path = tmp_path / f"{task_id}-unmatched.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE content_features (
              note_id VARCHAR,
              composition_type VARCHAR,
              copy_angle VARCHAR
            )
            """
        )
        con.execute("INSERT INTO content_features VALUES ('feature-only', 'single', 'gift')")
        con.execute(
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              reads DOUBLE,
              collects DOUBLE
            )
            """
        )
        con.execute("INSERT INTO notes VALUES ('other-note', 100, 10)")
    finally:
        con.close()

    result = run_task(task_id, db_path)
    row = result.tables[table_name][0]

    assert row["avg_reads"] is None
    assert row["avg_collects"] is None
    assert result.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert "没有匹配的笔记指标" in " ".join(result.limitations)


def test_product_opportunity_lists_skus_without_sales(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE skus (sku_id VARCHAR, sku_name VARCHAR)")
        con.execute("INSERT INTO skus VALUES ('s1', '青釉咖啡杯')")
    finally:
        con.close()

    result = run_task("product_opportunity_matrix", db_path)
    row = result.tables["product_opportunities"][0]

    assert row["sku_id"] == "s1"
    assert row["sku_name"] == "青釉咖啡杯"
    assert row["units"] is None
    assert row["opportunity_type"] == "needs_sales_data"
    assert result.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert result.limitations == ["缺少 daily_sku_sales 表。"]


def test_product_opportunity_uses_sales_without_sku_table(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            """
            CREATE TABLE daily_sku_sales (
              date DATE,
              sku_id VARCHAR,
              units DOUBLE,
              gmv DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_sku_sales VALUES
              (DATE '2026-06-01', 's1', 2, 258),
              (DATE '2026-06-02', 's1', 2, 258)
            """
        )
    finally:
        con.close()

    result = run_task("product_opportunity_matrix", db_path)
    row = result.tables["product_opportunities"][0]

    assert row["sku_id"] == "s1"
    assert row["sku_name"] == "s1"
    assert row["units"] == 4
    assert row["opportunity_type"] == "sales_response_present"
    assert result.findings[0].evidence_strength == EvidenceStrength.WEAK
    assert result.limitations == ["缺少 skus 表，SKU 名称使用 sku_id。"]


def test_product_opportunity_describes_total_sales_as_sales_performance(
    tmp_path: Path,
):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE skus (sku_id VARCHAR, sku_name VARCHAR)")
        con.execute("INSERT INTO skus VALUES ('s1', '青釉咖啡杯')")
        con.execute(
            """
            CREATE TABLE daily_sku_sales (
              date DATE,
              sku_id VARCHAR,
              units DOUBLE,
              gmv DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_sku_sales VALUES
              (DATE '2026-06-01', 's1', 4, 516)
            """
        )
    finally:
        con.close()

    result = run_task("product_opportunity_matrix", db_path)

    assert "销量表现" in result.findings[0].conclusion
    assert "销售响应" not in result.findings[0].conclusion


def test_product_opportunity_uses_velocity_and_inventory_not_fixed_units_threshold(
    tmp_path: Path,
):
    db_path = tmp_path / "inventory.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            "CREATE TABLE skus (sku_id VARCHAR, sku_name VARCHAR, inventory_optional DOUBLE)"
        )
        con.executemany(
            "INSERT INTO skus VALUES (?, ?, ?)",
            [("s1", "青釉杯", 1), ("s2", "白瓷盘", 100)],
        )
        con.execute(
            """
            CREATE TABLE daily_sku_sales (
              date DATE,
              sku_id VARCHAR,
              units DOUBLE,
              gmv DOUBLE
            )
            """
        )
        con.executemany(
            "INSERT INTO daily_sku_sales VALUES (?, ?, ?, ?)",
            [
                ("2026-06-01", "s1", 1, 100),
                ("2026-06-01", "s2", 1, 100),
            ],
        )
    finally:
        con.close()

    result = run_task("product_opportunity_matrix", db_path)
    rows = {row["sku_id"]: row for row in result.tables["product_opportunities"]}

    assert rows["s1"]["units_per_active_day"] == pytest.approx(1)
    assert rows["s1"]["inventory_cover_active_days"] == pytest.approx(1)
    assert rows["s1"]["opportunity_type"] == "low_inventory_risk"
    assert rows["s2"]["opportunity_type"] == "sales_response_present"
    assert rows["s2"]["units"] == 1


def test_product_opportunity_evidence_reason_does_not_assume_missing_note_links(
    tmp_path: Path,
):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE skus (sku_id VARCHAR, sku_name VARCHAR)")
        con.execute("INSERT INTO skus VALUES ('s1', '青釉咖啡杯')")
        con.execute(
            """
            CREATE TABLE daily_sku_sales (
              date DATE,
              sku_id VARCHAR,
              units DOUBLE,
              gmv DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO daily_sku_sales VALUES
              (DATE '2026-06-01', 's1', 4, 516)
            """
        )
        con.execute(
            """
            CREATE TABLE note_sku_links (
              note_id VARCHAR,
              sku_id VARCHAR
            )
            """
        )
        con.execute("INSERT INTO note_sku_links VALUES ('n1', 's1')")
    finally:
        con.close()

    result = run_task("product_opportunity_matrix", db_path)

    assert result.findings[0].evidence_reason
    assert "缺少显式 note-SKU 关联" not in result.findings[0].evidence_reason


def test_product_opportunity_does_not_treat_empty_sales_table_as_sales_evidence(
    tmp_path: Path,
):
    db_path = tmp_path / "empty-sales.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE skus (sku_id VARCHAR, sku_name VARCHAR)")
        con.execute("INSERT INTO skus VALUES ('s1', '青釉咖啡杯')")
        con.execute(
            """
            CREATE TABLE daily_sku_sales (
              date DATE,
              sku_id VARCHAR,
              units DOUBLE,
              gmv DOUBLE
            )
            """
        )
    finally:
        con.close()

    result = run_task("product_opportunity_matrix", db_path)
    row = result.tables["product_opportunities"][0]

    assert row["sku_id"] == "s1"
    assert row["units"] is None
    assert row["gmv"] is None
    assert row["opportunity_type"] == "needs_sales_data"
    assert result.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert "没有可用的 SKU 销售记录" in " ".join(result.limitations)
