import json

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app

runner = CliRunner()


def _write_inputs(tmp_path):
    results = {"domain_slices": [
        {"title": "生意大盘", "facts": [{"metric": "GMV", "value": 100}],
         "reading": {"conclusion": "平稳", "caveats": ["口径：支付时间"]}},
    ]}
    facts = {"facts_hash": "h", "numbers": {"GMV": 100}}
    (tmp_path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    (tmp_path / "facts.json").write_text(json.dumps(facts), encoding="utf-8")


def test_prepare_and_status_json(tmp_path):
    _write_inputs(tmp_path)
    run_dir = tmp_path / "run"
    res = runner.invoke(app, [
        "narrative", "prepare",
        "--run-dir", str(run_dir),
        "--results", str(tmp_path / "results.json"),
        "--facts", str(tmp_path / "facts.json"),
        "--name", "报告",
        "--project-root", str(tmp_path),
    ])
    assert res.exit_code == 0, res.output

    res = runner.invoke(app, ["narrative", "status", "--run-dir", str(run_dir), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["stage"] == "seed"
    assert payload["next_action"]


def test_prepare_force_flag(tmp_path):
    _write_inputs(tmp_path)
    run_dir = tmp_path / "run"
    base = ["narrative", "prepare", "--run-dir", str(run_dir),
            "--results", str(tmp_path / "results.json"),
            "--facts", str(tmp_path / "facts.json"),
            "--name", "报告", "--project-root", str(tmp_path)]
    assert runner.invoke(app, base).exit_code == 0
    # second prepare without --force fails
    assert runner.invoke(app, base).exit_code != 0
    # with --force succeeds
    assert runner.invoke(app, base + ["--force"]).exit_code == 0


def test_finalize_deterministic_cli(tmp_path):
    _write_inputs(tmp_path)
    run_dir = tmp_path / "run"
    runner.invoke(app, [
        "narrative", "prepare", "--run-dir", str(run_dir),
        "--results", str(tmp_path / "results.json"),
        "--facts", str(tmp_path / "facts.json"),
        "--name", "报告", "--project-root", str(tmp_path),
    ])
    res = runner.invoke(app, [
        "narrative", "finalize-deterministic",
        "--run-dir", str(run_dir), "--reason", "denied",
    ])
    assert res.exit_code == 0, res.output
    md = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "报告.md"
    assert md.exists()
    assert "确定性骨架版" in md.read_text(encoding="utf-8")
