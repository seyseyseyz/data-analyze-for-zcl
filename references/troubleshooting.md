## Troubleshooting

Concrete repair steps for common bootstrap and runtime failures.

---

### Bootstrap: no Python 3.11+

**What you see:**

```
ERROR: Python >= 3.11 is required. Found Python 3.9.x.
Install Python 3.11 or 3.12 and rerun:
  ~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

The bootstrap shell stage iterates a candidate list
(`python3.12`, `python3.11`, `python3`, homebrew/pyenv paths).
If none satisfy `>=3.11`, it exits 1.

**Fix (macOS):**

```bash
# Option A: Homebrew
brew install python@3.12

# Option B: pyenv
pyenv install 3.12.4
pyenv global 3.12.4

# Then rerun bootstrap
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

You can also force a specific interpreter by exporting before bootstrap:

```bash
export XHS_CA_PYTHON=/opt/homebrew/bin/python3.12
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

---

### Bootstrap: pip install fails

**Where the log lives:**

```
<runtime_dir>/.runtime/logs/pip-install.log
```

For a typical global skill install this resolves to:

```
~/.agents/skills/data-analyze-for-zcl/assets/xhs-ca/.runtime/logs/pip-install.log
```

**How to inspect:**

```bash
tail -60 ~/.agents/skills/data-analyze-for-zcl/assets/xhs-ca/.runtime/logs/pip-install.log
```

(There is also `pip-upgrade.log` in the same directory if `pip install -U pip` itself failed.)

**Common causes:**

| Symptom in log | Cause | Fix |
|---|---|---|
| `ConnectionError` / `ReadTimeoutError` | No network or PyPI unreachable | Connect to the internet, or configure a mirror (see below). |
| `Could not find a version that satisfies` | Stale pip cache or incompatible platform wheel | Delete pip cache: `rm -rf ~/.agents/skills/data-analyze-for-zcl/assets/xhs-ca/.runtime/pip-cache` and rerun bootstrap. |
| SSL certificate errors behind proxy | Corporate proxy strips certs | `export PIP_CERT=/path/to/ca-bundle.crt` before bootstrap. |

**Using TUNA mirror (mainland China):**

```bash
export PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
export PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

---

### Stale venv after skill upgrade

When the skill is upgraded (new version of `xhs_ceramics_analytics` or new
dependencies in `pyproject.toml`), the existing `.venv` may contain stale
packages. The launcher (`scripts/xhs-ca`) only checks that
`.venv/bin/python` is executable; it does not verify package freshness.

**Preferred fix — rebuild the venv via bootstrap:**

```bash
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

Bootstrap calls `venv_needs_rebuild()` and reinstalls editable deps.
If the venv Python binary is missing or broken it recreates the venv
automatically.

**Fallback — manually delete and rebootstrap:**

Determine which install root you have, then delete the venv:

```bash
# If installed under ~/.agents/skills/ (default via npx skills add):
rm -rf ~/.agents/skills/data-analyze-for-zcl/assets/xhs-ca/.venv
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap

# If installed under ~/.claude/skills/ (some harness variants):
rm -rf ~/.claude/skills/data-analyze-for-zcl/assets/xhs-ca/.venv
~/.claude/skills/data-analyze-for-zcl/scripts/bootstrap
```

**Nuclear option — full skill reinstall:**

```bash
rm -rf "$HOME/.agents/skills/data-analyze-for-zcl"
npx skills add seyseyseyz/data-analyze-for-zcl -g -y --skill data-analyze-for-zcl
~/.agents/skills/data-analyze-for-zcl/scripts/bootstrap
```

---

### doctor exits non-zero

`xhs-ca doctor --strict` runs these checks. Each failure maps to a fix:

| Check | Status | Fix |
|---|---|---|
| **Python >= 3.11** | MISSING | Install Python 3.11+ (see "no Python 3.11+" above). |
| **Project root** | OK (always) | Informational; shows the resolved root path. |
| **Virtual environment** | WARN | Run `./scripts/bootstrap` to create/activate the venv. |
| **xhs-ca command** | MISSING | `python -m pip install -e ".[dev]"` inside the venv. |
| **State directory** | MISSING | Ensure the project root is on a writable filesystem. If running from a read-only mount, set `XHS_CA_PROJECT_ROOT` to a writable path. |
| **Python dependency: \<pkg\>** | MISSING | `python -m pip install -e ".[dev]"` reinstalls all runtime deps (duckdb, pandas, openpyxl, pydantic, PyYAML, Jinja2, typer, rapidfuzz). |

When `--strict` is passed, any MISSING check causes exit code 1.
A WARN does not cause failure under `--strict`.

---

### build fails: header mapping

`xhs-ca build` normalizes raw Excel column headers into the standard
schema. If a column cannot be mapped, the build emits:

```
WARNING: unmapped column '...' — skipping
```

or hard-fails if a required column (e.g. `note_id`) is missing entirely.

**Where to look:**

- Data contract (required/optional fields): `references/data_contract.md`
- Mapping logic: `xhs_ceramics_analytics/importing/mapping.py`

`mapping.py` uses fuzzy matching and a Chinese-header alias table.
If the upstream export renames columns, update the alias map in
`mapping.py` and the corresponding contract in `references/data_contract.md`.

---

### build succeeds but run returns not-judgable

A task returning `evidence_strength = not_judgable` means it ran
successfully but could not produce a meaningful finding — typically because
the input data lacks the columns or sample size the task requires.

**Diagnosis:**

1. Check which columns the task expects: open the matching template in
   `task_templates/<task_slug>.md` — the "Required columns" or
   "Minimum data" section lists prerequisites.
2. Verify the built DuckDB tables actually contain those columns with
   non-null data:
   ```bash
   xhs-ca run data_quality_check
   ```
3. Check evidence tier definitions in `references/evidence_strength.md` —
   "not-judgable" is below "weak" and means the analysis cannot even begin.

**Common causes:**

- The source Excel was exported without the "paid traffic" or "orders" tab,
  so order/SKU tables are empty.
- Date range is too narrow (fewer than 7 days of data for time-series tasks).
- A required join key (e.g. `sku_id` linking notes to orders) is missing
  from one side.

Resolve by re-exporting the data with the missing tab/columns included,
then rerun `xhs-ca build` and `xhs-ca run <task>`.
