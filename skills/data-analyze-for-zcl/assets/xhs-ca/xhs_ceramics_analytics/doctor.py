import importlib.util
import shutil
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from xhs_ceramics_analytics.paths import project_root, state_dir


MIN_PYTHON = (3, 11)
REQUIRED_MODULES = (
    "duckdb",
    "pandas",
    "openpyxl",
    "pydantic",
    "yaml",
    "jinja2",
    "plotly",
    "typer",
    "rapidfuzz",
)


class CheckStatus(StrEnum):
    OK = "ok"
    WARN = "warn"
    MISSING = "missing"


@dataclass(frozen=True)
class Check:
    name: str
    status: CheckStatus
    detail: str
    next_step: str | None = None


def run_checks(
    root: Path | None = None,
    required_modules: Iterable[str] = REQUIRED_MODULES,
    python_version: object = sys.version_info,
    in_virtualenv: bool | None = None,
    command_available: Callable[[str], bool] | None = None,
) -> list[Check]:
    resolved_root = (root or project_root()).resolve()
    command_available = command_available or _command_available
    if in_virtualenv is None:
        in_virtualenv = _in_virtualenv()

    checks = [
        _python_check(python_version),
        _project_root_check(resolved_root),
        _virtualenv_check(in_virtualenv),
        _command_check(command_available),
        _state_dir_check(resolved_root),
    ]
    checks.extend(_module_check(module_name) for module_name in required_modules)
    return checks


def has_blocking_failures(checks: Iterable[Check]) -> bool:
    return any(check.status == CheckStatus.MISSING for check in checks)


def next_steps(checks: Iterable[Check]) -> list[str]:
    steps = []
    seen = set()
    for check in checks:
        if check.next_step and check.next_step not in seen:
            steps.append(check.next_step)
            seen.add(check.next_step)
    if not steps:
        steps.append("Run xhs-ca build ... and xhs-ca run all.")
    return steps


def _python_check(python_version: object) -> Check:
    if hasattr(python_version, "major") and hasattr(python_version, "minor"):
        major = int(python_version.major)
        minor = int(python_version.minor)
    else:
        major = int(python_version[0])
        minor = int(python_version[1])
    version_text = f"{major}.{minor}"
    if (major, minor) < MIN_PYTHON:
        return Check(
            name="Python >= 3.11",
            status=CheckStatus.MISSING,
            detail=f"found Python {version_text}",
            next_step="Install Python 3.11 or newer, then run ./scripts/bootstrap.",
        )
    return Check("Python >= 3.11", CheckStatus.OK, f"found Python {version_text}")


def _project_root_check(root: Path) -> Check:
    if (root / "pyproject.toml").exists():
        return Check("Project root", CheckStatus.OK, str(root))
    return Check(
        name="Project root",
        status=CheckStatus.MISSING,
        detail=f"pyproject.toml not found under {root}",
        next_step="Run commands from the xiaohongshu-ceramics-analytics project root.",
    )


def _virtualenv_check(in_virtualenv: bool) -> Check:
    if in_virtualenv:
        return Check("Virtual environment", CheckStatus.OK, "active")
    return Check(
        name="Virtual environment",
        status=CheckStatus.WARN,
        detail="not active",
        next_step="./scripts/bootstrap",
    )


def _command_check(command_available: Callable[[str], bool]) -> Check:
    if command_available("xhs-ca"):
        return Check("xhs-ca command", CheckStatus.OK, "available on PATH")
    return Check(
        name="xhs-ca command",
        status=CheckStatus.MISSING,
        detail="not available on PATH",
        next_step='python -m pip install -e ".[dev]"',
    )


def _state_dir_check(root: Path) -> Check:
    try:
        directory = state_dir(root)
        probe = directory / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        return Check(
            name="State directory",
            status=CheckStatus.MISSING,
            detail=str(exc),
            next_step="Choose a writable project directory.",
        )
    return Check("State directory", CheckStatus.OK, str(directory))


def _module_check(module_name: str) -> Check:
    if importlib.util.find_spec(module_name) is not None:
        return Check(f"Python dependency: {module_name}", CheckStatus.OK, "importable")
    return Check(
        name=f"Python dependency: {module_name}",
        status=CheckStatus.MISSING,
        detail="not importable",
        next_step='python -m pip install -e ".[dev]"',
    )


def _in_virtualenv() -> bool:
    base_prefix = getattr(sys, "base_prefix", sys.prefix)
    real_prefix = getattr(sys, "real_prefix", None)
    return bool(real_prefix) or sys.prefix != base_prefix


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None
