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
    status = json.loads((state / "sidecar_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "ready"
    assert status["facts_hash"] == data["facts_hash"]


def test_run_passes_the_published_factbook_to_html(
    tmp_path,
    fixture_dir,
    monkeypatch,
):
    _build_db(tmp_path, fixture_dir)
    import xhs_ceramics_analytics.reporting.html as html_reporting

    original_render_html = html_reporting.render_html
    captured: dict[str, object] = {}

    def _capture(results, **kwargs):
        captured["factbook"] = kwargs.get("factbook")
        return original_render_html(results, **kwargs)

    monkeypatch.setattr(html_reporting, "render_html", _capture)
    result = runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )

    assert result.exit_code == 0, result.output
    assert captured["factbook"] is not None


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
    state = tmp_path / ".xhs-ceramics-analytics"
    assert not (state / "facts.json").exists()
    assert not (state / "results.json").exists()
    status = json.loads((state / "sidecar_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "unavailable"
    assert "unexpected finding shape" in status["error"]


def test_run_invalidates_previous_pair_when_results_build_fails(
    tmp_path,
    fixture_dir,
    monkeypatch,
):
    _build_db(tmp_path, fixture_dir)
    state = tmp_path / ".xhs-ceramics-analytics"
    facts_path = state / "facts.json"
    results_path = state / "results.json"
    facts_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    results_path.write_text('{"facts_hash":"old"}', encoding="utf-8")

    import xhs_ceramics_analytics.reporting.narrative_results as narrative_results

    def _boom(*args, **kwargs):
        raise RuntimeError("results build failed")

    monkeypatch.setattr(narrative_results, "build_narrative_results", _boom)
    result = runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )

    assert result.exit_code == 0, result.output
    assert not facts_path.exists()
    assert not results_path.exists()
    status = json.loads((state / "sidecar_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "unavailable"
    assert "results build failed" in status["error"]


def test_run_invalidates_rolled_back_pair_when_second_replace_fails(
    tmp_path,
    fixture_dir,
    monkeypatch,
):
    _build_db(tmp_path, fixture_dir)
    state = tmp_path / ".xhs-ceramics-analytics"
    facts_path = state / "facts.json"
    results_path = state / "results.json"
    facts_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    results_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    original_replace = Path.replace
    failed = False

    def _replace(path, target):
        nonlocal failed
        if not failed and Path(target).name == "results.json":
            failed = True
            raise OSError("replace results failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", _replace)
    result = runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )

    assert result.exit_code == 0, result.output
    assert not facts_path.exists()
    assert not results_path.exists()
    status = json.loads((state / "sidecar_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "unavailable"
    assert "replace results failed" in status["error"]


def test_run_interrupt_during_pair_publish_invalidates_active_pair(
    tmp_path,
    fixture_dir,
    monkeypatch,
):
    _build_db(tmp_path, fixture_dir)
    state = tmp_path / ".xhs-ceramics-analytics"
    facts_path = state / "facts.json"
    results_path = state / "results.json"
    facts_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    results_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    (state / "sidecar_status.json").write_text(
        '{"status":"ready","facts_hash":"old"}',
        encoding="utf-8",
    )
    original_replace = Path.replace

    def _replace(path, target):
        if Path(target).name == "results.json":
            raise KeyboardInterrupt("publish interrupted")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", _replace)
    result = runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )

    assert result.exit_code == 130
    assert not facts_path.exists()
    assert not results_path.exists()
    status = json.loads((state / "sidecar_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "unavailable"
    assert "publish interrupted" in status["error"]


def test_run_interrupt_during_factbook_build_invalidates_active_pair(
    tmp_path,
    fixture_dir,
    monkeypatch,
):
    _build_db(tmp_path, fixture_dir)
    state = tmp_path / ".xhs-ceramics-analytics"
    facts_path = state / "facts.json"
    results_path = state / "results.json"
    facts_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    results_path.write_text('{"facts_hash":"old"}', encoding="utf-8")
    (state / "sidecar_status.json").write_text(
        '{"status":"ready","facts_hash":"old"}',
        encoding="utf-8",
    )
    import xhs_ceramics_analytics.reporting.facts_export as facts_export

    def _interrupt(*args, **kwargs):
        raise KeyboardInterrupt("factbook build interrupted")

    monkeypatch.setattr(facts_export, "build_factbook", _interrupt)
    result = runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )

    assert result.exit_code == 130
    assert not facts_path.exists()
    assert not results_path.exists()
    status = json.loads((state / "sidecar_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "unavailable"
    assert "factbook build interrupted" in status["error"]


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
