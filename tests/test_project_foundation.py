import os
from pathlib import Path

import pytest

from xhs_ceramics_analytics import __version__
from xhs_ceramics_analytics.paths import (
    outputs_dir,
    project_root,
    run_output_dir,
    run_timestamp,
    state_dir,
)


def test_package_version_is_defined():
    assert __version__ == "0.2.0"


def test_state_and_outputs_dirs_are_created(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    state = state_dir(root)
    outputs = outputs_dir(root)
    assert state == root / ".xhs-ceramics-analytics"
    assert outputs == state / "outputs"
    assert state.is_dir()
    assert outputs.is_dir()


def test_run_output_dir_is_a_timestamped_subfolder_of_outputs(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    run_dir = run_output_dir("PiGoo事实层评估", "20260709-134500", root)
    assert run_dir == outputs_dir(root) / "20260709-134500-PiGoo事实层评估"
    assert run_dir.is_dir()


def test_run_output_dir_isolates_successive_productions(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    first = run_output_dir("报告", "20260709-134500", root)
    second = run_output_dir("报告", "20260709-140212", root)
    assert first != second  # each production is uniquely addressable
    assert first.is_dir() and second.is_dir()


def test_run_timestamp_format_and_env_override(monkeypatch):
    # Wall-clock stamp is YYYYMMDD-HHMMSS; an env override makes a production folder
    # reproducible (used by tests and for a deterministic re-render).
    monkeypatch.setenv("XHS_CA_RUN_TIMESTAMP", "20260709-134500")
    assert run_timestamp() == "20260709-134500"
    monkeypatch.delenv("XHS_CA_RUN_TIMESTAMP", raising=False)
    stamp = run_timestamp()
    assert len(stamp) == len("20260709-134500")
    assert stamp[8] == "-" and stamp.replace("-", "").isdigit()


def test_project_root_falls_back_to_current_tree(tmp_path: Path, monkeypatch):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert project_root() == nested


def test_project_root_uses_environment_override(tmp_path: Path, monkeypatch):
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir()
    monkeypatch.setenv("XHS_CA_PROJECT_ROOT", str(runtime_root))

    assert project_root() == runtime_root.resolve()


def test_published_skill_bundles_runtime_and_entrypoints():
    repo_root = Path(__file__).resolve().parents[1]
    skill_dir = repo_root / "skills" / "data-analyze-for-zcl"
    if not skill_dir.exists():
        pytest.skip("source checkout skill package is not present")

    runtime_dir = skill_dir / "assets" / "xhs-ca"

    assert (runtime_dir / "pyproject.toml").exists()
    assert (runtime_dir / "xhs_ceramics_analytics" / "cli.py").exists()
    assert (runtime_dir / "references" / "data_contract.md").exists()
    assert (runtime_dir / "task_templates" / "weekly_business_review.md").exists()
    assert os.access(skill_dir / "scripts" / "bootstrap", os.X_OK)
    assert os.access(skill_dir / "scripts" / "xhs-ca", os.X_OK)
    assert (skill_dir / "scripts" / "bootstrap_runtime.py").exists()


def test_skill_entrypoint_does_not_force_state_into_runtime():
    repo_root = Path(__file__).resolve().parents[1]
    skill_dir = repo_root / "skills" / "data-analyze-for-zcl"
    script = skill_dir / "scripts" / "xhs-ca"
    if not script.exists():
        pytest.skip("source checkout skill package is not present")

    assert 'XHS_CA_PROJECT_ROOT="$runtime_dir"' not in script.read_text(encoding="utf-8")
