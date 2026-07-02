# Skill Runtime Environment Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `data-analyze-for-zcl` bootstrap automatically repair safe runtime problems and print concise Terminal repair shell when automatic repair cannot finish.

**Architecture:** Add one stdlib-only bootstrap helper used by both source and installed-skill bootstrap scripts. The helper resolves Python 3.11+, rebuilds invalid venvs, uses a skill-local pip cache, installs dependencies, runs doctor, and prints Repair Kit output for unrecoverable environment failures.

**Tech Stack:** Bash, Python stdlib, pytest, existing `xhs_ceramics_analytics` package, existing `scripts/sync-runtime`.

## Global Constraints

- Do not build a full pandas fallback report pipeline in this change.
- Do not make OCR, browser preview, or screenshot parsing required for core analysis.
- Do not require Homebrew, pyenv, or a specific system package manager.
- Do not change the public `xhs-ca build` and `xhs-ca run` command surface.
- Do not silently install or upgrade system Python.
- Do not invoke Homebrew, pyenv, sudo, or system package managers from bootstrap.
- Do not change shell startup files.
- Do not change ownership or permissions outside the skill/runtime directories.
- Private Python auto-install remains disabled until there is a checksum-verified, architecture-aware installer.
- Automatic repair failures must print Terminal shell instructions, not a raw traceback by default.

---

## File Structure

- Create `scripts/bootstrap_runtime.py`: stdlib-only helper for Python resolution, venv validation/rebuild, dependency installation, doctor execution, and Repair Kit output.
- Modify `scripts/bootstrap`: thin source bootstrap wrapper that invokes `scripts/bootstrap_runtime.py`.
- Modify `skills/data-analyze-for-zcl/scripts/bootstrap`: thin installed-skill bootstrap wrapper that invokes its local copied `bootstrap_runtime.py`.
- Modify `skills/data-analyze-for-zcl/scripts/sync-runtime`: copy `scripts/bootstrap_runtime.py` into the skill scripts directory during runtime sync.
- Test `tests/test_bootstrap_runtime.py`: pure unit tests for resolver, repair shell text, package checks, and venv-version behavior.
- Modify `tests/test_environment_doctor.py`: update script-shape assertions for the new helper-driven bootstrap.
- Modify `tests/test_project_foundation.py`: assert the published skill includes `scripts/bootstrap_runtime.py`.

---

### Task 1: Add Bootstrap Runtime Helper

**Files:**
- Create: `scripts/bootstrap_runtime.py`
- Test: `tests/test_bootstrap_runtime.py`

**Interfaces:**
- Consumes: `runtime_dir` containing `pyproject.toml`; `skill_dir` containing `scripts/xhs-ca`.
- Produces:
  - `resolve_python(runtime_dir: Path, env: Mapping[str, str] | None = None) -> PythonCandidate | None`
  - `venv_needs_rebuild(runtime_dir: Path) -> bool`
  - `repair_missing_python_shell(skill_dir: Path, runtime_dir: Path | None = None) -> str`
  - `repair_install_shell(skill_dir: Path, runtime_dir: Path | None = None) -> str`
  - CLI: `python scripts/bootstrap_runtime.py --runtime-dir PATH --skill-dir PATH --doctor-root PATH`

- [ ] **Step 1: Write failing tests for Python resolution and Repair Kit copy**

Create `tests/test_bootstrap_runtime.py` with:

```python
import importlib.util
import os
import sys
from pathlib import Path


def load_bootstrap_runtime():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "bootstrap_runtime.py"
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
```

- [ ] **Step 2: Run tests and verify they fail because helper is missing**

Run: `pytest tests/test_bootstrap_runtime.py -q`

Expected: FAIL with `FileNotFoundError` or import error for `scripts/bootstrap_runtime.py`.

- [ ] **Step 3: Implement `scripts/bootstrap_runtime.py`**

Create `scripts/bootstrap_runtime.py`:

