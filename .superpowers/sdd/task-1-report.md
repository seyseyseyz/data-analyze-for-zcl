# Task 1 Report

## Scope

- Added `scripts/bootstrap_runtime.py`.
- Added `tests/test_bootstrap_runtime.py`.
- Left all other repository files unchanged.

## TDD Record

### Red

1. Added the six required tests from the task brief to `tests/test_bootstrap_runtime.py`.
2. `pytest tests/test_bootstrap_runtime.py -q` could not run directly in this shell because `pytest` was not on `PATH`.
3. Re-ran the focused suite with `./.venv/bin/python -m pytest tests/test_bootstrap_runtime.py -q`.
4. Observed the intended red failure: all six tests failed with `FileNotFoundError` because `scripts/bootstrap_runtime.py` did not exist yet.

### Green

1. Implemented `scripts/bootstrap_runtime.py` exactly to the interface and code shape specified in the brief.
2. Re-ran `./.venv/bin/python -m pytest tests/test_bootstrap_runtime.py -q`.
3. Result: `6 passed in 0.03s`.

## Implementation Notes

- Added Python candidate discovery with explicit env preference, private runtime fallback, and `python3.12` / `python3.11` / `python3` path lookup.
- Added venv health checks and rebuild detection based on interpreter version.
- Added shell repair helpers for missing Python, dependency install retry, and skill reinstall.
- Added bootstrap flow for package-file validation, venv creation, dependency install, and strict doctor execution.

## Verification

- `./.venv/bin/python -m pytest tests/test_bootstrap_runtime.py -q`
- `git diff --check -- scripts/bootstrap_runtime.py tests/test_bootstrap_runtime.py`

## Commit

- Commit message: `feat: add bootstrap runtime helper`

## Concerns

- The shell did not expose a `pytest` executable on `PATH`; focused verification used the repo virtualenv interpreter instead.
