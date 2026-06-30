from pathlib import Path

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
