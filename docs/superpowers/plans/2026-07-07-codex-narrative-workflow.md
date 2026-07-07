# Codex Narrative Workflow Implementation Plan (Final)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a file-based, host-neutral narrative-workflow controller that lets the *main* agent (Codex, Claude Code, or any subagent-capable host) drive the existing L3 hybrid report DAG (Seed→Fan≤6→Confirm→Gate→Patch→Continuity) by preparing durable briefs/state and ingesting subagent JSON, while guaranteeing a deterministic-skeleton fallback so a report is always delivered.

**Architecture:** A pure-Python controller (`narrative_workflow.py`) writes per-stage briefs and a durable `state.json` under a run directory, but NEVER spawns subagents itself. The host agent reads briefs, spawns native subagents, feeds their JSON back through `ingest`, and calls `advance` to move stages. The controller reuses the already-shipped rendering/gate/frozen/telemetry primitives in `xhs_ceramics_analytics/reporting/`. If the host cannot or will not spawn (blocked / denied / gate-exhausted), the controller finalizes a deterministic skeleton report from the same L1/L2 data so the deliverable never fails open.

**Tech Stack:** Python 3.14 (repo `.venv`; the interpreter is `.venv/bin/python` — bare `python` is not installed), Typer CLI, DuckDB-backed marts (already built), existing `reporting/` primitives (`narrative_render`, `factcheck_gate`, `frozen_narrative`, `report_telemetry`, `domains`, `html`), pytest.

## Global Constraints

- **Interpreter:** `.venv/bin/python` is THE interpreter. Never invoke bare `python`. All test/verify commands use `.venv/bin/python -m pytest …`.
- **Host neutrality (copy rule):** No prompt, brief, docstring, banner, or committed doc may name a specific model or vendor (no "Claude", "Codex", "GPT", "Opus", "Sonnet", model IDs). Say "the host agent" / "a subagent" / "sub-agents". The plan filename and this header reference Codex only as the motivating host; shipped artifacts stay neutral.
- **Never-raise at delivery boundary:** The report deliverable must never fail open. Any unrecoverable orchestration state (blocked, denied, gate-exhausted) routes to `finalize_deterministic`, which always writes `<name>.md` + `<name>.html`.
- **No deterministic note→order attribution:** Weak evidence at most; every conclusion carries an evidence tier (Strong/Medium/Weak/Not-judgable). The skeleton fallback preserves module-declared caveats verbatim.
- **Emoji is real merchant content** — never strip it from ingested text or rendered output.
- **Read-only real exports:** Never write/move/rename/delete inside the WeChat cache. Copy OUT to `/tmp` only. (No task here touches real exports, but the constraint stands.)
- **TDD:** Each task writes a failing test first, watches it fail, implements minimally, watches it pass, commits.
- **Commit trailer (verbatim):**
  ```
  via [HAPI](https://hapi.run)

  Co-Authored-By: HAPI <noreply@hapi.run>
  ```
- **Two artifacts only:** the integrated report is exactly `<name>.md` + `<name>.html` under `.xhs-ceramics-analytics/outputs/`. The workflow run directory (`state.json`, briefs, ingested JSON) is durable scratch, not a deliverable.
- **Fan cap = 6:** `MAX_FAN_AGENTS = 6`. Slices beyond the cap must be losslessly folded, never silently dropped.

---

## File Structure

**New files:**
- `xhs_ceramics_analytics/orchestration/__init__.py` — package marker (may already exist; create if absent).
- `xhs_ceramics_analytics/orchestration/narrative_workflow.py` — the controller: state model, brief writers, lossless slice cap, ingestion with JSON tolerance, stage guards, advance/finalize, deterministic fallback, machine-readable status.
- `xhs_ceramics_analytics/orchestration/dag.md` — the stage contract doc (host-neutral).
- `xhs_ceramics_analytics/orchestration/runbook.md` — the explicit control loop the host follows to drive the workflow.
- `tests/orchestration/test_narrative_workflow.py` — unit tests for state/briefs/cap/ingest/advance/finalize/status.
- `tests/orchestration/test_narrative_cli.py` — CLI wiring tests.
- `tests/orchestration/test_runbook.py` — asserts runbook/dag banned-phrase + key-phrase invariants.

**Modified files:**
- `xhs_ceramics_analytics/cli.py` — add `narrative` sub-app: `prepare`, `status`, `ingest`, `advance`, `finalize-deterministic`.
- `xhs_ceramics_analytics/reporting/report_telemetry.py` — extend `_VALID_MODES` with `"blocked"` (skeleton already valid); keep `build_run_record` backward compatible.
- `skills/data-analyze-for-zcl/SKILL.md` — add section 7b describing the narrative workflow + runbook pointer (host-neutral).
- `scripts/sync-runtime` (invocation only) — sync repo source into the in-repo mirror at the end (Task 8).

---

## Task 1: Stage contract + host runbook (docs, host-neutral)

**Files:**
- Create: `xhs_ceramics_analytics/orchestration/__init__.py`
- Create: `xhs_ceramics_analytics/orchestration/dag.md`
- Create: `xhs_ceramics_analytics/orchestration/runbook.md`
- Test: `tests/orchestration/test_runbook.py`

**Interfaces:**
- Consumes: nothing (pure docs + package marker).
- Produces: `orchestration` package importable; two docs whose invariants later tests and the host rely on. Stage names fixed here: `seed`, `fan`, `synth`, `gate`, `patch`, `continuity`, `finalized`, `blocked`.

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestration/test_runbook.py
from pathlib import Path

ORCH = Path(__file__).resolve().parents[2] / "xhs_ceramics_analytics" / "orchestration"

# Banned: any host/vendor/model identity leaking into shipped docs.
_BANNED = ("claude", "codex", "gpt", "opus", "sonnet", "anthropic", "openai")
# Banned phrase that previously implied a no-subagent host degrades to in-session role-passes.
_BANNED_PHRASE = "sequential in-session role-passes"


def _text(name: str) -> str:
    return (ORCH / name).read_text(encoding="utf-8").lower()


def test_dag_doc_is_host_neutral_and_drops_banned_phrase():
    body = _text("dag.md")
    assert _BANNED_PHRASE not in body
    for token in _BANNED:
        assert token not in body, f"dag.md leaks host identity: {token}"


def test_dag_doc_declares_all_stages():
    body = _text("dag.md")
    for stage in ("seed", "fan", "synth", "gate", "patch", "continuity", "finalized", "blocked"):
        assert stage in body


def test_runbook_is_host_neutral():
    body = _text("runbook.md")
    for token in _BANNED:
        assert token not in body, f"runbook leaks host identity: {token}"


def test_runbook_declares_the_control_loop():
    body = _text("runbook.md")
    for phrase in ("prepare", "authorize", "ingest", "advance", "status --json", "finalize-deterministic"):
        assert phrase in body