```python
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
    result = subprocess.run(
        [str(binary), "-c", code],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
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
npx skills add seyseyseyz/data-analyze-for-zcl -g -y
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


def run_command(command: list[str], env: Mapping[str, str] | None = None) -> bool:
    result = subprocess.run(command, env=dict(env or os.environ), check=False)
    return result.returncode == 0


def ensure_venv(runtime_dir: Path, python: PythonCandidate) -> bool:
    if venv_needs_rebuild(runtime_dir):
        shutil.rmtree(runtime_dir / ".venv", ignore_errors=True)
        return run_command([str(python.path), "-m", "venv", str(runtime_dir / ".venv")])
    return True


def install_dependencies(runtime_dir: Path) -> bool:
    cache_dir = runtime_dir / ".runtime" / "pip-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PIP_CACHE_DIR"] = str(cache_dir)
    python_bin = str(venv_python(runtime_dir))
    commands = [
        [python_bin, "-m", "pip", "install", "-U", "pip"],
        [python_bin, "-m", "pip", "install", "-e", f"{runtime_dir}[dev]"],
    ]
    return all(run_command(command, env=env) for command in commands)


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
    return run_command(command, env=env)


def bootstrap(runtime_dir: Path, skill_dir: Path, doctor_root: Path) -> int:
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

    if not install_dependencies(runtime_dir):
        print_repair("Python dependency installation failed", repair_install_shell(skill_dir, runtime_dir))
        return 1

    if not run_doctor(runtime_dir, doctor_root):
        print_repair("runtime doctor failed after dependency installation", repair_install_shell(skill_dir, runtime_dir))
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-dir", required=True, type=Path)
    parser.add_argument("--skill-dir", required=True, type=Path)
    parser.add_argument("--doctor-root", required=True, type=Path)
    args = parser.parse_args(argv)

    return bootstrap(
        runtime_dir=args.runtime_dir.resolve(),
        skill_dir=args.skill_dir.resolve(),
        doctor_root=args.doctor_root.resolve(),
    )


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests and verify Task 1 passes**

Run: `pytest tests/test_bootstrap_runtime.py -q`

Expected: PASS, all Task 1 tests green.

- [ ] **Step 5: Commit Task 1**

```bash
git add scripts/bootstrap_runtime.py tests/test_bootstrap_runtime.py
git commit -m "feat: add bootstrap runtime helper"
```

---

### Task 2: Wire Source Bootstrap to Helper

**Files:**
- Modify: `scripts/bootstrap`
- Modify: `tests/test_environment_doctor.py`

**Interfaces:**
- Consumes: `scripts/bootstrap_runtime.py` CLI from Task 1.
- Produces: source bootstrap behavior that resolves Python 3.11+ before creating `.venv`.

- [ ] **Step 1: Write failing assertions for source bootstrap shape**

In `tests/test_environment_doctor.py`, replace `test_bootstrap_script_is_executable_and_runs_doctor` with:

```python
def test_bootstrap_script_uses_runtime_repair_helper():
    script = Path("scripts/bootstrap")

    assert script.exists()
    assert os.access(script, os.X_OK)

    body = script.read_text(encoding="utf-8")
    assert "bootstrap_runtime.py" in body
    assert "--runtime-dir" in body
    assert "--doctor-root" in body
    assert "python3 -m venv .venv" not in body
```

- [ ] **Step 2: Run focused test and verify it fails**

Run: `pytest tests/test_environment_doctor.py::test_bootstrap_script_uses_runtime_repair_helper -q`

Expected: FAIL because `scripts/bootstrap` still calls `python3 -m venv .venv`.

- [ ] **Step 3: Replace `scripts/bootstrap`**

Replace `scripts/bootstrap` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"

if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
data-analyze-for-zcl runtime is not ready: python3 was not found.

Copy the whole command block below into macOS Terminal. After it finishes, return to Codex and rerun the analysis.

```bash
set -e
echo "Install Python 3.11 or 3.12, then rerun ./scripts/bootstrap from the project root."
exit 1
```
EOF
  exit 1
fi

exec python3 "$repo_root/scripts/bootstrap_runtime.py" \
  --runtime-dir "$repo_root" \
  --skill-dir "$repo_root" \
  --doctor-root "$repo_root"
```

- [ ] **Step 4: Run focused source bootstrap tests**

Run: `pytest tests/test_environment_doctor.py tests/test_bootstrap_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Run source bootstrap smoke**

Run: `./scripts/bootstrap`

Expected: exits 0 and prints an `Environment Doctor` section with `[OK] Python >= 3.11`.

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/bootstrap tests/test_environment_doctor.py
git commit -m "fix: route source bootstrap through runtime repair"
```

---

### Task 3: Wire Installed Skill Bootstrap and Sync

**Files:**
- Modify: `skills/data-analyze-for-zcl/scripts/bootstrap`
- Modify: `skills/data-analyze-for-zcl/scripts/sync-runtime`
- Modify: `tests/test_project_foundation.py`
- Modify: `skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_project_foundation.py` after sync
- Create: `skills/data-analyze-for-zcl/scripts/bootstrap_runtime.py` by sync or copy

**Interfaces:**
- Consumes: source `scripts/bootstrap_runtime.py`.
- Produces: installed skill bootstrap uses the same helper and the published skill includes `scripts/bootstrap_runtime.py`.

