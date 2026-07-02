#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


MIN_VERSION = (3, 11)


@dataclass(frozen=True)
class PythonCandidate:
    source: str
    path: Path
    version: tuple[int, int, int]


def is_compatible_version(version: tuple[int, int, int]) -> bool:
    return version[:2] >= MIN_VERSION


def iter_python_candidates(
    runtime_dir: Path, env: Mapping[str, str] | None = None
) -> list[tuple[str, Path]]:
    env = env or os.environ
    candidates: list[tuple[str, Path]] = []
    configured = env.get("XHS_CA_PYTHON")
    if configured:
        candidates.append(("XHS_CA_PYTHON", Path(configured).expanduser()))

    private_python = runtime_dir / ".runtime" / "python" / "bin" / "python3"
    candidates.append(("private runtime", private_python))

    for name in ("python3.12", "python3.11", "python3"):
        resolved = shutil.which(name, path=env.get("PATH"))
        if resolved:
            candidates.append((name, Path(resolved)))
    return candidates


def python_version(binary: Path) -> tuple[int, int, int] | None:
    if not binary.exists():
        return None
    code = "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"
    try:
        result = subprocess.run(
            [str(binary), "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    parts = result.stdout.strip().split(".")
    if len(parts) != 3:
        return None
    try:
        return int(parts[0]), int(parts[1]), int(parts[2])
    except ValueError:
        return None


def resolve_python(
    runtime_dir: Path, env: Mapping[str, str] | None = None
) -> PythonCandidate | None:
    for source, path in iter_python_candidates(runtime_dir, env):
        version = python_version(path)
        if version and is_compatible_version(version):
            return PythonCandidate(source=source, path=path, version=version)
    return None


def venv_python(runtime_dir: Path) -> Path:
    return runtime_dir / ".venv" / "bin" / "python"


def venv_needs_rebuild(runtime_dir: Path) -> bool:
    venv_bin = venv_python(runtime_dir)
    version = python_version(venv_bin)
    return version is None or not is_compatible_version(version)


def missing_package_files(runtime_dir: Path, skill_dir: Path) -> list[Path]:
    required = [
        runtime_dir / "pyproject.toml",
        runtime_dir / "xhs_ceramics_analytics",
        skill_dir / "scripts" / "bootstrap",
        skill_dir / "scripts" / "xhs-ca",
    ]
    return [path for path in required if not path.exists()]


def repair_missing_python_shell(skill_dir: Path, runtime_dir: Path | None = None) -> str:
    runtime_dir = runtime_dir or skill_dir / "assets" / "xhs-ca"
    return f'''set -e

SKILL_DIR="{skill_dir}"
RUNTIME_DIR="{runtime_dir}"

if command -v python3.12 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.12)"
elif command -v python3.11 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.11)"
else
  echo "Python 3.11+ was not found. Install Python 3.11 or 3.12, then rerun this block."
  exit 1
fi

rm -rf "$RUNTIME_DIR/.venv"
"$PYTHON_BIN" -m venv "$RUNTIME_DIR/.venv"
"$RUNTIME_DIR/.venv/bin/python" -m pip install -U pip
"$RUNTIME_DIR/.venv/bin/python" -m pip install -e "$RUNTIME_DIR[dev]"
"$SKILL_DIR/scripts/xhs-ca" doctor --strict
'''


def repair_install_shell(skill_dir: Path, runtime_dir: Path | None = None) -> str:
    runtime_dir = runtime_dir or skill_dir / "assets" / "xhs-ca"
    return f'''set -e

SKILL_DIR="{skill_dir}"
RUNTIME_DIR="{runtime_dir}"
PIP_CACHE_DIR="$(mktemp -d)"

"$RUNTIME_DIR/.venv/bin/python" -m pip install -U pip
PIP_CACHE_DIR="$PIP_CACHE_DIR" "$RUNTIME_DIR/.venv/bin/python" -m pip install -e "$RUNTIME_DIR[dev]"
"$SKILL_DIR/scripts/xhs-ca" doctor --strict
'''


def repair_reinstall_skill_shell() -> str:
    return '''set -e

rm -rf "$HOME/.agents/skills/data-analyze-for-zcl"
npx skills add seyseyseyz/data-analyze-for-zcl -g -y --skill data-analyze-for-zcl
test -x "$HOME/.agents/skills/data-analyze-for-zcl/scripts/xhs-ca"
test -d "$HOME/.agents/skills/data-analyze-for-zcl/assets/xhs-ca"
'''


def print_repair(reason: str, shell: str) -> None:
    print(f"data-analyze-for-zcl runtime is not ready: {reason}.", file=sys.stderr)
    print(file=sys.stderr)
    print(
        "Copy the whole command block below into macOS Terminal. "
        "After it finishes, return to Codex and rerun the analysis.",
        file=sys.stderr,
    )
    print(file=sys.stderr)
    print("```bash", file=sys.stderr)
    print(shell.rstrip(), file=sys.stderr)
    print("```", file=sys.stderr)


def write_command_log(log_path: Path | None, command: list[str], output: str) -> None:
    if log_path is None:
        return
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "$ " + " ".join(command) + "\n" + output,
            encoding="utf-8",
        )
    except OSError:
        pass


def run_command(
    command: list[str],
    env: Mapping[str, str] | None = None,
    log_path: Path | None = None,
    echo_success: bool = False,
) -> bool:
    try:
        result = subprocess.run(
            command,
            env=dict(env or os.environ),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        write_command_log(log_path, command, f"Failed to start command: {exc}\n")
        return False
    output = result.stdout or ""
    if result.returncode != 0:
        write_command_log(log_path, command, output)
        return False
    if echo_success and output:
        print(output, end="")
    return result.returncode == 0


def ensure_venv(runtime_dir: Path, python: PythonCandidate) -> bool:
    if venv_needs_rebuild(runtime_dir):
        shutil.rmtree(runtime_dir / ".venv", ignore_errors=True)
        return run_command([str(python.path), "-m", "venv", str(runtime_dir / ".venv")])
    return True


def install_dependencies(runtime_dir: Path, *, with_dev: bool = False) -> bool:
    cache_dir = runtime_dir / ".runtime" / "pip-cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return False
    env = dict(os.environ)
    env["PIP_CACHE_DIR"] = str(cache_dir)
    python_bin = str(venv_python(runtime_dir))
    install_target = f"{runtime_dir}[dev]" if with_dev else str(runtime_dir)
    commands = [
        ("pip-upgrade.log", [python_bin, "-m", "pip", "install", "-U", "pip"]),
        ("pip-install.log", [python_bin, "-m", "pip", "install", "-e", install_target]),
    ]
    log_dir = runtime_dir / ".runtime" / "logs"
    for log_name, command in commands:
        log_path = log_dir / log_name
        if not run_command(command, env=env, log_path=log_path):
            _print_pip_log_tail(log_path)
            return False
    return True


def _print_pip_log_tail(log_path: Path | None, lines: int = 40) -> None:
    """Print the tail of a pip log to stderr for troubleshooting."""
    if log_path is None or not log_path.exists():
        return
    try:
        content = log_path.read_text(encoding="utf-8", errors="replace")
        tail = content.splitlines()[-lines:]
        print("\n--- pip log tail (last 40 lines) ---", file=sys.stderr)
        for line in tail:
            print(line, file=sys.stderr)
        print("--- end pip log ---\n", file=sys.stderr)
    except OSError:
        pass


def run_doctor(runtime_dir: Path, doctor_root: Path) -> bool:
    env = dict(os.environ)
    env["PATH"] = f"{runtime_dir / '.venv' / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    command = [
        str(venv_python(runtime_dir)),
        "-m",
        "xhs_ceramics_analytics.cli",
        "doctor",
        "--strict",
        "--project-root",
        str(doctor_root),
    ]
    return run_command(
        command,
        env=env,
        log_path=runtime_dir / ".runtime" / "logs" / "doctor.log",
        echo_success=True,
    )


def check_runtime(runtime_dir: Path) -> int:
    """Verify venv exists, Python version is compatible, and module is importable.

    Returns 0 if healthy, 1 if stale/broken.
    """
    venv_bin = venv_python(runtime_dir)
    version = python_version(venv_bin)
    if version is None:
        print("check: .venv/bin/python not found or broken", file=sys.stderr)
        return 1
    if not is_compatible_version(version):
        print(
            f"check: venv Python {'.'.join(map(str, version))} < 3.11 required",
            file=sys.stderr,
        )
        return 1
    # Verify the xhs_ceramics_analytics module is importable
    try:
        result = subprocess.run(
            [str(venv_bin), "-c", "import xhs_ceramics_analytics"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        print("check: failed to invoke venv python", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print("check: xhs_ceramics_analytics module not importable", file=sys.stderr)
        return 1
    return 0


def rebuild_venv(runtime_dir: Path, skill_dir: Path, doctor_root: Path, *, with_dev: bool = False) -> int:
    """Nuke .venv and re-install from scratch."""
    shutil.rmtree(runtime_dir / ".venv", ignore_errors=True)
    print("Removed existing .venv, rebuilding...", file=sys.stderr)
    return bootstrap(runtime_dir, skill_dir, doctor_root, with_dev=with_dev)


def bootstrap(runtime_dir: Path, skill_dir: Path, doctor_root: Path, *, with_dev: bool = False) -> int:
    missing = missing_package_files(runtime_dir, skill_dir)
    if missing:
        names = ", ".join(str(path) for path in missing)
        print_repair(
            f"skill package files are missing: {names}",
            repair_reinstall_skill_shell(),
        )
        return 1

    python = resolve_python(runtime_dir)
    if not python:
        print_repair("Python 3.11+ was not found", repair_missing_python_shell(skill_dir, runtime_dir))
        return 1

    print(
        f"Using Python {'.'.join(map(str, python.version))} "
        f"from {python.path} ({python.source})"
    )

    if not ensure_venv(runtime_dir, python):
        print_repair("venv creation failed", repair_missing_python_shell(skill_dir, runtime_dir))
        return 1

    if not install_dependencies(runtime_dir, with_dev=with_dev):
        print_repair("Python dependency installation failed", repair_install_shell(skill_dir, runtime_dir))
        return 1

    if not run_doctor(runtime_dir, doctor_root):
        print_repair("runtime doctor failed after dependency installation", repair_install_shell(skill_dir, runtime_dir))
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Bootstrap xhs-ca runtime environment.")
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--skill-dir", required=True, type=Path)
    parser.add_argument("--doctor-root", required=True, type=Path)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify venv health without installing. Exit 0 if healthy, 1 if stale.",
    )
    parser.add_argument(
        "--rebuild-venv",
        action="store_true",
        help="Nuke .venv and re-install from scratch.",
    )
    parser.add_argument(
        "--with-dev",
        action="store_true",
        help="Install [dev] extras (test dependencies). Omitted by default.",
    )
    args = parser.parse_args(argv)

    runtime_dir = args.runtime_dir.resolve()
    skill_dir = args.skill_dir.resolve()
    doctor_root = args.doctor_root.resolve()

    if args.check:
        return check_runtime(runtime_dir)

    if args.rebuild_venv:
        return rebuild_venv(runtime_dir, skill_dir, doctor_root, with_dev=args.with_dev)

    return bootstrap(runtime_dir, skill_dir, doctor_root, with_dev=args.with_dev)


if __name__ == "__main__":
    raise SystemExit(main())
