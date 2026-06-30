from pathlib import Path

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
    assert result.limitations == [
        "notes metrics unavailable; cover ranking uses feature counts only."
    ]


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
    assert result.limitations == ["notes read/collect metrics incomplete."]


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
    assert result.limitations == ["daily_sku_sales table missing."]


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
    assert result.findings[0].evidence_strength == EvidenceStrength.MEDIUM
    assert result.limitations == ["skus table missing; SKU names use sku_id."]
