from pathlib import Path

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