def test_runbook_declares_fallback_on_blocked_or_denied():
    body = _text("runbook.md")
    assert "blocked" in body and "denied" in body
    assert "deterministic" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/orchestration/test_runbook.py -v`
Expected: FAIL — `orchestration/dag.md` and `runbook.md` do not exist (FileNotFoundError).

- [ ] **Step 3: Create the package marker**

```python
# xhs_ceramics_analytics/orchestration/__init__.py
"""File-based narrative-workflow controller (host-neutral)."""
```

- [ ] **Step 4: Write `dag.md` (host-neutral, banned phrase deleted)**

```markdown
# Narrative Workflow DAG

The narrative workflow turns deterministic Findings (L1) and the single number
source `facts.json` (L2) into a merchant-facing report (L3) through a fixed
sequence of stages. The controller only prepares briefs and durable state; the
host agent spawns sub-agents and feeds their JSON back.

## Stages

1. **seed** — one sub-agent drafts the report skeleton bundle (section shells,
   titles, ordering) from the domain slices. Output: a draft bundle.
2. **fan** — up to six sub-agents (MAX_FAN_AGENTS = 6), one per domain slice,
   write their section prose grounded in the slice facts. Slices beyond the cap
   are losslessly folded into a single "综合参考" slice before fan-out — never
   dropped.
3. **synth** — one sub-agent merges the fan sections into a coherent bundle,
   reusing each fan section's canonical `section_id`.
4. **gate** — deterministic fact-check (no sub-agent). Numbers must trace to
   `facts.json`; causal wording and over-claims are capped. Emits PASS/FAIL.
5. **patch** — on gate FAIL, one sub-agent repairs only the flagged sections;
   the gate re-runs.
6. **continuity** — one sub-agent smooths cross-section transitions; the gate
   runs once more as the final guard.
7. **finalized** — terminal success: `<name>.md` + `<name>.html` written.
8. **blocked** — terminal degraded: orchestration could not complete (host
   declined, gate exhausted, or an unrecoverable state). The controller writes a
   deterministic skeleton report so the deliverable still exists.

## Host neutrality

Briefs and prompts never name a model or vendor. A host that cannot spawn
sub-agents does not attempt the LLM stages at all — it routes directly to the
deterministic skeleton via `finalize-deterministic`. There is no in-session
role-passing substitute for real sub-agents.
```

- [ ] **Step 5: Write `runbook.md` (explicit control loop, host-neutral)**

```markdown
# Narrative Workflow Runbook

This runbook is the control loop the host agent follows to drive the narrative
workflow. The controller is passive: it prepares briefs and durable state and
ingests results, but never spawns. You (the host) own spawning.

## One-time authorization

Before spawning any sub-agent, ask the user once for permission to run the
multi-agent narrative writer. If the user declines, skip straight to the
deterministic fallback (see "Degradation").

## The loop

1. **prepare** — run `xhs-ca narrative prepare --run-dir <dir> --name <report>`
   (add `--force` only to intentionally overwrite an unfinished run). This
   writes `state.json` and the seed brief.
2. **status** — run `xhs-ca narrative status --run-dir <dir> --json`. The JSON
   tells you the current `stage`, the `next_action`, and which brief files to
   read. Always consult it to decide what to do next; never guess the stage.
3. **map briefs to spawns** — read the brief file(s) named by `status`. For the
   seed/synth/patch/continuity stages spawn one sub-agent; for the fan stage
   spawn one sub-agent per brief (at most six). Give each sub-agent only its
   brief. Require it to return JSON.
4. **ingest** — for each returned result run
   `xhs-ca narrative ingest --run-dir <dir> --stage <stage> --source <file>`
   (or `--section-id <id>` for a single fan section). Ingestion tolerates JSON
   wrapped in code fences or surrounded by prose.
5. **advance** — run `xhs-ca narrative advance --run-dir <dir>`. This moves the
   stage forward (running the deterministic gate where the DAG requires it) and
   updates `state.json`.
6. **branch on status** — re-run `status --json`:
   - `stage == finalized` → done; deliver `<name>.md` + `<name>.html`.
   - `stage == blocked` → the controller already wrote the deterministic
     skeleton; deliver it and report the degradation reason.
   - otherwise → loop back to step 2.

## Degradation

Route to the deterministic skeleton whenever the LLM path cannot finish:

- **User denied** spawning → run
  `xhs-ca narrative finalize-deterministic --run-dir <dir> --reason denied`.
- **Host cannot spawn sub-agents at all** → same command, `--reason unsupported`.
- **Gate never passes / orchestration exhausted** → `advance` itself routes to
  the deterministic skeleton and sets stage `blocked`; just deliver it.

In every degraded path the deliverable still exists: a "确定性骨架版" report
built from the same L1/L2 data, with module caveats preserved and unanswerable
questions listed explicitly.
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/orchestration/test_runbook.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Commit**

```bash
git add xhs_ceramics_analytics/orchestration/__init__.py \
        xhs_ceramics_analytics/orchestration/dag.md \
        xhs_ceramics_analytics/orchestration/runbook.md \
        tests/orchestration/test_runbook.py
git commit -m "$(cat <<'EOF'
docs(orchestration): add host-neutral DAG contract + driving runbook

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 2: Workflow state, briefs, lossless slice cap, overwrite protection

**Files:**
- Create/extend: `xhs_ceramics_analytics/orchestration/narrative_workflow.py`
- Test: `tests/orchestration/test_narrative_workflow.py`

**Interfaces:**
- Consumes: `reporting/domains.py::DOMAINS` (6 domains) for slice grouping; `reporting/narrative_render.py::skeleton_markdown` is NOT used here (that is fallback-only).
- Produces:
  - `MAX_FAN_AGENTS: int = 6`
  - `_slug(title: str) -> str` — canonical section_id (preserves CJK, lowercases ASCII, collapses whitespace/punct to `-`).
  - `_cap_slices(slices: list[dict]) -> tuple[list[dict], list[str]]` — folds tail beyond the cap into one `综合参考` slice; returns `(capped_slices, merged_titles)`.
  - `prepare_run(run_dir, *, results, facts_json, report_name, project_root=None, force=False) -> dict` — writes `state.json` + seed brief + `domain_slices.json`; records `merged_sections`; raises `FileExistsError` on an unfinished existing run unless `force`.
  - `_write_fan_briefs(run_dir, capped_slices) -> list[Path]` — one brief per capped slice.
  - State schema (JSON): `{"stage": str, "report_name": str, "facts_hash": str, "merged_sections": list[str], "sections": dict, "history": list[str], "degradation_reason": str | None}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestration/test_narrative_workflow.py
import json
from pathlib import Path

import pytest

from xhs_ceramics_analytics.orchestration import narrative_workflow as nw


