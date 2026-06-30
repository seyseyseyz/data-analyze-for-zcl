from pathlib import Path

import pytest

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _build_db(db_path: Path, statements: list[str]) -> Path:
    con = connect(db_path)
    try:
        for statement in statements:
            con.execute(statement)
    finally:
        con.close()
    return db_path


@pytest.mark.parametrize(
    ("task_id", "table_name"),
    [
        ("content_portfolio_optimization", "portfolio_mix"),
        ("weekly_experiment_matrix", "experiment_plan"),
        ("hypothesis_knowledge_base", "hypotheses"),
        ("weekly_business_review", "weekly_sections"),
    ],
)
def test_partial_tables_do_not_crash_task11_tasks(tmp_path: Path, task_id: str, table_name: str):
    db_path = _build_db(
        tmp_path / f"{task_id}.duckdb",
        [
            "CREATE TABLE content_features (note_id VARCHAR)",
            "CREATE TABLE notes (note_id VARCHAR)",
            "CREATE TABLE daily_sku_sales (sku_id VARCHAR)",
            "INSERT INTO content_features VALUES ('n-1')",
            "INSERT INTO notes VALUES ('n-1')",
            "INSERT INTO daily_sku_sales VALUES ('sku-1')",
        ],
    )

    result = run_task(task_id, db_path)

    assert result.task_id == task_id
    assert len(result.findings) == 1
    assert table_name in result.tables


def test_weekly_review_handles_null_daily_sku_sales_summary(tmp_path: Path):
    db_path = _build_db(
        tmp_path / "weekly-null-sales.duckdb",
        [
            """
            CREATE TABLE daily_sku_sales (
              sku_id VARCHAR,
              units DOUBLE,
              gmv DOUBLE
            )
            """,
            "INSERT INTO daily_sku_sales VALUES ('sku-null', NULL, NULL)",
        ],
    )

    result = run_task("weekly_business_review", db_path)
    product_section = next(
        row for row in result.tables["weekly_sections"] if row["section"] == "product_opportunity"
    )

    assert product_section["summary"]
    assert product_section["value"] is None


def test_reshoot_downranks_tiny_samples(tmp_path: Path):
    db_path = _build_db(
        tmp_path / "reshoot-tiny-sample.duckdb",
        [
            """
            CREATE TABLE notes (
              note_id VARCHAR,
              title VARCHAR,
              reads DOUBLE,
              collects DOUBLE
            )
            """,
            "INSERT INTO notes VALUES ('tiny', 'Tiny sample', 1, 1)",
            "INSERT INTO notes VALUES ('strong', 'Strong sample', 1000, 80)",
            "INSERT INTO notes VALUES ('mid', 'Mid sample', 200, 10)",
        ],
    )

    result = run_task("reshoot_repost_candidates", db_path)
    rows = result.tables["reshoot_candidates"]
    tiny_row = next(row for row in rows if row["note_id"] == "tiny")

    assert rows[0]["note_id"] == "strong"
    assert tiny_row["rank"] > 1
    assert tiny_row["needs_more_data"] is True


def test_hypothesis_without_comment_signal_stays_unknown(tmp_path: Path):
    db_path = _build_db(
        tmp_path / "hypothesis-no-comments.duckdb",
        [
            """
            CREATE TABLE comments (
              comment_text VARCHAR
            )
            """,
            "INSERT INTO comments VALUES (NULL)",
        ],
    )

    result = run_task("hypothesis_knowledge_base", db_path)
    demand_row = next(row for row in result.tables["hypotheses"] if row["theme"] == "comment_demand")

    assert demand_row["status"] == "needs_data"
    assert demand_row["label"] == "unknown"
    assert demand_row["metric"] is None
    assert "price" not in str(demand_row["hypothesis"]).lower()
    assert "收集" in str(demand_row["next_test"]) or "评论" in str(demand_row["next_test"])


def test_experiment_matrix_uses_future_default_planning_date(tmp_path: Path):
    db_path = _build_db(
        tmp_path / "experiment-default-date.duckdb",
        [
            "CREATE TABLE notes (note_id VARCHAR)",
            "INSERT INTO notes VALUES ('n-1')",
        ],
    )

    result = run_task("weekly_experiment_matrix", db_path)
    first_row = result.tables["experiment_plan"][0]

    assert first_row["date"] == "2026-07-01"
