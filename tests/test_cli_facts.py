"""`xhs-ca facts` emits a deterministic facts.json with a hash."""
import json
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.db.build import build_database


def _build_db(tmp_path: Path, fixture_dir: Path) -> None:
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir(parents=True, exist_ok=True)
    build_database(
        db_path=state / "analytics.duckdb",
        files=[
            fixture_dir / "business_overview_daily.csv",
            fixture_dir / "traffic_source.csv",
        ],
    )


def test_facts_command_writes_json_and_hash(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        ["facts", "core_business_diagnosis", "--project-root", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    facts_json = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "facts.json"
    assert facts_json.exists()
    data = json.loads(facts_json.read_text(encoding="utf-8"))
    assert "facts_hash" in data and len(data["facts_hash"]) == 64
    assert "facts" in data


def test_facts_command_is_deterministic(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    runner = CliRunner()
    runner.invoke(app, ["facts", "core_business_diagnosis", "--project-root", str(tmp_path)])
    first = (tmp_path / ".xhs-ceramics-analytics" / "outputs" / "facts.json").read_text("utf-8")
    runner.invoke(app, ["facts", "core_business_diagnosis", "--project-root", str(tmp_path)])
    second = (tmp_path / ".xhs-ceramics-analytics" / "outputs" / "facts.json").read_text("utf-8")
    assert first == second  # byte-identical re-run
