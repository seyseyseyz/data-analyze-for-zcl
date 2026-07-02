import importlib.util
import os
import sys
from pathlib import Path


def load_bootstrap_runtime():
    test_path = Path(__file__).resolve()
    candidates = [
        test_path.parents[1] / "scripts" / "bootstrap_runtime.py",
        test_path.parents[3] / "scripts" / "bootstrap_runtime.py",
    ]
    module_path = next((path for path in candidates if path.exists()), candidates[0])
    spec = importlib.util.spec_from_file_location("bootstrap_runtime", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_version_tuple_accepts_python_311_or_newer():
    helper = load_bootstrap_runtime()

    assert helper.is_compatible_version((3, 11, 0))
    assert helper.is_compatible_version((3, 12, 4))
    assert not helper.is_compatible_version((3, 10, 9))


def test_candidate_order_prefers_explicit_env_then_private_python(tmp_path, monkeypatch):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    private_python = runtime_dir / ".runtime" / "python" / "bin" / "python3"
    private_python.parent.mkdir(parents=True)
    private_python.write_text("#!/bin/sh\n", encoding="utf-8")
    env_python = tmp_path / "custom-python"
    env_python.write_text("#!/bin/sh\n", encoding="utf-8")

    env = {"XHS_CA_PYTHON": str(env_python), "PATH": os.environ.get("PATH", "")}
    candidates = list(helper.iter_python_candidates(runtime_dir, env))

    assert candidates[0] == ("XHS_CA_PYTHON", env_python)
    assert candidates[1] == ("private runtime", private_python)


def test_missing_python_repair_shell_is_terminal_only():
    helper = load_bootstrap_runtime()
    shell = helper.repair_missing_python_shell(Path("/Users/example/.agents/skills/data-analyze-for-zcl"))

    assert "Copy the whole command block below into macOS Terminal" not in shell
    assert "python3.12" in shell
    assert "python3.11" in shell
    assert "rm -rf \"$RUNTIME_DIR/.venv\"" in shell
    assert "Codex" not in shell


def test_install_repair_shell_uses_temporary_pip_cache():
    helper = load_bootstrap_runtime()
    shell = helper.repair_install_shell(Path("/Users/example/.agents/skills/data-analyze-for-zcl"))

    assert "PIP_CACHE_DIR=\"$(mktemp -d)\"" in shell
    assert "pip install -e \"$RUNTIME_DIR[dev]\"" in shell
    assert "\"$SKILL_DIR/scripts/xhs-ca\" doctor --strict" in shell


def test_venv_needs_rebuild_when_python_is_missing(tmp_path):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    (runtime_dir / ".venv").mkdir(parents=True)

    assert helper.venv_needs_rebuild(runtime_dir)


def test_package_check_reports_missing_runtime_assets(tmp_path):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    skill_dir = tmp_path / "skill"

    missing = helper.missing_package_files(runtime_dir, skill_dir)

    assert runtime_dir / "pyproject.toml" in missing
    assert runtime_dir / "xhs_ceramics_analytics" in missing
    assert skill_dir / "scripts" / "xhs-ca" in missing


def test_python_version_returns_none_for_non_executable_file(tmp_path):
    helper = load_bootstrap_runtime()
    binary = tmp_path / "python3"
    binary.write_text("not executable\n", encoding="utf-8")

    assert helper.python_version(binary) is None


def test_main_prints_repair_kit_for_incomplete_skill_package(tmp_path, capsys):
    helper = load_bootstrap_runtime()
    runtime_dir = tmp_path / "runtime"
    skill_dir = tmp_path / "skill"
    runtime_dir.mkdir()
    skill_dir.mkdir()

    exit_code = helper.main(
        [
            "--runtime-dir",
            str(runtime_dir),
            "--skill-dir",
            str(skill_dir),
            "--doctor-root",
            str(runtime_dir),
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Copy the whole command block below into macOS Terminal" in captured.err
    assert "npx skills add seyseyseyz/data-analyze-for-zcl -g -y" in captured.err
    assert "Traceback" not in captured.err
