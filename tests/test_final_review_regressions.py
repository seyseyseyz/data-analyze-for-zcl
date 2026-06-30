from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.db.build import build_database
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.db.marts import create_note_metrics_view
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.markdown import render_markdown


def test_note_metrics_view_allows_minimal_notes_table(tmp_path: Path):
    con = connect(tmp_path / "analytics.duckdb")
    try:
        con.execute("CREATE TABLE notes (note_id VARCHAR)")
        create_note_metrics_view(con)

        row = con.sql(
            """
            SELECT read_rate, like_rate, collect_rate, comment_rate, engagement_rate
            FROM note_metrics
            """
        ).fetchone()
    finally:
        con.close()

    assert row is None


def test_account_and_funnel_degrade_for_incomplete_notes(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE notes (note_id VARCHAR)")
        con.execute("INSERT INTO notes VALUES ('n1')")
    finally:
        con.close()

    baseline = run_task("account_baseline", db_path)
    funnel = run_task("note_funnel", db_path)

    assert baseline.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert baseline.limitations == ["notes.publish_time column missing."]
    assert baseline.tables["daily_posts"] == []

    assert funnel.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert funnel.tables["note_funnel"][0]["reads"] is None
    assert funnel.limitations == [
        "notes columns missing for funnel rates: impressions, reads, likes, collects, comments."
    ]


def test_build_and_run_all_tolerates_partial_note_export(tmp_path: Path):
    notes_path = tmp_path / "notes.csv"
    notes_path.write_text(
        "note_id,publish_time\nn1,2026-06-01 09:00:00\n",
        encoding="utf-8",
    )
    db_path = tmp_path / "analytics.duckdb"

    build_database(db_path, [notes_path])

    baseline = run_task("account_baseline", db_path)
    funnel = run_task("note_funnel", db_path)

    assert baseline.tables["daily_posts"][0]["posts"] == 1
    assert baseline.tables["daily_posts"][0]["avg_reads"] is None
    assert funnel.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert funnel.limitations == [
        "notes columns missing for funnel rates: impressions, reads, likes, collects, comments."
    ]


def test_markdown_renders_limitations_and_table_preview(tmp_path: Path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute("CREATE TABLE notes (note_id VARCHAR)")
        con.execute("INSERT INTO notes VALUES ('n1')")
    finally:
        con.close()

    report = render_markdown([run_task("note_funnel", db_path)])

    assert "Limitations:" in report
    assert "notes columns missing for funnel rates" in report
    assert "Table `note_funnel`: 1 rows" in report
    assert "| note_id | reads | read_rate | like_rate | collect_rate | comment_rate |" in report


def test_cli_run_writes_markdown_and_html(tmp_path: Path, fixture_dir: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    files = [
        fixture_dir / "notes.csv",
        fixture_dir / "products.csv",
        fixture_dir / "skus.csv",
        fixture_dir / "orders.csv",
        fixture_dir / "content_features.csv",
        fixture_dir / "comments.csv",
        fixture_dir / "calendar_events.csv",
    ]

    build_result = runner.invoke(app, ["build", *map(str, files)])
    run_result = runner.invoke(app, ["run", "all"])

    assert build_result.exit_code == 0
    assert run_result.exit_code == 0
    assert (tmp_path / ".xhs-ceramics-analytics" / "outputs" / "all.md").exists()
    assert (tmp_path / ".xhs-ceramics-analytics" / "outputs" / "all.html").exists()
    assert "all.html" in run_result.output
