import os
from pathlib import Path

import pytest

from xhs_ceramics_analytics import __version__
from xhs_ceramics_analytics.paths import outputs_dir, project_root, state_dir


def test_package_version_is_defined():
    assert __version__ == "0.1.0"


def test_state_and_outputs_dirs_are_created(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    state = state_dir(root)
    outputs = outputs_dir(root)
    assert state == root / ".xhs-ceramics-analytics"
    assert outputs == state / "outputs"
    assert state.is_dir()
    assert outputs.is_dir()


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


def test_skill_entrypoint_does_not_force_state_into_runtime():
    repo_root = Path(__file__).resolve().parents[1]
    skill_dir = repo_root / "skills" / "data-analyze-for-zcl"
    script = skill_dir / "scripts" / "xhs-ca"
    if not script.exists():
        pytest.skip("source checkout skill package is not present")

    assert 'XHS_CA_PROJECT_ROOT="$runtime_dir"' not in script.read_text(encoding="utf-8")