def _slice(i):
    return {"title": f"域{i}", "facts": [{"metric": f"m{i}", "value": i}], "reading": {"conclusion": f"c{i}"}}


def _bundle_inputs(n):
    results = {"domain_slices": [_slice(i) for i in range(n)]}
    facts_json = {"facts_hash": "abc123", "numbers": {}}
    return results, facts_json


def test_slug_preserves_cjk_and_normalizes_ascii():
    assert nw._slug("生意大盘") == "生意大盘"
    assert nw._slug("Traffic & Content") == "traffic-content"


def test_cap_slices_folds_tail_losslessly():
    slices = [_slice(i) for i in range(9)]
    capped, merged = nw._cap_slices(slices)
    assert len(capped) == nw.MAX_FAN_AGENTS
    # first five untouched, sixth is the folded remainder
    assert capped[-1]["title"] == "综合参考"
    assert [s["title"] for s in slices[nw.MAX_FAN_AGENTS - 1:]] == merged
    # every original fact survives in the capped set
    folded_facts = [f for s in capped for f in s["facts"]]
    assert len(folded_facts) == sum(len(s["facts"]) for s in slices)


def test_cap_slices_noop_under_cap():
    slices = [_slice(i) for i in range(4)]
    capped, merged = nw._cap_slices(slices)
    assert capped == slices
    assert merged == []


def test_prepare_run_writes_state_and_briefs(tmp_path):
    results, facts_json = _bundle_inputs(9)
    state = nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="测试报告")
    assert state["stage"] == "seed"
    assert state["report_name"] == "测试报告"
    assert state["facts_hash"] == "abc123"
    # tail folded → merged_sections recorded
    assert state["merged_sections"] == [f"域{i}" for i in range(5, 9)]
    assert (tmp_path / "state.json").exists()
    assert (tmp_path / "briefs" / "seed.md").exists()
    assert (tmp_path / "domain_slices.json").exists()
    fan_briefs = sorted((tmp_path / "briefs").glob("fan_*.md"))
    assert len(fan_briefs) == nw.MAX_FAN_AGENTS


