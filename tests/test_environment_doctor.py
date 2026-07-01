import os
import sys
import builtins
import importlib
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.doctor import CheckStatus, run_checks


def test_doctor_cli_reports_environment_status(tmp_path: Path, monkeypatch):
    from xhs_ceramics_analytics.cli import app

    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    result = CliRunner().invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "Environment Doctor" in result.output
    assert "Python >= 3.11" in result.output
    assert "Project root" in result.output
    assert "NEXT:" in result.output


def test_doctor_strict_accepts_data_directory_without_pyproject(
    tmp_path: Path, monkeypatch
):
    from xhs_ceramics_analytics.cli import app

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    xhs_ca = bin_dir / "xhs-ca"
    xhs_ca.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    xhs_ca.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    result = CliRunner().invoke(app, ["doctor", "--strict", "--project-root", str(tmp_path)])

    assert result.exit_code == 0
    assert "Data/output root" in result.output
    assert "pyproject.toml not found" not in result.output


def test_cli_import_does_not_require_analytics_dependencies(monkeypatch):
    real_import = builtins.__import__

    def block_duckdb_import(name, *args, **kwargs):
        if name == "duckdb":
            raise ModuleNotFoundError("blocked duckdb for doctor import test")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", block_duckdb_import)
    sys.modules.pop("xhs_ceramics_analytics.cli", None)

    module = importlib.import_module("xhs_ceramics_analytics.cli")

    assert hasattr(module, "app")


def test_run_checks_marks_missing_required_dependency(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    checks = run_checks(
        root=tmp_path,
        required_modules=("definitely_missing_xhs_dependency",),
        python_version=sys.version_info,
        in_virtualenv=True,
        command_available=lambda _: False,
    )

    missing = [check for check in checks if check.status == CheckStatus.MISSING]

    assert any("definitely_missing_xhs_dependency" in check.name for check in missing)
    assert any("xhs-ca command" in check.name for check in missing)


def test_run_checks_marks_old_python_as_missing(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    checks = run_checks(
        root=tmp_path,
        required_modules=(),
        python_version=(3, 10),
        in_virtualenv=True,
        command_available=lambda _: True,
    )

    python_check = next(check for check in checks if check.name == "Python >= 3.11")

    assert python_check.status == CheckStatus.MISSING
    assert "Install Python 3.11" in str(python_check.next_step)


def test_bootstrap_script_is_executable_and_runs_doctor():
    script = Path("scripts/bootstrap")

    assert script.exists()
    assert os.access(script, os.X_OK)

    body = script.read_text(encoding="utf-8")
    assert "python3 -m venv .venv" in body
    assert 'python -m pip install -e ".[dev]"' in body
    assert "xhs-ca doctor" in body