- [ ] **Step 1: Write failing published-skill test**

In `tests/test_project_foundation.py`, update `test_published_skill_bundles_runtime_and_entrypoints`:

```python
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
```

- [ ] **Step 2: Run test and verify it fails**

Run: `pytest tests/test_project_foundation.py::test_published_skill_bundles_runtime_and_entrypoints -q`

Expected: FAIL because `skills/data-analyze-for-zcl/scripts/bootstrap_runtime.py` is not present yet.

- [ ] **Step 3: Update skill bootstrap**

Replace `skills/data-analyze-for-zcl/scripts/bootstrap` with:

```bash
#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd "$(dirname "$0")/.." && pwd)"
runtime_dir="$skill_dir/assets/xhs-ca"

if ! command -v python3 >/dev/null 2>&1; then
  cat >&2 <<'EOF'
data-analyze-for-zcl runtime is not ready: python3 was not found.

Copy the whole command block below into macOS Terminal. After it finishes, return to Codex and rerun the analysis.

```bash
set -e
echo "Install Python 3.11 or 3.12, then rerun ~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap."
exit 1
```
EOF
  exit 1
fi

exec python3 "$skill_dir/scripts/bootstrap_runtime.py" \
  --runtime-dir "$runtime_dir" \
  --skill-dir "$skill_dir" \
  --doctor-root "$runtime_dir"
```

- [ ] **Step 4: Update sync script to publish helper**

Modify `skills/data-analyze-for-zcl/scripts/sync-runtime` so it copies the helper:

```bash
#!/usr/bin/env bash
set -euo pipefail

skill_dir="$(cd "$(dirname "$0")/.." && pwd)"
repo_root="$(cd "$skill_dir/../.." && pwd)"
runtime_dir="$skill_dir/assets/xhs-ca"

mkdir -p "$runtime_dir"
rsync -a --delete \
  "$repo_root/pyproject.toml" \
  "$repo_root/xhs_ceramics_analytics" \
  "$repo_root/references" \
  "$repo_root/task_templates" \
  "$repo_root/tests" \
  "$runtime_dir/"

cp "$repo_root/scripts/bootstrap_runtime.py" "$skill_dir/scripts/bootstrap_runtime.py"

find "$runtime_dir" -type d -name "__pycache__" -prune -exec rm -rf {} +
find "$runtime_dir" -type d -name ".pytest_cache" -prune -exec rm -rf {} +
find "$runtime_dir" -type d -name ".ruff_cache" -prune -exec rm -rf {} +
```

- [ ] **Step 5: Run sync and verify helper is copied**

Run: `skills/data-analyze-for-zcl/scripts/sync-runtime`

Expected: `skills/data-analyze-for-zcl/scripts/bootstrap_runtime.py` exists and matches `scripts/bootstrap_runtime.py`.

- [ ] **Step 6: Run focused published-skill tests**

Run: `pytest tests/test_project_foundation.py tests/test_bootstrap_runtime.py -q`

Expected: PASS.

- [ ] **Step 7: Commit Task 3**

```bash
git add \
  skills/data-analyze-for-zcl/scripts/bootstrap \
  skills/data-analyze-for-zcl/scripts/bootstrap_runtime.py \
  skills/data-analyze-for-zcl/scripts/sync-runtime \
  skills/data-analyze-for-zcl/assets/xhs-ca/tests/test_project_foundation.py \
  tests/test_project_foundation.py
git commit -m "fix: publish bootstrap repair helper with skill"
```

---

### Task 4: Verify Repair Kit Behavior and Full Runtime

**Files:**
- Modify: `tests/test_bootstrap_runtime.py`
- Modify: `README.md`
- Modify: `skills/data-analyze-for-zcl/SKILL.md`

**Interfaces:**
- Consumes: helper and bootstrap scripts from Tasks 1-3.
- Produces: documentation and tests proving Repair Kit output is Terminal-shell-focused.

- [ ] **Step 1: Add CLI-level tests for Repair Kit output**

Append to `tests/test_bootstrap_runtime.py`:

```python
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
```

- [ ] **Step 2: Run test and verify it passes**

Run: `pytest tests/test_bootstrap_runtime.py::test_main_prints_repair_kit_for_incomplete_skill_package -q`

Expected: PASS.

- [ ] **Step 3: Update README environment section**

In `README.md`, replace the environment setup paragraph under `Development Setup` with:

