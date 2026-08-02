"""`xhs-ca run` writes results.json that drives narrative prepare end-to-end (P1).

The narrative controller needs a domain-sliced `--results` document. Before P1 no
command produced one, so the host had to hand-fabricate it (and facts.json's empty
``domain_slices`` dict made prepare cap to zero). This proves `run` now emits a real
results.json beside facts.json, and that feeding it to `narrative prepare` caps > 0.
"""
import json
from pathlib import Path

import pytest
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
    # result_tables joins the contract at the CLI level too: it is the numeric-trust
    # source the curated-view engine fills from + the gate polices against.
    assert set(doc) == {
        "canonical_version",
        "facts_hash",
        "registry_hash",
        "metric_mapping",
        "platform_semantics",
        "domain_slices",
        "blocked_modules",
        "result_tables",
    }
    assert isinstance(doc["result_tables"], dict)
    # blocked_modules are {slug, reason} dicts (explicit-slug run → reasons empty).
    assert all(set(b) == {"slug", "reason"} for b in doc["blocked_modules"])


def test_run_sidecars_share_one_metric_snapshot(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = CliRunner().invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "店铺经营诊断报告"],
    )
    assert result.exit_code == 0, result.output
    state = tmp_path / ".xhs-ceramics-analytics"
    facts = json.loads((state / "facts.json").read_text(encoding="utf-8"))
    results = json.loads((state / "results.json").read_text(encoding="utf-8"))

    assert results["canonical_version"] == facts["canonical_version"] == 3
    assert results["facts_hash"] == facts["facts_hash"]
    assert results["registry_hash"] == facts["registry_hash"]
    assert results["metric_mapping"] == facts["metric_mapping"]
    assert results["platform_semantics"] == facts["platform_semantics"]
    assert results["platform_semantics"]["status"] == "observe"
    for domain_slice in results["domain_slices"]:
        for slice_fact in domain_slice["facts"]:
            fact_id = slice_fact.get("fact_id")
            if fact_id is not None:
                assert slice_fact["metric_id"] == facts["facts"][fact_id]["metric_id"]


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
                "--multi-agent-authorized",
            ],
        )
    assert prep.exit_code == 0, prep.output
    slices_doc = json.loads((run_dir / "domain_slices.json").read_text(encoding="utf-8"))
    assert slices_doc["capped"], "prepare must cap > 0 slices from a real results.json"


@pytest.mark.parametrize("status", ["building", "unavailable"])
def test_prepare_rejects_a_non_ready_active_sidecar_pair(tmp_path, fixture_dir, status):
    _build_db(tmp_path, fixture_dir)
    runner = CliRunner()
    runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )
    state = tmp_path / ".xhs-ceramics-analytics"
    (state / "sidecar_status.json").write_text(
        json.dumps({"status": status, "error": "publish interrupted"}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "narrative",
            "prepare",
            "--run-dir",
            str(tmp_path / "run"),
            "--results",
            str(state / "results.json"),
            "--facts",
            str(state / "facts.json"),
            "--name",
            "诊断",
        ],
    )

    assert result.exit_code != 0
    assert "sidecar_status.json" in result.output
    assert status in result.output


def test_prepare_rejects_an_active_sidecar_pair_without_status(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    runner = CliRunner()
    runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )
    state = tmp_path / ".xhs-ceramics-analytics"
    (state / "sidecar_status.json").unlink()

    result = runner.invoke(
        app,
        [
            "narrative",
            "prepare",
            "--run-dir",
            str(tmp_path / "run"),
            "--results",
            str(state / "results.json"),
            "--facts",
            str(state / "facts.json"),
            "--name",
            "诊断",
        ],
    )

    assert result.exit_code != 0
    assert "sidecar_status.json" in result.output
    assert "required" in result.output


def test_prepare_rejects_sidecars_from_different_directories(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    runner = CliRunner()
    runner.invoke(
        app,
        ["run", "core_business_diagnosis", "--project-root", str(tmp_path), "--name", "诊断"],
    )
    state = tmp_path / ".xhs-ceramics-analytics"
    copied_facts = tmp_path / "facts.json"
    copied_facts.write_text(
        (state / "facts.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "narrative",
            "prepare",
            "--run-dir",
            str(tmp_path / "run"),
            "--results",
            str(state / "results.json"),
            "--facts",
            str(copied_facts),
            "--name",
            "诊断",
        ],
    )

    assert result.exit_code != 0
    assert "same directory" in result.output
