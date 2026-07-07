"""`xhs-ca run` writes results.json that drives narrative prepare end-to-end (P1).

The narrative controller needs a domain-sliced `--results` document. Before P1 no
command produced one, so the host had to hand-fabricate it (and facts.json's empty
``domain_slices`` dict made prepare cap to zero). This proves `run` now emits a real
results.json beside facts.json, and that feeding it to `narrative prepare` caps > 0.
"""
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


def test_run_writes_results_json_with_domain_slices(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "店铺经营诊断报告"],
    )
    assert result.exit_code == 0, result.output
    results_json = tmp_path / ".xhs-ceramics-analytics" / "results.json"
    assert results_json.exists(), "run must emit results.json beside facts.json"
    doc = json.loads(results_json.read_text(encoding="utf-8"))
    assert doc["domain_slices"], "results.json domain_slices must be non-empty"
    assert set(doc) == {"domain_slices", "blocked_modules"}
    # blocked_modules are {slug, reason} dicts (explicit-slug run → reasons empty).
    assert all(set(b) == {"slug", "reason"} for b in doc["blocked_modules"])


def test_run_auto_enriches_blocked_modules_with_coverage_reasons(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app, ["run", "auto", "--project-root", str(tmp_path), "--name", "店铺经营诊断报告"]
    )
    assert result.exit_code == 0, result.output
    doc = json.loads(
        (tmp_path / ".xhs-ceramics-analytics" / "results.json").read_text(encoding="utf-8")
    )
    blocked = doc["blocked_modules"]
    assert blocked, "auto run over a thin export must report blocked modules"
    # at least one blocked module carries a non-empty coverage reason (what unlocks it).
    assert any(b["reason"] for b in blocked), "auto path must enrich block reasons"


def test_results_json_drives_prepare_to_capped_gt_zero(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    runner = CliRunner()
    runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "店铺经营诊断报告"],
    )
    state = tmp_path / ".xhs-ceramics-analytics"
    run_dir = tmp_path / "run"
    prep = runner.invoke(
        app,
        [
            "narrative",
            "prepare",
            "--run-dir",
            str(run_dir),
            "--results",
            str(state / "results.json"),
            "--facts",
            str(state / "facts.json"),
            "--name",
            "店铺经营诊断报告",
        ],
    )
    assert prep.exit_code == 0, prep.output
    slices_doc = json.loads((run_dir / "domain_slices.json").read_text(encoding="utf-8"))
    assert slices_doc["capped"], "prepare must cap > 0 slices from a real results.json"