```markdown
`./scripts/bootstrap` creates or repairs `.venv`, installs the editable package
with dev dependencies, and runs `xhs-ca doctor --strict`. If the local machine
does not have Python 3.11+ or dependency installation fails, bootstrap prints a
short command block to copy into macOS Terminal instead of showing a raw pip
traceback.
```

- [ ] **Step 4: Update skill workflow note**

In `skills/data-analyze-for-zcl/SKILL.md`, replace workflow step 2 with:

```markdown
2. On first use, run this skill's `scripts/bootstrap`. It creates or repairs `assets/xhs-ca/.venv`, installs the bundled Python package, verifies the environment, and prints a Terminal repair command if the runtime cannot be prepared automatically.
```

- [ ] **Step 5: Sync runtime after doc/runtime changes**

Run: `skills/data-analyze-for-zcl/scripts/sync-runtime`

Expected: bundled runtime tests and README-independent runtime files stay synchronized.

- [ ] **Step 6: Run full validation**

Run:

```bash
pytest -q
git diff --check
./scripts/bootstrap
/Users/temptrip/Documents/personal/xiaohongshu-ceramics-analytics/skills/data-analyze-for-zcl/scripts/bootstrap
```

Expected:

- `pytest -q` reports all tests passing.
- `git diff --check` reports no whitespace errors.
- both bootstrap scripts exit 0 on this machine.

- [ ] **Step 7: Commit Task 4**

```bash
git add \
  README.md \
  skills/data-analyze-for-zcl/SKILL.md \
  skills/data-analyze-for-zcl/assets/xhs-ca \
  tests/test_bootstrap_runtime.py
git commit -m "docs: describe bootstrap repair workflow"
```

---

### Task 5: Publish and Install Verification

**Files:**
- No source edits unless Task 4 validation reveals a defect.

**Interfaces:**
- Consumes: all previous task commits.
- Produces: published `main` containing the repaired bootstrap workflow.

- [ ] **Step 1: Confirm clean validation before publishing**

Run:

```bash
pytest -q
git diff --check
git status --short
```

Expected:

- tests pass
- diff check passes
- working tree is clean after all intended commits

- [ ] **Step 2: Verify skill discovery before push**

Run: `npx skills add seyseyseyz/data-analyze-for-zcl -l`

Expected: command lists `data-analyze-for-zcl`.

- [ ] **Step 3: Push commits**

Run:

```bash
git fetch origin main
git rev-list --left-right --count HEAD...origin/main
git push origin main
```

Expected:

- rev-list shows local ahead and remote not ahead
- push succeeds

- [ ] **Step 4: Verify global update path**

Run:

```bash
npx skills update data-analyze-for-zcl -g -y
test -x "$HOME/.agents/skills/data-analyze-for-zcl/scripts/xhs-ca"
test -f "$HOME/.agents/skills/data-analyze-for-zcl/scripts/bootstrap_runtime.py"
"$HOME/.agents/skills/data-analyze-for-zcl/scripts/bootstrap"
cd /tmp
"$HOME/.agents/skills/data-analyze-for-zcl/scripts/xhs-ca" doctor --strict
```

Expected:

- skill update succeeds
- installed skill includes `scripts/bootstrap_runtime.py`
- bootstrap succeeds
- doctor from `/tmp` prints `[OK] Data/output root: /tmp`

- [ ] **Step 5: Report publish result**

Final report should include:

- latest commit hash
- validation commands and pass/fail result
- installed skill path
- whether `Data/output root` was verified from `/tmp`

---

## Plan Self-Review

Spec coverage:

- Skill package layer is covered by Task 1 package checks and Task 3 published-skill tests.
- Runtime core layer is covered by Task 1 helper, Task 2 source bootstrap, Task 3 installed bootstrap, and Task 4 validation.
- Optional capabilities are kept out of bootstrap blockers through Global Constraints and no implementation task adds OCR/browser blockers.
- Repair Kit output is covered by Task 1 string tests and Task 4 CLI-level test.
- No pandas fallback is included.

Type and interface consistency:

- `bootstrap_runtime.py` exposes `resolve_python`, `venv_needs_rebuild`, `repair_missing_python_shell`, `repair_install_shell`, and `main`; all later tasks refer to those exact names and pass `runtime_dir` when generating source-runtime repair shell.
- Both bootstrap scripts pass `--runtime-dir`, `--skill-dir`, and `--doctor-root` to the same helper.
- `sync-runtime` copies `scripts/bootstrap_runtime.py` into `skills/data-analyze-for-zcl/scripts/bootstrap_runtime.py`.

Scope check:

- This plan is one coherent subsystem: runtime repair and readiness. It does not include report-generation fallback or private Python downloading.
