# Skill Runtime Environment Repair Design

## Background

`data-analyze-for-zcl` is distributed as a Codex skill with a bundled Python runtime under `assets/xhs-ca/`. A recent real run showed that skill installation can be complete while runtime setup still fails: macOS provided `python3` as Python 3.9, the package requires Python 3.11+, pip was old, network access was restricted, and the standard `xhs-ca build/run` pipeline could not start.

The current bootstrap scripts are too optimistic. They call `python3 -m venv` before proving that `python3` satisfies the runtime contract, and failures surface as raw pip or import errors. Users then fall back to ad hoc analysis scripts, which creates non-repeatable behavior and weakens the skill's standard reporting guarantees.

## Goals

- Make bootstrap repair safe environment problems automatically when it can.
- Stop creating or reusing invalid Python 3.9 runtime environments.
- Distinguish skill package installation from runtime readiness.
- Keep system-level changes explicit; do not silently modify system Python, Homebrew, shell profiles, or global permissions.
- When automatic repair cannot finish, print concise terminal instructions that the user can copy and run.
- Prevent analysis from continuing when core runtime requirements are not ready.

## Non-Goals

- Do not build a full pandas fallback report pipeline in this change.
- Do not make OCR, browser preview, or screenshot parsing required for core analysis.
- Do not require Homebrew, pyenv, or a specific system package manager.
- Do not change the public `xhs-ca build` and `xhs-ca run` command surface.

## Environment Layers

The runtime should classify checks into three layers.

### Skill Package

Required files:

- `SKILL.md`
- `assets/xhs-ca/pyproject.toml`
- `assets/xhs-ca/xhs_ceramics_analytics/`
- `scripts/bootstrap`
- `scripts/xhs-ca`

If these files are missing, bootstrap cannot reliably self-repair because the installed skill package itself is incomplete. The repair output should tell the user to reinstall the skill globally with `npx skills add seyseyseyz/data-analyze-for-zcl -g -y`.

### Runtime Core

Required for standard analysis:

- Python 3.11+
- a valid `.venv` created by Python 3.11+
- pip new enough to install the pyproject-based package
- core dependencies from `pyproject.toml`, especially DuckDB, pandas, openpyxl, Typer, PyYAML, Jinja2, Plotly, and rapidfuzz
- `scripts/xhs-ca doctor --strict` succeeds

Failures in this layer block analysis.

### Optional Capabilities

Examples:

- OCR tooling
- image-only screenshot extraction
- browser preview helpers

Missing optional capabilities should be reported as limitations, not bootstrap blockers.

## Bootstrap Flow

Bootstrap should follow this order.

1. Resolve `skill_dir` and `runtime_dir`.
2. Verify the skill package files exist.
3. Resolve a Python candidate in this priority order:
   - `XHS_CA_PYTHON`
   - existing private runtime Python under `assets/xhs-ca/.runtime/python/`
   - `python3.12`
   - `python3.11`
   - `python3`
4. Check that the candidate is Python 3.11+ before creating or reusing `.venv`.
5. If no valid Python is found, attempt private Python repair only when the repository has a supported private-runtime installer implementation.
6. If private Python repair succeeds, use it to create `.venv`.
7. If `.venv` exists but its Python is missing, broken, or older than 3.11, delete and rebuild it automatically.
8. Use a skill-local or temporary pip cache if the default pip cache is not writable.
9. Install or refresh dependencies with `pip install -e "$runtime_dir[dev]"`.
10. Run a lightweight readiness check, then `scripts/xhs-ca doctor --strict`.

## Automatic Repair Policy

Safe automatic repairs:

- recreate `.venv` when it is missing, broken, or built with Python older than 3.11
- upgrade pip inside the skill venv
- install package dependencies inside the skill venv
- use a local or temporary pip cache to avoid user cache permission errors
- create the local `.xhs-ceramics-analytics` state directory when writable

Repairs that must not happen silently:

