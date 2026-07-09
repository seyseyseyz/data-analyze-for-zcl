import json
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.db.build import build_database

runner = CliRunner()


def _build_db(tmp_path: Path, fixture_dir: Path) -> None:
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir(parents=True, exist_ok=True)
    build_database(
        db_path=state / "analytics.duckdb",
        files=[fixture_dir / "business_overview_daily.csv", fixture_dir / "traffic_source.csv"],
    )


def test_run_emits_facts_json_into_state_dir(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = runner.invoke(app, ["run", "core_business_diagnosis", "--project-root", str(tmp_path),
                                 "--name", "诊断"])
    assert result.exit_code == 0, result.output
    state = tmp_path / ".xhs-ceramics-analytics"
    outputs = state / "outputs" / "20260101-000000-诊断"
    assert (outputs / "诊断.md").exists()
    # facts.json is the cache-key sidecar in the state dir, NOT a deliverable in outputs/.
    facts = state / "facts.json"
    assert facts.exists()
    assert not (outputs / "facts.json").exists()
    data = json.loads(facts.read_text(encoding="utf-8"))
    assert len(data["facts_hash"]) == 64


def test_run_survives_facts_json_failure(tmp_path, fixture_dir, monkeypatch):
    # facts.json is a non-deliverable sidecar; if its build raises, the md/html
    # deliverables must still land and the command must exit 0 (degrade, don't abort).
    _build_db(tmp_path, fixture_dir)
    import xhs_ceramics_analytics.reporting.facts_export as fx

    def _boom(*a, **k):
        raise RuntimeError("unexpected finding shape")

    monkeypatch.setattr(fx, "build_factbook", _boom)
    result = runner.invoke(app, ["run", "core_business_diagnosis", "--project-root", str(tmp_path),
                                 "--name", "诊断"])
    assert result.exit_code == 0, result.output
    outputs = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "20260101-000000-诊断"
    assert (outputs / "诊断.md").exists()
    assert (outputs / "诊断.html").exists()
    assert not (tmp_path / ".xhs-ceramics-analytics" / "facts.json").exists()


def test_skeleton_appends_telemetry_record(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = runner.invoke(app, ["skeleton", "core_business_diagnosis",
                                 "--project-root", str(tmp_path), "--name", "骨架"])
    assert result.exit_code == 0, result.output
    runs = tmp_path / ".xhs-ceramics-analytics" / "report_runs.jsonl"
    assert runs.exists()
    record = json.loads(runs.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["mode"] == "skeleton"
    assert record["degradation_reason"] is not None