def test_prepare_run_refuses_overwrite_of_unfinished_run(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    with pytest.raises(FileExistsError):
        nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    # force overrides
    state = nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r", force=True)
    assert state["stage"] == "seed"


def test_prepare_run_allows_overwrite_when_finalized(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    raw = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    raw["stage"] = "finalized"
    (tmp_path / "state.json").write_text(json.dumps(raw), encoding="utf-8")
    # no force needed once finalized/blocked
    state = nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    assert state["stage"] == "seed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -v`
Expected: FAIL — `narrative_workflow` has no `_slug`/`_cap_slices`/`prepare_run` (AttributeError / ImportError).

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/orchestration/narrative_workflow.py
"""Passive, file-based narrative-workflow controller (host-neutral).

The controller prepares durable briefs and state and ingests sub-agent JSON,
but never spawns sub-agents. The host agent drives it (see runbook.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

MAX_FAN_AGENTS = 6

_STATE_FILE = "state.json"
_SLUG_STRIP = re.compile(r"[^\w一-鿿]+")
_TERMINAL_STAGES = {"finalized", "blocked"}


def _slug(title: str) -> str:
    """Canonical section_id: preserve CJK, lowercase ASCII, dashes for the rest."""
    lowered = title.strip().lower()
    slug = _SLUG_STRIP.sub("-", lowered).strip("-")
    return slug or "section"


def _cap_slices(slices: list[dict]) -> tuple[list[dict], list[str]]:
    """Fold any slices beyond MAX_FAN_AGENTS into one lossless '综合参考' slice."""
    if len(slices) <= MAX_FAN_AGENTS:
        return list(slices), []
    head = list(slices[: MAX_FAN_AGENTS - 1])
    tail = list(slices[MAX_FAN_AGENTS - 1 :])
    merged_titles = [s.get("title", "") for s in tail]
    merged = {
        "title": "综合参考",
        "facts": [f for s in tail for f in s.get("facts", [])],
        "reading": {
            "conclusion": "；".join(
                s.get("reading", {}).get("conclusion", "") for s in tail if s.get("reading", {}).get("conclusion")
            ),
        },
        "merged_from": merged_titles,
    }
    head.append(merged)
    return head, merged_titles


def _load_state(run_dir: Path) -> dict | None:
    path = run_dir / _STATE_FILE
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_state(run_dir: Path, state: dict) -> None:
    (run_dir / _STATE_FILE).write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_seed_brief(run_dir: Path, capped_slices: list[dict], report_name: str) -> None:
    lines = [
        f"# Seed brief — {report_name}",
        "",
        "Draft the report skeleton bundle: one section shell per slice below,",
        "in this order. Return JSON: {\"sections\": [{\"section_id\", \"title\", \"body\"}]}.",
        "Use only the facts provided; do not invent numbers. Return JSON only.",
        "",
    ]
    for s in capped_slices:
        lines.append(f"- {_slug(s['title'])}: {s['title']}")
    (run_dir / "briefs" / "seed.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_fan_briefs(run_dir: Path, capped_slices: list[dict]) -> list[Path]:
    paths: list[Path] = []
    briefs = run_dir / "briefs"
    for idx, s in enumerate(capped_slices):
        section_id = _slug(s["title"])
        payload = {
            "section_id": section_id,
            "title": s["title"],
            "facts": s.get("facts", []),
            "reading": s.get("reading", {}),
        }
        body = [
            f"# Fan brief — {s['title']}",
            "",
            f"Write the merchant-facing prose for section `{section_id}`.",
            "Ground every number in the facts below. Do not invent numbers or causal claims.",
            "Return JSON only: {\"section_id\", \"title\", \"body\"}.",
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
        path = briefs / f"fan_{idx:02d}_{section_id}.md"
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def prepare_run(
    run_dir,
    *,
    results: dict,
    facts_json: dict,
    report_name: str,
    project_root=None,
    force: bool = False,
) -> dict:
    """Initialize a run directory: state.json + seed/fan briefs + domain_slices.json.

    Raises FileExistsError if an unfinished run already exists and force is False.
    """
    run_dir = Path(run_dir)
    existing = _load_state(run_dir)
    if existing is not None and existing.get("stage") not in _TERMINAL_STAGES and not force:
        raise FileExistsError(
            f"run at {run_dir} is at stage {existing.get('stage')!r}; pass force=True to overwrite"
        )

    (run_dir / "briefs").mkdir(parents=True, exist_ok=True)

    slices = list(results.get("domain_slices", []))
    capped, merged = _cap_slices(slices)

    (run_dir / "domain_slices.json").write_text(
        json.dumps(
            {
                "capped": capped,
                "merged_sections": merged,
                "blocked_modules": list(results.get("blocked_modules", [])),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_seed_brief(run_dir, capped, report_name)
    _write_fan_briefs(run_dir, capped)

    state = {
        "stage": "seed",
        "report_name": report_name,
        "facts_hash": facts_json.get("facts_hash", ""),
        "merged_sections": merged,
        "sections": {},
        "history": ["prepared"],
        "degradation_reason": None,
        "project_root": str(project_root) if project_root else None,
    }
    _write_state(run_dir, state)
    # persist facts.json alongside state for downstream gate/fallback
    (run_dir / "facts.json").write_text(
        json.dumps(facts_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/orchestration/narrative_workflow.py \
        tests/orchestration/test_narrative_workflow.py
git commit -m "$(cat <<'EOF'
feat(orchestration): workflow state + briefs + lossless slice cap + overwrite guard

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 3: Ingestion with JSON tolerance + stage guards

**Files:**
- Modify: `xhs_ceramics_analytics/orchestration/narrative_workflow.py`
- Test: `tests/orchestration/test_narrative_workflow.py`

**Interfaces:**
- Consumes: `state.json` from Task 2.
- Produces:
  - `extract_json(text: str) -> dict | list` — tolerant parser: raw JSON, then fenced ```json blocks, then first balanced `{}`/`[]`; raises `ValueError` if none.
  - `_EXPECTED_STATUS: dict[str, set[str]]` — stage→allowed-current-stage guard.
  - `ingest_output(run_dir, *, stage, source=None, text=None, section_id=None) -> dict` — validates current stage against `_EXPECTED_STATUS`, extracts JSON, records into `state["sections"]` keyed by canonical `section_id`; raises `ValueError` on stage mismatch.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/orchestration/test_narrative_workflow.py

def test_extract_json_raw():
    assert nw.extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    text = "prose before\n```json\n{\"a\": 2}\n```\ntrailing"
    assert nw.extract_json(text) == {"a": 2}


def test_extract_json_balanced_scan():
    text = "the model said: {\"section_id\": \"x\", \"body\": \"hi 🍵\"} thanks!"
    assert nw.extract_json(text) == {"section_id": "x", "body": "hi 🍵"}


def test_extract_json_raises_when_absent():
    with pytest.raises(ValueError):
        nw.extract_json("no json here at all")


def test_ingest_rejects_wrong_stage(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    # stage is 'seed'; ingesting a 'fan' result is out of order
    with pytest.raises(ValueError):
        nw.ingest_output(tmp_path, stage="fan", text='{"section_id": "域0", "body": "x"}')


def test_ingest_seed_records_sections(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    payload = '{"sections": [{"section_id": "域0", "title": "域0", "body": "b0 🍶"}]}'
    state = nw.ingest_output(tmp_path, stage="seed", text=payload)
    assert "域0" in state["sections"]
    assert state["sections"]["域0"]["body"] == "b0 🍶"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -k "extract_json or ingest" -v`
Expected: FAIL — `extract_json`/`ingest_output` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# add to narrative_workflow.py

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_EXPECTED_STATUS = {
    "seed": {"seed"},
    "fan": {"fan"},
    "synth": {"synth"},
    "patch": {"patch"},
    "continuity": {"continuity"},
}


def _scan_balanced(text: str):
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break
    return None


def extract_json(text: str):
    """Parse JSON tolerantly: raw, then fenced, then first balanced block."""
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for match in _FENCE_RE.finditer(text):
        inner = match.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            continue
    scanned = _scan_balanced(text)
    if scanned is not None:
        return scanned
    raise ValueError("no parseable JSON found in text")


def _record_section(state: dict, section: dict) -> None:
    title = section.get("title") or section.get("section_id") or "section"
    section_id = _slug(section.get("section_id") or title)
    state["sections"][section_id] = {
        "section_id": section_id,
        "title": title,
        "body": section.get("body", ""),
    }


def ingest_output(run_dir, *, stage: str, source=None, text=None, section_id=None) -> dict:
    """Ingest a sub-agent result for the given stage, guarding stage order."""
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")

    allowed = _EXPECTED_STATUS.get(stage)
    if allowed is None:
        raise ValueError(f"unknown stage {stage!r}")
    if state["stage"] not in allowed:
        raise ValueError(
            f"cannot ingest {stage!r} while run is at stage {state['stage']!r}"
        )

    if text is None:
        if source is None:
            raise ValueError("provide either source or text")
        text = Path(source).read_text(encoding="utf-8")
    parsed = extract_json(text)

    if isinstance(parsed, dict) and "sections" in parsed:
        for section in parsed["sections"]:
            _record_section(state, section)
    elif isinstance(parsed, dict):
        if section_id and "section_id" not in parsed:
            parsed = {**parsed, "section_id": section_id}
        _record_section(state, parsed)
    elif isinstance(parsed, list):
        for section in parsed:
            _record_section(state, section)
    else:
        raise ValueError("ingested JSON is neither an object nor a list of sections")

    state.setdefault("history", []).append(f"ingest:{stage}")
    _write_state(run_dir, state)
    return state
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -v`
Expected: PASS (all Task 2 + Task 3 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/orchestration/narrative_workflow.py \
        tests/orchestration/test_narrative_workflow.py
git commit -m "$(cat <<'EOF'
feat(orchestration): tolerant JSON ingestion with stage-order guards

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 4: Advance, gate integration, patch/continuity, machine-readable status

**Files:**
- Modify: `xhs_ceramics_analytics/orchestration/narrative_workflow.py`
- Test: `tests/orchestration/test_narrative_workflow.py`

**Interfaces:**
- Consumes: `reporting/narrative_render.py::render_draft(bundle, facts_json) -> dict`, `apply_continuity_edits(bundle, edits) -> dict`; `reporting/factcheck_gate.py::run_gate(bundle, facts_json) -> GateReport` (`.status` in {"PASS","FAIL"}, `.hard_failures`, `.bundle`).
- Produces:
  - `_bundle_from_state(state) -> dict` — assembles a bundle `{"sections": [...]}` from recorded sections, in prepared order.
  - `MAX_GATE_ROUNDS: int = 2`.
  - `advance_run(run_dir, *, project_root=None) -> dict` — moves stage seed→fan→synth→gate→(patch→gate)*→continuity→gate→finalized; on gate exhaustion routes to `finalize_deterministic` and sets stage `blocked`.
  - `status_json(run_dir) -> dict` — `{"stage", "next_action", "briefs", "degradation_reason", "merged_sections"}`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/orchestration/test_narrative_workflow.py

def test_status_json_reports_next_action(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    status = nw.status_json(tmp_path)
    assert status["stage"] == "seed"
    assert "next_action" in status and status["next_action"]
    assert status["briefs"]  # seed brief listed
    assert status["merged_sections"] == []


def test_advance_seed_to_fan(tmp_path):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")
    nw.ingest_output(tmp_path, stage="seed",
                     text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    state = nw.advance_run(tmp_path)
    assert state["stage"] == "fan"


def test_advance_exhausted_gate_routes_to_deterministic(tmp_path, monkeypatch):
    results, facts_json = _bundle_inputs(3)
    nw.prepare_run(tmp_path, results=results, facts_json=facts_json, report_name="r")

    # force the gate to always FAIL so rounds exhaust
    class _Fail:
        status = "FAIL"
        hard_failures = [{"section_id": "域0", "reason": "number mismatch"}]
        bundle = {"sections": []}

    monkeypatch.setattr(nw, "run_gate", lambda bundle, facts: _Fail())
    called = {}
    monkeypatch.setattr(
        nw, "finalize_deterministic",
        lambda rd, *, project_root=None, reason: called.setdefault("reason", reason) or {"stage": "blocked"},
    )

    # fast-forward to gate: seed→fan→synth
    nw.ingest_output(tmp_path, stage="seed", text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    nw.advance_run(tmp_path)  # fan
    nw.ingest_output(tmp_path, stage="fan", text='{"section_id":"域0","title":"域0","body":"b"}')
    nw.advance_run(tmp_path)  # synth
    nw.ingest_output(tmp_path, stage="synth", text='{"sections":[{"section_id":"域0","title":"域0","body":"b"}]}')
    # gate rounds: each advance re-fails; after MAX_GATE_ROUNDS → deterministic
    for _ in range(nw.MAX_GATE_ROUNDS + 2):
        state = nw.advance_run(tmp_path)
        if state["stage"] == "blocked":
            break
    assert called["reason"] == "gate_exhausted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -k "advance or status_json" -v`
Expected: FAIL — `advance_run`/`status_json`/`MAX_GATE_ROUNDS` undefined.

- [ ] **Step 3: Write minimal implementation**

```python
# add imports at top of narrative_workflow.py
from xhs_ceramics_analytics.reporting.narrative_render import (
    render_draft,
    apply_continuity_edits,
)
from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate

# add near MAX_FAN_AGENTS
MAX_GATE_ROUNDS = 2

_NEXT_ACTION = {
    "seed": "read briefs/seed.md, spawn one sub-agent, ingest --stage seed, then advance",
    "fan": "read briefs/fan_*.md, spawn one sub-agent per brief, ingest --stage fan each, then advance",
    "synth": "read the recorded sections, spawn one sub-agent, ingest --stage synth, then advance",
    "gate": "run advance to apply the deterministic fact-check gate",
    "patch": "read gate failures, spawn one sub-agent, ingest --stage patch, then advance",
    "continuity": "spawn one sub-agent to smooth transitions, ingest --stage continuity, then advance",
    "finalized": "done — deliver <name>.md + <name>.html",
    "blocked": "deterministic skeleton delivered — report degradation reason",
}


def _bundle_from_state(state: dict) -> dict:
    return {"sections": list(state.get("sections", {}).values())}


def status_json(run_dir) -> dict:
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    stage = state["stage"]
    briefs_dir = run_dir / "briefs"
    if stage == "seed":
        briefs = [str(briefs_dir / "seed.md")]
    elif stage == "fan":
        briefs = [str(p) for p in sorted(briefs_dir.glob("fan_*.md"))]
    else:
        briefs = []
    return {
        "stage": stage,
        "next_action": _NEXT_ACTION.get(stage, ""),
        "briefs": briefs,
        "degradation_reason": state.get("degradation_reason"),
        "merged_sections": state.get("merged_sections", []),
    }


def advance_run(run_dir, *, project_root=None) -> dict:
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    stage = state["stage"]
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    project_root = project_root or state.get("project_root")

    if stage == "seed":
        state["stage"] = "fan"
    elif stage == "fan":
        state["stage"] = "synth"
    elif stage == "synth":
        # render the draft bundle, then gate it
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["_gate_rounds"] = 0
        state["stage"] = "gate"
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "gate":
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "patch":
        # patched sections already ingested; re-render + gate
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["stage"] = "gate"
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "continuity":
        edits = state.get("_continuity_edits", [])
        bundle = apply_continuity_edits(state.get("_bundle", _bundle_from_state(state)), edits)
        state["_bundle"] = bundle
        report = run_gate(bundle, facts_json)
        if report.status == "PASS":
            state["stage"] = "finalized"
        else:
            return _route_deterministic(run_dir, state, project_root, "continuity_gate_failed")
    _write_state(run_dir, state)
    return state


def _run_gate_stage(run_dir, state, facts_json, project_root) -> dict:
    report = run_gate(state.get("_bundle", _bundle_from_state(state)), facts_json)
    if report.status == "PASS":
        state["stage"] = "continuity"
        _write_state(run_dir, state)
        return state
    rounds = state.get("_gate_rounds", 0) + 1
    state["_gate_rounds"] = rounds
    if rounds > MAX_GATE_ROUNDS:
        return _route_deterministic(run_dir, state, project_root, "gate_exhausted")
    state["_gate_failures"] = list(report.hard_failures)
    state["stage"] = "patch"
    _write_state(run_dir, state)
    return state


def _route_deterministic(run_dir, state, project_root, reason) -> dict:
    finalize_deterministic(run_dir, project_root=project_root, reason=reason)
    state["stage"] = "blocked"
    state["degradation_reason"] = reason
    _write_state(run_dir, state)
    return state
```

Add a forward-reference stub so imports resolve until Task 5 replaces it. The Task 4 test monkeypatches `finalize_deterministic`, so the stub is never actually executed here; Task 5's tests exercise the real one:

```python
def finalize_deterministic(run_dir, *, project_root=None, reason):  # noqa: D401
    """Deterministic skeleton fallback — full implementation in Task 5."""
    raise NotImplementedError("finalize_deterministic implemented in Task 5")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -v`
Expected: PASS (advance/status tests green; deterministic routing uses the stub via monkeypatch).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/orchestration/narrative_workflow.py \
        tests/orchestration/test_narrative_workflow.py
git commit -m "$(cat <<'EOF'
feat(orchestration): advance/gate/patch/continuity + machine-readable status

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 5: Deterministic skeleton fallback (`finalize_deterministic`)

**Files:**
- Modify: `xhs_ceramics_analytics/orchestration/narrative_workflow.py`
- Test: `tests/orchestration/test_narrative_workflow.py`

**Interfaces:**
- Consumes: `reporting/html.py::render_markdown_document_html(markdown_text, title=None) -> str`; `reporting/report_telemetry.py::build_run_record`, `append_run_record`; `domain_slices.json`, `facts.json`, `state.json` from the run dir.
- Produces:
  - `_deterministic_markdown(run_dir, facts_json, report_name) -> str` — builds a "确定性骨架版" report from the capped slices' conclusions/actions/caveats + a facts table + an explicit "暂时答不了的问题" list, preserving evidence tiers.
  - `finalize_deterministic(run_dir, *, project_root=None, reason) -> dict` — writes `<name>.md` + `<name>.html` under `<project_root>/.xhs-ceramics-analytics/outputs/`, records telemetry `mode="skeleton"`, sets stage `blocked`, returns state.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/orchestration/test_narrative_workflow.py

def test_finalize_deterministic_writes_two_artifacts(tmp_path):
    results = {"domain_slices": [
        {"title": "生意大盘", "facts": [{"metric": "GMV", "value": 12345}],
         "reading": {"conclusion": "大盘平稳", "action": "维持投放", "caveats": ["口径：支付时间"]}},
    ]}
    facts_json = {"facts_hash": "h1", "numbers": {"GMV": 12345}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="确定性报告", project_root=project_root)

    state = nw.finalize_deterministic(run_dir, project_root=project_root, reason="denied")
    assert state["stage"] == "blocked"
    assert state["degradation_reason"] == "denied"

    out = project_root / ".xhs-ceramics-analytics" / "outputs"
    md = out / "确定性报告.md"
    html = out / "确定性报告.html"
    assert md.exists() and html.exists()
    body = md.read_text(encoding="utf-8")
    assert "确定性骨架版" in body
    assert "大盘平稳" in body       # conclusion preserved
    assert "口径：支付时间" in body   # caveat preserved verbatim
    assert "12,345" in body or "12345" in body  # fact rendered


def test_deterministic_lists_unanswerable_questions(tmp_path):
    results = {
        "domain_slices": [{"title": "流量", "facts": [], "reading": {"conclusion": "c"}}],
        "blocked_modules": [{"slug": "search_efficiency_diagnosis", "reason": "缺少搜索词表"}],
    }
    facts_json = {"facts_hash": "h2", "numbers": {}}
    project_root = tmp_path / "proj"
    project_root.mkdir()
    run_dir = tmp_path / "run"
    nw.prepare_run(run_dir, results=results, facts_json=facts_json,
                   report_name="r", project_root=project_root)
    nw.finalize_deterministic(run_dir, project_root=project_root, reason="unsupported")
    body = (project_root / ".xhs-ceramics-analytics" / "outputs" / "r.md").read_text(encoding="utf-8")
    assert "暂时答不了的问题" in body
    assert "缺少搜索词表" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -k "deterministic" -v`
Expected: FAIL — `finalize_deterministic` is still the NotImplementedError stub.

- [ ] **Step 3: Write minimal implementation (replace the Task 4 stub)**

```python
# add imports near the other reporting imports
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
from xhs_ceramics_analytics.reporting.report_telemetry import (
    build_run_record,
    append_run_record,
)


def _fmt_value(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _deterministic_markdown(run_dir, facts_json, report_name: str) -> str:
    run_dir = Path(run_dir)
    slices_doc = json.loads((run_dir / "domain_slices.json").read_text(encoding="utf-8"))
    capped = slices_doc.get("capped", [])

    lines = [
        f"# {report_name}（确定性骨架版）",
        "",
        "> 本报告为确定性骨架版：多智能体叙事流程未能完成，"
        "以下内容直接来自确定性分析层（L1）与唯一数字源（L2），未经叙事改写。",
        "",
    ]
    for s in capped:
        title = s.get("title", "")
        reading = s.get("reading", {})
        lines.append(f"## {title}")
        lines.append("")
        if reading.get("conclusion"):
            lines.append(f"**结论：** {reading['conclusion']}")
            lines.append("")
        if reading.get("action"):
            lines.append(f"**建议动作：** {reading['action']}")
            lines.append("")
        facts = s.get("facts", [])
        if facts:
            lines.append("| 指标 | 数值 |")
            lines.append("| --- | --- |")
            for f in facts:
                lines.append(f"| {f.get('metric', '')} | {_fmt_value(f.get('value', ''))} |")
            lines.append("")
        caveats = reading.get("caveats") or []
        for caveat in caveats:
            lines.append(f"> 口径/证据说明：{caveat}")
        if caveats:
            lines.append("")

    # unanswerable questions from blocked modules
    blocked = slices_doc.get("blocked_modules", [])
    if blocked:
        lines.append("## 暂时答不了的问题")
        lines.append("")
        for b in blocked:
            slug = b.get("slug", "")
            reason = b.get("reason", "")
            lines.append(f"- {slug}：{reason}")
        lines.append("")

    return "\n".join(lines) + "\n"


def finalize_deterministic(run_dir, *, project_root=None, reason) -> dict:
    """Write a deterministic skeleton report; never raises at the delivery boundary."""
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    project_root = Path(project_root or state.get("project_root") or ".")
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    report_name = state["report_name"]

    markdown = _deterministic_markdown(run_dir, facts_json, report_name)
    html = render_markdown_document_html(markdown, title=f"{report_name}（确定性骨架版）")

    out_dir = project_root / ".xhs-ceramics-analytics" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{report_name}.md").write_text(markdown, encoding="utf-8")
    (out_dir / f"{report_name}.html").write_text(html, encoding="utf-8")

    record = build_run_record(
        mode="skeleton",
        facts_hash=facts_json.get("facts_hash", ""),
        cache_hit=False,
        degradation_reason=reason,
    )
    append_run_record(out_dir / "run_telemetry.jsonl", record)

    state["stage"] = "blocked"
    state["degradation_reason"] = reason
    state.setdefault("history", []).append(f"finalize_deterministic:{reason}")
    _write_state(run_dir, state)
    return state
```

Delete the Task 4 `finalize_deterministic` stub (the NotImplementedError version) so only this real implementation remains.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_workflow.py -v`
Expected: PASS (all workflow tests, including the deterministic pair and the Task 4 gate-exhaustion routing).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/orchestration/narrative_workflow.py \
        tests/orchestration/test_narrative_workflow.py
git commit -m "$(cat <<'EOF'
feat(orchestration): deterministic skeleton fallback never fails open

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 6: Telemetry — add `blocked` mode, keep backward compatible

**Files:**
- Modify: `xhs_ceramics_analytics/reporting/report_telemetry.py`
- Test: `tests/reporting/test_report_telemetry.py` (extend)

**Interfaces:**
- Consumes: existing `build_run_record(*, mode, facts_hash, cache_hit, hard_fail_counts=None, degradation_reason=None) -> dict`; `_VALID_MODES`.
- Produces: `_VALID_MODES == ("frozen", "skeleton", "gate", "blocked")`; `build_run_record` accepts `mode="blocked"` and still round-trips old modes unchanged.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/reporting/test_report_telemetry.py
from xhs_ceramics_analytics.reporting.report_telemetry import build_run_record, _VALID_MODES


def test_blocked_mode_is_valid():
    assert "blocked" in _VALID_MODES
    rec = build_run_record(mode="blocked", facts_hash="h", cache_hit=False, degradation_reason="denied")
    assert rec["mode"] == "blocked"
    assert rec["degradation_reason"] == "denied"


def test_existing_modes_still_valid():
    for mode in ("frozen", "skeleton", "gate"):
        rec = build_run_record(mode=mode, facts_hash="h", cache_hit=False)
        assert rec["mode"] == mode


def test_unknown_mode_degrades_to_unknown():
    # Telemetry never raises (module contract) — an unrecognized mode degrades
    # to the sentinel "unknown" rather than propagating an exception.
    rec = build_run_record(mode="bogus", facts_hash="h", cache_hit=False)
    assert rec["mode"] == "unknown"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/reporting/test_report_telemetry.py -k "blocked or existing_modes or unknown_mode" -v`
Expected: FAIL — `"blocked"` not in `_VALID_MODES` (`test_blocked_mode_is_valid` fails; the never-raise degrade test already passes against current code).

- [ ] **Step 3: Write minimal implementation**

```python
# in report_telemetry.py — extend the tuple; keep the never-raise contract intact
_VALID_MODES = ("frozen", "skeleton", "gate", "blocked")
```

Also update the two docstrings that enumerate the modes so they stay accurate:
the module docstring's `mode (frozen / skeleton / gate)` → `mode (frozen / skeleton / gate / blocked)`, and `build_run_record`'s `mode ∈ {frozen, skeleton, gate}` → `mode ∈ {frozen, skeleton, gate, blocked}`. Do NOT add any validation that raises — an unknown mode must still degrade to `"unknown"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/reporting/test_report_telemetry.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/report_telemetry.py \
        tests/reporting/test_report_telemetry.py
git commit -m "$(cat <<'EOF'
feat(reporting): telemetry accepts blocked mode, backward compatible

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 7: CLI `narrative` sub-app (prepare/status/ingest/advance/finalize-deterministic)

**Files:**
- Modify: `xhs_ceramics_analytics/cli.py`
- Test: `tests/orchestration/test_narrative_cli.py`

**Interfaces:**
- Consumes: `narrative_workflow.prepare_run/status_json/ingest_output/advance_run/finalize_deterministic`; existing `cli.py` conventions (`import typer`, `from typing import Annotated`, `app = typer.Typer(...)`, `Annotated[Path | None, ...]`).
- Produces: Typer sub-app `narrative` mounted on the root `app` with five commands. `status --json` prints machine-readable JSON to stdout. `prepare` accepts `--force`. `finalize-deterministic` accepts `--reason`.

- [ ] **Step 1: Write the failing test**

```python
# tests/orchestration/test_narrative_cli.py
import json
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app

runner = CliRunner()


def _write_inputs(tmp_path):
    results = {"domain_slices": [
        {"title": "生意大盘", "facts": [{"metric": "GMV", "value": 100}],
         "reading": {"conclusion": "平稳", "caveats": ["口径：支付时间"]}},
    ]}
    facts = {"facts_hash": "h", "numbers": {"GMV": 100}}
    (tmp_path / "results.json").write_text(json.dumps(results), encoding="utf-8")
    (tmp_path / "facts.json").write_text(json.dumps(facts), encoding="utf-8")


def test_prepare_and_status_json(tmp_path):
    _write_inputs(tmp_path)
    run_dir = tmp_path / "run"
    res = runner.invoke(app, [
        "narrative", "prepare",
        "--run-dir", str(run_dir),
        "--results", str(tmp_path / "results.json"),
        "--facts", str(tmp_path / "facts.json"),
        "--name", "报告",
        "--project-root", str(tmp_path),
    ])
    assert res.exit_code == 0, res.output

    res = runner.invoke(app, ["narrative", "status", "--run-dir", str(run_dir), "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.stdout)
    assert payload["stage"] == "seed"
    assert payload["next_action"]


def test_prepare_force_flag(tmp_path):
    _write_inputs(tmp_path)
    run_dir = tmp_path / "run"
    base = ["narrative", "prepare", "--run-dir", str(run_dir),
            "--results", str(tmp_path / "results.json"),
            "--facts", str(tmp_path / "facts.json"),
            "--name", "报告", "--project-root", str(tmp_path)]
    assert runner.invoke(app, base).exit_code == 0
    # second prepare without --force fails
    assert runner.invoke(app, base).exit_code != 0
    # with --force succeeds
    assert runner.invoke(app, base + ["--force"]).exit_code == 0


def test_finalize_deterministic_cli(tmp_path):
    _write_inputs(tmp_path)
    run_dir = tmp_path / "run"
    runner.invoke(app, [
        "narrative", "prepare", "--run-dir", str(run_dir),
        "--results", str(tmp_path / "results.json"),
        "--facts", str(tmp_path / "facts.json"),
        "--name", "报告", "--project-root", str(tmp_path),
    ])
    res = runner.invoke(app, [
        "narrative", "finalize-deterministic",
        "--run-dir", str(run_dir), "--reason", "denied",
    ])
    assert res.exit_code == 0, res.output
    md = tmp_path / ".xhs-ceramics-analytics" / "outputs" / "报告.md"
    assert md.exists()
    assert "确定性骨架版" in md.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_cli.py -v`
Expected: FAIL — no `narrative` command group registered.

- [ ] **Step 3: Write minimal implementation**

```python
# in cli.py — add near the other imports (Annotated + typer already imported)
import json as _json

from xhs_ceramics_analytics.orchestration import narrative_workflow as _nw

narrative_app = typer.Typer(help="Drive the file-based narrative workflow.")
app.add_typer(narrative_app, name="narrative")


@narrative_app.command("prepare")
def narrative_prepare(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    results: Annotated[Path, typer.Option("--results")],
    facts: Annotated[Path, typer.Option("--facts")],
    name: Annotated[str, typer.Option("--name")],
    project_root: Annotated[Path | None, typer.Option("--project-root")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    results_doc = _json.loads(results.read_text(encoding="utf-8"))
    facts_doc = _json.loads(facts.read_text(encoding="utf-8"))
    try:
        state = _nw.prepare_run(
            run_dir, results=results_doc, facts_json=facts_doc,
            report_name=name, project_root=project_root, force=force,
        )
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    typer.echo(f"prepared: stage={state['stage']} merged={state['merged_sections']}")


@narrative_app.command("status")
def narrative_status(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    payload = _nw.status_json(run_dir)
    if as_json:
        typer.echo(_json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"stage={payload['stage']}  next={payload['next_action']}")


@narrative_app.command("ingest")
def narrative_ingest(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    stage: Annotated[str, typer.Option("--stage")],
    source: Annotated[Path | None, typer.Option("--source")] = None,
    section_id: Annotated[str | None, typer.Option("--section-id")] = None,
) -> None:
    try:
        state = _nw.ingest_output(run_dir, stage=stage, source=source, section_id=section_id)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1)
    typer.echo(f"ingested {stage}: {len(state['sections'])} section(s) recorded")


@narrative_app.command("advance")
def narrative_advance(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
) -> None:
    state = _nw.advance_run(run_dir)
    typer.echo(f"stage={state['stage']}")


@narrative_app.command("finalize-deterministic")
def narrative_finalize_deterministic(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    reason: Annotated[str, typer.Option("--reason")],
) -> None:
    state = _nw.finalize_deterministic(run_dir, reason=reason)
    typer.echo(f"stage={state['stage']} reason={state['degradation_reason']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/orchestration/test_narrative_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/cli.py tests/orchestration/test_narrative_cli.py
git commit -m "$(cat <<'EOF'
feat(cli): narrative sub-app — prepare/status/ingest/advance/finalize-deterministic

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Task 8: SKILL wiring + runtime mirror sync + full-suite verify

**Files:**
- Modify: `skills/data-analyze-for-zcl/SKILL.md`
- Invoke: `scripts/sync-runtime`
- Test: full suite + a manual dry-run note.

**Interfaces:**
- Consumes: everything above.
- Produces: SKILL section 7b (host-neutral) pointing at the runbook; in-repo mirror updated so the installed runtime carries the new controller.

- [ ] **Step 1: Add SKILL section 7b (host-neutral)**

Insert after the step-7 block in `skills/data-analyze-for-zcl/SKILL.md`:

```markdown
### 7b. Optional: multi-agent narrative report (host with sub-agents)

When the host agent can spawn sub-agents and a more readable, merchant-facing
narrative is wanted on top of the deterministic report, drive the narrative
workflow instead of composing directly:

1. Produce the deterministic results + `facts.json` as usual.
2. Follow `assets/xhs-ca/orchestration/runbook.md` exactly: `prepare` →
   ask the user once to authorize spawning → `status --json` → map briefs to
   spawns → `ingest` each result → `advance` → loop until stage is `finalized`
   or `blocked`.
3. If the user declines, the host cannot spawn, or the gate never passes, run
   `xhs-ca narrative finalize-deterministic --run-dir <dir> --reason <reason>`
   (or let `advance` route there automatically). A "确定性骨架版" report is
   always delivered — the deliverable never fails open.

The workflow still yields exactly two artifacts (`<name>.md` + `<name>.html`).
The run directory is durable scratch, not a deliverable.
```

- [ ] **Step 2: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS — all prior tests plus the new orchestration tests. (Runtime-mirror suite remains 278 passed + 3 skipped by design; total count rises by the new tests.)

- [ ] **Step 3: Lint**

Run: `.venv/bin/ruff check .`
Expected: clean.

- [ ] **Step 4: Sync the in-repo runtime mirror**

Run: `scripts/sync-runtime`
Expected: `skills/data-analyze-for-zcl/assets/xhs-ca` now contains `xhs_ceramics_analytics/orchestration/` and the updated `cli.py`/`report_telemetry.py`.

- [ ] **Step 5: Manual dry-run note (no real export needed)**

Run a controller-only smoke test to confirm the file protocol end-to-end without spawning:

```bash
.venv/bin/python - <<'PY'
import json, tempfile
from pathlib import Path
from xhs_ceramics_analytics.orchestration import narrative_workflow as nw

d = Path(tempfile.mkdtemp())
results = {"domain_slices": [{"title": "生意大盘", "facts": [{"metric": "GMV", "value": 100}],
           "reading": {"conclusion": "平稳", "caveats": ["口径：支付时间"]}}]}
facts = {"facts_hash": "h", "numbers": {"GMV": 100}}
nw.prepare_run(d, results=results, facts_json=facts, report_name="冒烟", project_root=d)
print(nw.status_json(d)["next_action"])
nw.finalize_deterministic(d, reason="denied")
print((d / ".xhs-ceramics-analytics" / "outputs" / "冒烟.md").read_text(encoding="utf-8")[:120])
PY
```
Expected: prints the seed next-action, then the first lines of the skeleton report including "确定性骨架版".

- [ ] **Step 6: Commit**

```bash
git add skills/data-analyze-for-zcl/SKILL.md skills/data-analyze-for-zcl/assets/xhs-ca
git commit -m "$(cat <<'EOF'
docs(skill): wire narrative workflow 7b + sync runtime mirror

via [HAPI](https://hapi.run)

Co-Authored-By: HAPI <noreply@hapi.run>
EOF
)"
```

---

## Self-Review

**1. Spec coverage:**
- 🔴 HIGH silent truncation → Task 2 `_cap_slices` lossless fold + `merged_sections` in state/domain_slices.json. ✔
- 🟠 MED ingest state guards → Task 3 `_EXPECTED_STATUS`. ✔
- 🟠 MED prepare overwrite protection → Task 2 `force` + `FileExistsError`. ✔
- 🟠 MED section_id namespace → Task 2 `_slug` canonical everywhere; Task 3 records by `_slug`; Task 4 synth reuses fan ids via `_bundle_from_state`. ✔
- 🟡 LOW dag.md banned-phrase explicit deletion + neutrality → Task 1 test asserts absence + neutrality. ✔
- Codex Fix A (runbook + machine-readable next-action) → Task 1 runbook + Task 4 `status_json` + Task 7 `status --json`. ✔
- Codex Fix B (JSON tolerance) → Task 3 `extract_json`. ✔
- Codex Fix C (auto skeleton on blocked/denied/gate-exhausted) → Task 5 `finalize_deterministic` + Task 4 routing + Task 7 CLI. ✔
- Telemetry blocked mode → Task 6. ✔
- SKILL wiring + mirror sync → Task 8. ✔

**2. Placeholder scan:** No "TBD"/"handle edge cases" left. The only forward reference is Task 4's `finalize_deterministic` stub, explicitly replaced in Task 5 (documented; monkeypatched in Task 4's test so the stub never executes, exercised for real in Task 5).

**3. Type consistency:** `render_draft`/`apply_continuity_edits` return `dict`; `run_gate` returns `GateReport` with `.status`/`.hard_failures`/`.bundle`. `_bundle_from_state` returns `{"sections": [...]}` matching what `render_draft`/`run_gate` consume. `_slug` used identically in briefs, ingest, and bundle assembly. `build_run_record` signature unchanged (only `_VALID_MODES` widened). CLI options use `Annotated[Path | None, ...]` per existing `cli.py` convention. `MAX_FAN_AGENTS = 6` and `MAX_GATE_ROUNDS = 2` referenced consistently in code and tests.

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-07-07-codex-narrative-workflow.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