- installing or upgrading system Python
- invoking Homebrew, pyenv, sudo, or system package managers
- changing shell startup files
- changing ownership or permissions outside the skill/runtime directories
- configuring network proxy settings

Private Python under `assets/xhs-ca/.runtime/python/` is allowed as a future automatic repair because it is scoped to the skill. If implementation cannot guarantee the correct macOS architecture, checksum verification, and clear network failure handling, it should not be enabled yet; bootstrap should print a repair kit instead.

## Repair Kit Output

When automatic repair cannot finish, output should be short and copyable. It should not include a raw traceback by default.

Format:

````text
data-analyze-for-zcl runtime is not ready: <one-line reason>.

Copy the whole command block below into macOS Terminal. After it finishes, return to Codex and rerun the analysis.

```bash
<repair shell>
```
````

Example for missing Python 3.11+:

```bash
set -e

SKILL_DIR="$HOME/.agents/skills/data-analyze-for-zcl"
RUNTIME_DIR="$SKILL_DIR/assets/xhs-ca"

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
```

Example for pip cache permission or dependency install failure:

```bash
set -e

SKILL_DIR="$HOME/.agents/skills/data-analyze-for-zcl"
RUNTIME_DIR="$SKILL_DIR/assets/xhs-ca"
PIP_CACHE_DIR="$(mktemp -d)"

"$RUNTIME_DIR/.venv/bin/python" -m pip install -U pip
PIP_CACHE_DIR="$PIP_CACHE_DIR" "$RUNTIME_DIR/.venv/bin/python" -m pip install -e "$RUNTIME_DIR[dev]"
"$SKILL_DIR/scripts/xhs-ca" doctor --strict
```

## Readiness Check Design

Add a small readiness command or script that does not depend on Typer. It should use only Python stdlib before dependency installation and then optionally validate imports after installation.

Checks:

- Python executable path and version
- venv Python version
- pip availability
- package import checks for core dependencies
- `xhs-ca` entrypoint availability through the skill wrapper
- state/output root writability

The output should be human-readable and script-friendly enough for tests. It should not replace the existing `xhs-ca doctor`; it should make bootstrap diagnosable before Typer and package dependencies are guaranteed.

## Error Handling

- Core runtime failures exit non-zero after printing the repair kit.
- Optional capability failures exit zero and are listed as warnings or limitations.
- Raw command output may be written to a log file under `assets/xhs-ca/.runtime/logs/`, but the terminal should show only the short reason and repair shell.
- Bootstrap should not continue into analysis commands after a core runtime failure.

## Testing Strategy

Add focused tests for:

- bootstrap script contains Python 3.11+ preflight behavior
- invalid `.venv` version is detected and scheduled for rebuild
- missing Python produces a repair kit instead of a pip traceback
- pip cache permission failure produces a `PIP_CACHE_DIR` repair shell
- bundled skill runtime and source runtime stay synchronized after `scripts/sync-runtime`
- `xhs-ca doctor --strict` still passes from a normal data/output directory after bootstrap succeeds

Shell-heavy behavior can be tested with small helper scripts and fake Python executables in temporary directories rather than installing real Python versions.

## Rollout Plan

1. Implement Python resolution and version preflight in source and skill bootstrap scripts.
2. Add venv validation and automatic rebuild.
3. Add pip cache fallback.
4. Add repair-kit output helpers.
5. Add lightweight readiness checks.
6. Synchronize the bundled skill runtime with `scripts/sync-runtime`.
7. Publish and verify with:
   - `pytest -q`
   - `git diff --check`
   - `npx skills add seyseyseyz/data-analyze-for-zcl -l`
   - a fresh global install/update followed by `scripts/bootstrap` and `scripts/xhs-ca doctor --strict`

## Open Decisions

- Private Python auto-install should remain disabled until there is a checksum-verified, architecture-aware installer.
- The first implementation should prioritize clear repair instructions over hidden downloads.
- A pandas fallback analysis path should be designed separately if needed; it should not be folded into bootstrap repair.
