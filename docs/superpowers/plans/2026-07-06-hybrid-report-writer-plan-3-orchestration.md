# Hybrid Report Writer — Plan 3: Orchestration Contract + Skill Wiring

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the host-neutral orchestration contract (`orchestration/dag.md`, `schemas/*.json`,
`prompts/*.md`), the optional Claude-Code accelerator `report_writer_workflow.js`, per-run telemetry
(`report_runs.jsonl`), the `run`→facts.json emission that makes the cache checkpoint reachable, and
the SKILL.md step-7b + mirror wiring — so any host (Claude Code, Codex, agent-less) can drive the L3
DAG against the deterministic layer built in Plans 1–2.

**Architecture:** Plans 1–2 delivered the whole 0-agent Python spine (facts_export → gate →
render/freeze/skeleton, all `xhs-ca` subcommands). Plan 3 adds the *portable contract* every host
reads to run the multi-agent writer, plus the glue: `run` now emits `facts.json` beside the report
(the cache key source), a telemetry module records each run's mode/degradation/hard-fail counts, and
SKILL.md gains the host-neutral step 7b. The agent DAG itself is host-driven per `orchestration/dag.md`
— the shipped `run auto` stays 0-agent; the accelerator `.js` is a Claude-Code convenience that reads
the same neutral prompts. Nothing hard-binds an Anthropic model: tiers are `judgment/high` and
`draft/medium`.

**Tech Stack:** Python 3.14 stdlib (`json`, `pathlib`), Typer CLI, existing `reporting/` modules,
static JSON/Markdown assets, one JS workflow script (Claude-Code adapter), bash mirror script. Tests:
pytest via `.venv/bin/python -m pytest`. `jsonschema` is **NOT** a dependency — schema tests use
stdlib `json` structural assertions only.

## Global Constraints

- Python 3.14; `.venv/bin/python` is THE interpreter. Ruff line-length 100.
- Modules never raise; degrade + record. Emoji is real merchant content — never strip.
- No Co-Authored-By trailer. Commit/push/发布 only on explicit user request.
- Model selection is **role tier + reasoning effort** (`judgment/high`, `draft/medium`), NEVER a
  model id — the contract must run on Claude Code AND Codex AND an agent-less host.
- `orchestration/` lives at the **repo root** (sibling of `references/`, `task_templates/`), so
  `scripts/sync-runtime`'s rsync mirrors it into `skills/data-analyze-for-zcl/assets/xhs-ca/`.
- The shipped `run auto` path stays 0-agent. The `.js` is an optional accelerator, not the source of
  truth; the neutral `orchestration/` assets are.
- After code: run `scripts/sync-runtime`, regen the real-data demo, verify exactly two artifacts.

## Interfaces already shipped (Plans 1–2), consumed here

- `reporting/facts_export.py`: `build_factbook(results, *, blocked_modules=()) -> FactBook`,
  `factbook_to_json(book) -> str`, `facts_hash(book) -> str`.
- `reporting/factcheck_gate.py`: `run_gate(bundle, facts_json) -> GateReport`
  (`.status`, `.hard_failures`, `.warnings`, `.capped_claims`, `.bundle`).
- `reporting/frozen_narrative.py`: `narrative_schema_version()`, `renderer_version()`,
  `load_frozen(path)`, `is_cache_hit(frozen, facts_hash)`.
- `reporting/narrative_render.py`: `render_frozen(frozen, facts_json) -> (md, html)`,
  `skeleton_markdown(results, *, title=None) -> str`.
- CLI (`cli.py`): commands `run`, `facts`, `gate`, `render-draft`, `finalize`, `render-frozen`,
  `skeleton`, `coverage`; `outputs_dir(project_root)`, `state_dir(project_root)`.

## File structure & task map

| Task | File(s) | Responsibility | Depends on |
|---|---|---|---|
| T1 | `reporting/report_telemetry.py` + test | per-run record builder + jsonl appender | facts_export |
| T2 | `orchestration/schemas/*.json` (7) + test | host-neutral handoff JSON Schemas | — |
| T3 | `orchestration/dag.md`, `orchestration/prompts/*.md` (5) + test | DAG doc + per-role prompts | — |
| T4 | `.xhs-ceramics-analytics/report_writer_workflow.js` + test | Claude-Code accelerator | T2, T3 (reads them) |
| T5 | `cli.py` (modify) + test | `run` emits facts.json; `render-frozen`/`skeleton` emit telemetry | T1 |
| T6 | `scripts/sync-runtime`, `SKILL.md` (modify) + test | mirror `orchestration/`; add step 7b | — |

T1, T2, T3, T4, T6 touch distinct files (parallel-safe among themselves; T4 only *reads* T2/T3 output
at test time, so run it after them). T5 edits the shared `cli.py` and imports T1, so it runs last.

---

### Task 1: Per-run telemetry (`report_telemetry.py`)

**Files:**
- Create: `xhs_ceramics_analytics/reporting/report_telemetry.py`
- Test: `tests/test_reporting_report_telemetry.py`

**Interfaces:**
- Produces:
  - `build_run_record(*, mode: str, facts_hash: str, cache_hit: bool, hard_fail_counts: dict | None
    = None, degradation_reason: str | None = None) -> dict` — a plain, deterministic dict (no
    timestamp; the harness has no wall clock in tests and the spec forbids nondeterminism in the
    hashed/replayed path). `mode ∈ {"frozen", "skeleton", "gate"}`.
  - `append_run_record(path, record: dict) -> None` — append one canonical JSON line
    (sorted keys, `ensure_ascii=False`) to `report_runs.jsonl`, creating parent dirs. Never raises on
    a normal filesystem; a non-dict record is coerced to `{"error": "invalid_record"}` rather than
    crashing the report path.
  - `summarize_runs(records: list[dict]) -> str` — a one-line human summary for the skill's step-9
    delivery note (`"3 runs: 2 frozen, 1 skeleton (1 gate hard-fail)"`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reporting_report_telemetry.py
import json

from xhs_ceramics_analytics.reporting import report_telemetry as rt


def test_build_run_record_is_deterministic():
    a = rt.build_run_record(mode="frozen", facts_hash="abc", cache_hit=True)
    b = rt.build_run_record(mode="frozen", facts_hash="abc", cache_hit=True)
    assert a == b
    assert a["mode"] == "frozen"
    assert a["facts_hash"] == "abc"
    assert a["cache_hit"] is True
    assert a["hard_fail_counts"] == {}
    assert a["degradation_reason"] is None


def test_build_run_record_carries_skeleton_reason():
    rec = rt.build_run_record(mode="skeleton", facts_hash="h", cache_hit=False,
                              hard_fail_counts={"SUMMED_POOLS": 2},
                              degradation_reason="gate_exhausted")
    assert rec["mode"] == "skeleton"
    assert rec["degradation_reason"] == "gate_exhausted"
    assert rec["hard_fail_counts"] == {"SUMMED_POOLS": 2}


def test_append_run_record_writes_one_jsonl_line(tmp_path):
    path = tmp_path / "sub" / "report_runs.jsonl"
    rt.append_run_record(path, rt.build_run_record(mode="frozen", facts_hash="h1", cache_hit=False))
    rt.append_run_record(path, rt.build_run_record(mode="skeleton", facts_hash="h2", cache_hit=False))
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["facts_hash"] == "h1"
    assert json.loads(lines[1])["mode"] == "skeleton"


def test_append_run_record_coerces_non_dict(tmp_path):
    path = tmp_path / "report_runs.jsonl"
    rt.append_run_record(path, ["not", "a", "dict"])
    line = json.loads(path.read_text(encoding="utf-8").strip())
    assert line == {"error": "invalid_record"}


def test_summarize_runs_counts_modes():
    records = [
        rt.build_run_record(mode="frozen", facts_hash="a", cache_hit=True),
        rt.build_run_record(mode="frozen", facts_hash="b", cache_hit=False),
        rt.build_run_record(mode="skeleton", facts_hash="c", cache_hit=False,
                            hard_fail_counts={"MISSING_FACT": 1}, degradation_reason="gate_exhausted"),
    ]
    summary = rt.summarize_runs(records)
    assert "3 runs" in summary
    assert "2 frozen" in summary
    assert "1 skeleton" in summary
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_reporting_report_telemetry.py -v`
Expected: FAIL with `ModuleNotFoundError: ...report_telemetry`.

- [ ] **Step 3: Write minimal implementation**

```python
# xhs_ceramics_analytics/reporting/report_telemetry.py
"""Per-run telemetry — the guard against a silently-degrading report.

Each report run appends one canonical JSON line to ``report_runs.jsonl`` recording
mode (frozen / skeleton / gate), the facts_hash, whether the frozen-narrative cache
hit, per-rule hard-fail counts, and a degradation reason code. The skill surfaces
``summarize_runs`` in its step-9 delivery note, so an over-strict gate rule cannot
make skeleton the silent default — the counters make it visible. Records are
timestamp-free by design (deterministic + replay-safe; the spec bars a wall clock in
the hashed path). Pure + never raises on a normal filesystem.
"""
import json
from collections import Counter
from pathlib import Path

_VALID_MODES = ("frozen", "skeleton", "gate")


def build_run_record(
    *,
    mode: str,
    facts_hash: str,
    cache_hit: bool,
    hard_fail_counts: dict | None = None,
    degradation_reason: str | None = None,
) -> dict:
    """Deterministic run record. mode ∈ {frozen, skeleton, gate}. No timestamp by design."""
    return {
        "mode": mode if mode in _VALID_MODES else "gate",
        "facts_hash": facts_hash,
        "cache_hit": bool(cache_hit),
        "hard_fail_counts": dict(hard_fail_counts or {}),
        "degradation_reason": degradation_reason,
    }


def append_run_record(path, record: dict) -> None:
    """Append one canonical JSON line to report_runs.jsonl. Coerces a non-dict to an error row."""
    if not isinstance(record, dict):
        record = {"error": "invalid_record"}
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False)
    with p.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def summarize_runs(records: list[dict]) -> str:
    """One-line human summary for the skill's step-9 delivery note."""
    modes = Counter(str(r.get("mode")) for r in records if isinstance(r, dict))
    hard = sum(
        sum((r.get("hard_fail_counts") or {}).values())
        for r in records
        if isinstance(r, dict)
    )
    parts = [f"{n} {mode}" for mode, n in sorted(modes.items())]
    tail = f" ({hard} gate hard-fail)" if hard else ""
    return f"{len(records)} runs: {', '.join(parts)}{tail}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_reporting_report_telemetry.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/reporting/report_telemetry.py \
        tests/test_reporting_report_telemetry.py
git commit -m "feat(reporting): per-run telemetry record + report_runs.jsonl appender"
```

---

### Task 2: Host-neutral handoff schemas (`orchestration/schemas/*.json`)

**Files:**
- Create: `orchestration/schemas/fact.json`, `spine_brief.json`, `claim.json`, `section_bundle.json`,
  `narrative_bundle.json`, `gate_report.json`, `continuity_edit.json`
- Test: `tests/test_orchestration_schemas.py`

**Interfaces:**
- Produces: seven JSON-Schema (draft 2020-12) files defining the handoff atoms every host serializes.
  They mirror the exact shapes `factcheck_gate.run_gate` / `narrative_render` consume (Plan 2), so a
  host that validates its agent output against these cannot emit a bundle the gate will reject on
  structure. `jsonschema` is not installed — the test asserts each file parses and is well-formed, and
  that the `claim`/`narrative_bundle` schemas name the exact fields the gate reads.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestration_schemas.py
import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parents[1] / "orchestration" / "schemas"
ROSTER = {
    "fact", "spine_brief", "claim", "section_bundle",
    "narrative_bundle", "gate_report", "continuity_edit",
}


def _load(name):
    return json.loads((SCHEMA_DIR / f"{name}.json").read_text(encoding="utf-8"))


def test_all_schemas_present():
    on_disk = {p.stem for p in SCHEMA_DIR.glob("*.json")}
    assert on_disk == ROSTER


def test_every_schema_is_wellformed_object_schema():
    for name in ROSTER:
        schema = _load(name)
        assert schema.get("$schema", "").startswith("https://json-schema.org/")
        assert schema.get("type") in {"object", "array"}
        assert "title" in schema


def test_claim_schema_names_gate_fields():
    props = _load("claim")["properties"]
    for field in ("claim_id", "claim_kind", "sentence", "number_tokens",
                  "entity_refs", "confidence", "causal_link"):
        assert field in props
    assert props["claim_kind"]["enum"] == ["measurement", "mechanism", "sizing"]
    assert props["confidence"]["enum"] == ["强", "中", "弱"]
    token = props["number_tokens"]["items"]["properties"]
    for field in ("token_id", "fact_id", "expected_metric_key", "direction"):
        assert field in token


def test_narrative_bundle_schema_names_gate_fields():
    props = _load("narrative_bundle")["properties"]
    for field in ("facts_hash", "headline", "first_screen", "spine_final",
                  "sections", "cannot_say"):
        assert field in props


def test_gate_report_schema_enumerates_status():
    props = _load("gate_report")["properties"]
    assert props["status"]["enum"] == ["PASS", "FAIL"]
    for field in ("hard_failures", "warnings", "capped_claims"):
        assert field in props


def test_fact_schema_matches_facts_json_fields():
    props = _load("fact")["properties"]
    for field in ("fact_id", "rendered", "metric_key", "direction", "pool_id",
                  "entity_type", "evidence_strength", "descriptive_reliability", "assumption"):
        assert field in props
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_orchestration_schemas.py -v`
Expected: FAIL — `orchestration/schemas` does not exist.

- [ ] **Step 3: Write the seven schema files**

Create `orchestration/schemas/fact.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "fact",
  "description": "L2 immutable fact — the only source of a number string. Mirrors facts.json entries.",
  "type": "object",
  "additionalProperties": false,
  "required": ["fact_id", "rendered", "metric_key", "unit"],
  "properties": {
    "fact_id": {"type": "string"},
    "value": {"type": ["number", "null"], "description": "Raw float for computation; NEVER rendered into prose."},
    "rendered": {"type": "string", "description": "Python-owned display string; the writer copies it verbatim."},
    "metric_key": {"type": "string"},
    "unit": {"type": "string"},
    "caliber": {"type": ["string", "null"]},
    "denominator": {"type": ["string", "null"]},
    "evidence_strength": {"enum": ["strong", "medium", "weak", "not_judgable"]},
    "descriptive_reliability": {"enum": ["high", "medium", "low", "not_applicable", null]},
    "entity_type": {"type": ["string", "null"]},
    "direction": {"enum": ["up", "down", "flat", null]},
    "pool_id": {"type": ["string", "null"]},
    "assumption": {"type": ["string", "null"]}
  }
}
```

Create `orchestration/schemas/spine_brief.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "spine_brief",
  "description": "Seed → writers+synthesizer. Accounting backbone (arithmetic identities) + broadcast set.",
  "type": "object",
  "additionalProperties": false,
  "required": ["decomposition_backbone", "headline_candidate", "section_callbacks", "broadcast_facts"],
  "properties": {
    "decomposition_backbone": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["link_id", "from", "to", "anchor_fact_ids", "relation"],
        "properties": {
          "link_id": {"type": "string"},
          "from": {"type": "string"},
          "to": {"type": "string"},
          "anchor_fact_ids": {"type": "array", "items": {"type": "string"}},
          "relation": {"enum": ["accounting_identity", "weak_causal_overlay"]}
        }
      }
    },
    "headline_candidate": {"type": "string", "description": "Opaque {tN} allowed; NO bare digits."},
    "section_callbacks": {
      "type": "object",
      "additionalProperties": {
        "type": "object",
        "additionalProperties": false,
        "properties": {
          "must_connect_to": {"type": "string"},
          "angle_hint": {"type": "string"}
        }
      }
    },
    "broadcast_facts": {"type": "array", "items": {"type": "string"}, "maxItems": 8}
  }
}
```

Create `orchestration/schemas/claim.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "claim",
  "description": "The atom. Sentence carries opaque {tN} tokens ONLY — no digits. Gate-validated.",
  "type": "object",
  "additionalProperties": false,
  "required": ["claim_id", "section_id", "claim_kind", "sentence", "number_tokens", "entity_refs", "confidence"],
  "properties": {
    "claim_id": {"type": "string"},
    "section_id": {"type": "string"},
    "claim_kind": {"enum": ["measurement", "mechanism", "sizing"]},
    "sentence": {"type": "string", "description": "Opaque {tN} placeholders; NO digits anywhere."},
    "number_tokens": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["token_id", "fact_id", "expected_metric_key"],
        "properties": {
          "token_id": {"type": "string", "pattern": "^t\\d+$"},
          "fact_id": {"type": "string"},
          "expected_metric_key": {"type": "string"},
          "direction": {"enum": ["up", "down", "flat", null]}
        }
      }
    },
    "entity_refs": {"type": "array", "items": {"type": "string"}, "description": "MUST ⊆ entity_registry."},
    "confidence": {"enum": ["强", "中", "弱"]},
    "causal_link": {
      "type": ["object", "null"],
      "additionalProperties": false,
      "required": ["from_entity_type", "to_entity_type", "quantified"],
      "properties": {
        "from_entity_type": {"type": "string"},
        "to_entity_type": {"type": "string"},
        "quantified": {"type": "boolean", "description": "true on an absent link → hard fail."}
      }
    },
    "next_test": {"type": ["string", "null"]},
    "spine_ref": {"type": ["string", "null"]}
  }
}
```

Create `orchestration/schemas/section_bundle.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "section_bundle",
  "description": "Writer → synthesizer. One report section's claims plus its spine alignment.",
  "type": "object",
  "additionalProperties": false,
  "required": ["section_id", "title", "claims", "spine_callbacks"],
  "properties": {
    "section_id": {"type": "string"},
    "title": {"type": "string"},
    "claims": {"type": "array", "items": {"$ref": "claim.json"}},
    "table_ref": {"type": ["string", "null"], "description": "Points at an L1/L2 artifact; never recomputed."},
    "chart_ref": {"type": ["string", "null"]},
    "spine_callbacks": {"type": "array", "items": {"type": "string"}},
    "spine_alignment": {"type": ["string", "null"]},
    "spine_dissent": {"type": ["string", "null"], "description": "Bottom-up honesty valve; may be null."}
  }
}
```

Create `orchestration/schemas/narrative_bundle.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "narrative_bundle",
  "description": "Synthesizer output — what the gate validates and freezes.",
  "type": "object",
  "additionalProperties": false,
  "required": ["facts_hash", "headline", "first_screen", "spine_final", "sections", "cannot_say"],
  "properties": {
    "facts_hash": {"type": "string"},
    "headline": {"type": "string", "description": "Opaque {tN} allowed; NO bare digits."},
    "first_screen": {
      "type": "object",
      "additionalProperties": false,
      "required": ["spine", "panel", "actions"],
      "properties": {
        "spine": {"type": "array", "items": {"$ref": "claim.json"}},
        "panel": {"type": "array", "items": {"$ref": "claim.json"}},
        "actions": {"type": "array", "items": {"type": "string"}}
      }
    },
    "spine_final": {
      "type": "object",
      "additionalProperties": false,
      "required": ["backbone"],
      "properties": {
        "backbone": {"type": "array", "items": {
          "type": "object",
          "additionalProperties": false,
          "required": ["link_id", "from", "to", "anchor_fact_ids", "relation"],
          "properties": {
            "link_id": {"type": "string"},
            "from": {"type": "string"},
            "to": {"type": "string"},
            "anchor_fact_ids": {"type": "array", "items": {"type": "string"}},
            "relation": {"enum": ["accounting_identity", "weak_causal_overlay"]}
          }
        }}
      }
    },
    "sections": {"type": "array", "items": {"$ref": "section_bundle.json"}},
    "cannot_say": {"type": "array", "items": {"type": "string"}}
  }
}
```

Create `orchestration/schemas/gate_report.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "gate_report",
  "description": "factcheck_gate output. HARD blocks render; WARN annotates; capped logs confidence caps.",
  "type": "object",
  "additionalProperties": false,
  "required": ["status", "hard_failures", "warnings", "capped_claims"],
  "properties": {
    "status": {"enum": ["PASS", "FAIL"]},
    "hard_failures": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
    "warnings": {"type": "array", "items": {"$ref": "#/$defs/finding"}},
    "capped_claims": {
      "type": "array",
      "items": {
        "type": "object",
        "additionalProperties": false,
        "required": ["claim_id", "from", "to"],
        "properties": {
          "claim_id": {"type": ["string", "null"]},
          "from": {"enum": ["强", "中", "弱"]},
          "to": {"enum": ["强", "中", "弱"]}
        }
      }
    }
  },
  "$defs": {
    "finding": {
      "type": "object",
      "additionalProperties": false,
      "required": ["code", "detail"],
      "properties": {
        "code": {"type": "string"},
        "claim_id": {"type": ["string", "null"]},
        "detail": {"type": "string"}
      }
    }
  }
}
```

Create `orchestration/schemas/continuity_edit.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "continuity_edit",
  "description": "Continuity pass output — prose-only edits. digit + {tN} multisets are invariant.",
  "type": "array",
  "items": {
    "type": "object",
    "additionalProperties": false,
    "required": ["claim_id", "old", "new"],
    "properties": {
      "claim_id": {"type": "string"},
      "old": {"type": "string", "description": "Verbatim substring of the claim's rendered_sentence, occurs once."},
      "new": {"type": "string", "description": "Same digits, same {tN}; prose only."}
    }
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_orchestration_schemas.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add orchestration/schemas/ tests/test_orchestration_schemas.py
git commit -m "feat(orchestration): host-neutral handoff JSON schemas (7 atoms)"
```

---

### Task 3: DAG doc + per-role prompts (`orchestration/dag.md`, `prompts/*.md`)

**Files:**
- Create: `orchestration/dag.md`, `orchestration/prompts/seed.md`, `writer.md`, `synthesizer.md`,
  `continuity.md`, `patch.md`
- Test: `tests/test_orchestration_prompts.py`

**Interfaces:**
- Produces: the model-agnostic source of truth every host reads to run the L3 DAG. `dag.md` describes
  the Seed→Fan→Confirm→Gate→Continuity stages with tiers as `judgment/high`·`draft/medium` (NO model
  ids). Each prompt states the role's inputs, the schema it emits, and the writing constitution rules
  it must honor. The test asserts the roster is present and that no prompt hard-codes a model id and
  every prompt references its output schema.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestration_prompts.py
from pathlib import Path

ORCH = Path(__file__).resolve().parents[1] / "orchestration"
PROMPTS = ORCH / "prompts"
ROLES = {"seed", "writer", "synthesizer", "continuity", "patch"}
# Anthropic/OpenAI model ids that must never appear in a host-neutral asset.
BANNED_MODEL_TOKENS = ("claude-", "gpt-", "o1-", "o3-", "sonnet-", "opus-", "haiku-")


def test_dag_and_prompts_present():
    assert (ORCH / "dag.md").is_file()
    assert {p.stem for p in PROMPTS.glob("*.md")} == ROLES


def test_dag_uses_role_tiers_not_model_ids():
    text = (ORCH / "dag.md").read_text(encoding="utf-8")
    assert "judgment/high" in text
    assert "draft/medium" in text
    lower = text.lower()
    for token in BANNED_MODEL_TOKENS:
        assert token not in lower, f"dag.md hard-codes a model id: {token}"


def test_no_prompt_hardcodes_a_model_id():
    for role in ROLES:
        lower = (PROMPTS / f"{role}.md").read_text(encoding="utf-8").lower()
        for token in BANNED_MODEL_TOKENS:
            assert token not in lower, f"{role}.md hard-codes a model id: {token}"


def test_each_prompt_names_its_output_schema():
    expected = {
        "seed": "spine_brief",
        "writer": "section_bundle",
        "synthesizer": "narrative_bundle",
        "continuity": "continuity_edit",
        "patch": "claim",
    }
    for role, schema in expected.items():
        text = (PROMPTS / f"{role}.md").read_text(encoding="utf-8")
        assert schema in text, f"{role}.md does not reference its schema {schema}"


def test_writer_prompt_forbids_digits_in_sentences():
    text = (PROMPTS / "writer.md").read_text(encoding="utf-8")
    assert "{tN}" in text or "{t0}" in text
    assert "数字" in text  # must instruct: no digits, tokens only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_orchestration_prompts.py -v`
Expected: FAIL — `orchestration/dag.md` / prompts missing.

- [ ] **Step 3: Write the DAG doc and five prompts**

Create `orchestration/dag.md`:

```markdown
# L3 orchestration DAG (host-neutral)

This is the source of truth for the merchant-narrative writer. Any host that can spawn sub-agents
runs this same DAG; a host without sub-agents runs the stages as sequential in-session role-passes.
The deterministic Python layer (`xhs-ca facts / gate / render-draft / finalize / render-frozen /
skeleton`) brackets the agents and is identical on every host.

## Model policy — role tier + reasoning effort, NEVER a model id

- **judgment / high** — the strongest model the host exposes, high reasoning effort.
- **draft / medium** — the host's standard model, medium reasoning effort.

Each host maps a tier to its own model at dispatch. `narrative_schema_version` hashes the
prompts + schemas + tiers (not model ids), so the same contract is one cache key across hosts.

## Stages

| Stage | Role | Agents | Tier / effort | Consumes | Emits (schema) |
|---|---|---|---|---|---|
| Seed | 主线假设器 | 1 | judgment / high | facts.json 数字与结构 only (never module prose) | `spine_brief` |
| Fan | 域写手 | ≤6 (parallel) | draft / medium | 本域 domain_slice ∪ broadcast_facts ∪ 本域 callback | `section_bundle` |
| Confirm | 综合器 | 1 | judgment / high | 全部 section_bundle + spine_brief + dissents + blocked_modules | `narrative_bundle` |
| Gate | factcheck_gate.py | 0 (Python) | — | narrative_bundle + facts + registries/ledgers | `gate_report` |
| Patch | 定向补丁 | 0–2 | draft / medium | gate_report.hard_failures + 出错 claim + 该 fact 的 rendered | fixed `claim` spliced back |
| Continuity | 全篇连读 | 1 | judgment / high | render-draft 之后已填数字的成稿 | `continuity_edit[]` |

## Flow

1. `xhs-ca facts auto` → facts.json → cache-check `(facts_hash, narrative_schema_version,
   renderer_version)`. HIT → `xhs-ca render-frozen` (0 agents). MISS → run the DAG.
2. **Seed** emits `spine_brief`. Spine-sanity precheck (Python, before the fan): every backbone
   anchor fact-grounded and all four pillars (大盘/退款/流量内容/商品或用户) present; 1 retry else degrade.
3. **Fan** — ≤6 writers in parallel, one per producible domain; each sees only its slice ∪
   `broadcast_facts` (read-only spine fact_ids). A writer whose observed direction exceeds its
   assigned node reports `spine_dissent`.
4. **Confirm** assembles `narrative_bundle`. If a spine link changed materially, re-dispatch only the
   affected writers with a revised `angle_hint` (≤3 writers, ≤1 round).
5. **Gate** — `xhs-ca gate narrative_bundle.json facts.json`. HARD-FAIL → ≤2 targeted patch rounds
   routed to the owning node. Confidence is capped deterministically (never an agent). WARN never
   triggers a rewrite.
6. `xhs-ca render-draft` fills every `{tN}` from `fact.rendered`. **Continuity** reads the filled
   9-section draft and emits prose-only `continuity_edit[]` (digit + `{tN}` multisets invariant).
7. `xhs-ca finalize` applies the edits, re-gates, and freezes `frozen_narrative` beside
   `mapping_overrides.yaml`. `xhs-ca render-frozen` writes md+html (re-gates at render time).
8. **Exhaustion** (gate ≤2 rounds fail / spine precheck fails twice / agent layer unavailable) →
   `xhs-ca skeleton` — deterministic 0-agent floor (facts + real-name tables + charts + 强/中/弱 tags
   + CANNOT-SAY), banner「本报告为确定性骨架版」. Every run appends a record to `report_runs.jsonl`.

## Bounds

~9 base agents per fresh report (1 Seed + ≤6 writers + 1 Synthesizer + 1 Continuity), ~10–11 with one
patch/re-dispatch, ~14–16 worst-case. Cache-hit re-runs = 0 agents. Not mid-DAG resumable; the only
persistent checkpoint is the post-gate freeze.
```

Create `orchestration/prompts/seed.md`:

```markdown
# Seed — 主线假设器 (tier: judgment / high)

You receive `facts.json` — **numbers and structure only**. Never read module prose. Build the
report's accounting backbone: the arithmetic identities that hold the report together (the LMDI GMV
bridge, per-visitor-GMV = f(UV, 客单价, 转化), 客单价 as a ratio, refund sums). These are
`relation: accounting_identity`. Causal arrows (退款→客单价, 内容→流量) ride on top as
`relation: weak_causal_overlay` and will be Python-capped at 弱 downstream — never put them in the
load-bearing backbone.

Emit a **`spine_brief`** (see `schemas/spine_brief.json`):
- `decomposition_backbone[]` — each link fact-grounded by `anchor_fact_ids` that exist in facts.json.
- `headline_candidate` — one sentence, opaque `{tN}` only, NO digits.
- `section_callbacks{domain: {must_connect_to, angle_hint}}` — how each domain connects to the spine.
- `broadcast_facts[~6]` — the shared spine `fact_id`s every writer may cite.

Single caliber iron law: efficiency/per-visitor ¥ use `product_visitors` only, reconciled to 4.6%
conversion; `total_visitors` is barred from efficiency math.
```

Create `orchestration/prompts/writer.md`:

```markdown
# Fan writer — 域写手 (tier: draft / medium)

You write ONE report section. You see your `domain_slice` (its facts + module_reading) ∪
`broadcast_facts` (read-only spine fact_ids) ∪ your section's callback. You may cite a broadcast fact
to connect to the spine; you may NOT cite any non-broadcast fact outside your slice.

Emit a **`section_bundle`** (see `schemas/section_bundle.json`) of `claim` objects. Hard rules:
- **Sentences carry opaque `{tN}` tokens ONLY — never a digit.** Every magnitude is a
  `number_token {token_id, fact_id, expected_metric_key, direction}`; Python fills `{tN}` from
  `fact.rendered` at render time. A digit in a sentence is unrepresentable and will hard-fail the gate.
- **先钱后机制** — open on ¥ and direction, not on a metric definition.
- **大胆下判断 + 置信标签** — end on a decisive conclusion (including causal), tagged 强/中/弱. Weakness
  is a tag, never a reason to omit the call.
- **相关性硬约束** — content/note claims may give a directional judgment (tagged 弱) but NEVER a
  quantified attribution presented as fact; set `causal_link.quantified=false` for such claims.
- **真名不哈希** — use real entity names (兴安岭之夜/鱼盘); they must be in `entity_registry`.
- Report `spine_dissent` if your slice's observed direction exceeds your assigned spine node.
```

Create `orchestration/prompts/synthesizer.md`:

```markdown
# Confirm — 综合器 (tier: judgment / high)

You receive every `section_bundle`, the `spine_brief`, all `spine_dissent`s, and `blocked_modules`.
Assemble the **`narrative_bundle`** (see `schemas/narrative_bundle.json`):
- `spine_final.backbone` — the reconciled accounting backbone.
- `first_screen` — 因果主线 / 盘面 / 本周重点. **篇幅内容驱动,不硬凑不硬删**: the 主线 is 1–2 sentences
  (one more if genuinely needed), 盘面 lists only 够格 conclusions, 本周重点 only truly-qualified actions.
  It is an引子 that pulls the reader into the full analysis, not a 90-second card to close on.
- `sections` — ordered business-first; each keeps its `spine_callbacks` connected to a real backbone
  `link_id`.
- `cannot_say` — the CANNOT-SAY list (笔记→订单归因 is permanently unanswerable; 退款原因/时点, 人群,
  投放, SKU日销, 内容特征, 评论 are unlock-on-data).

If a spine link changed materially versus a writer's assumption, re-dispatch only the affected writers
with a revised `angle_hint` (≤3 writers, ≤1 round) rather than bolting on a callback. Never invent a
number or an entity; every magnitude stays a `{tN}` token bound to a real fact.
```

Create `orchestration/prompts/continuity.md`:

```markdown
# Continuity — 全篇连读+统一嗓音 (tier: judgment / high)

You read the **already-filled** nine-section draft (numbers are in place) end to end and unify voice,
flow, and emphasis so it reads as ONE story, not nine stitched panels. Emit **`continuity_edit[]`**
(see `schemas/continuity_edit.json`): each `{claim_id, old, new}` rewrites prose ONLY.

Mechanical contract (enforced by Python `finalize`; a violation drops the edit):
- `old` must be a verbatim substring of that claim's rendered sentence and occur exactly once.
- `new` must contain the **same digit multiset** and the **same `{tN}` multiset** as `old` — you may
  reword around numbers, never change, add, or remove one.
- Never change a conclusion's direction, a confidence tag, or a caliber footnote.
- Never strip emoji — it is real merchant content.
Only emit an edit where it genuinely reads better; 宁缺毋滥.
```

Create `orchestration/prompts/patch.md`:

```markdown
# Patch — 定向补丁 (tier: draft / medium)

You fix ONE gate hard-failure. You receive the failing `claim`, the `gate_report` entry, and the
copy-paste `rendered` string of the fact it should cite. Return the corrected **`claim`** (see
`schemas/claim.json`), spliced back for re-gating.

Fix the structure, not by inventing data:
- MISSING_FACT / METRIC_MISBIND / DIRECTION_CONFLICT — point the `number_token` at the correct
  existing `fact_id` / `expected_metric_key` / `direction`, or drop the token and the clause it backs.
- INVENTED_ENTITY — remove or replace with a name in `entity_registry`.
- NONEXISTENT_SLICE — delete the claim; the slice does not exist (it belongs in CANNOT-SAY / §7).
- QUANTIFIED_ATTRIBUTION — set `causal_link.quantified=false` and restate as a directional 弱 judgment,
  or remove the attributed number.
- SUMMED_POOLS — split into per-pool claims; never sum incompatible pools.
- MAGNITUDE_UNBOUND — replace any bare digit with a `{tN}` token bound to a real fact.
Never raise the confidence tag to escape a cap; the cap is deterministic and re-applied.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_orchestration_prompts.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add orchestration/dag.md orchestration/prompts/ tests/test_orchestration_prompts.py
git commit -m "feat(orchestration): host-neutral DAG doc + per-role prompts (tier, not model id)"
```

---

### Task 4: Claude-Code accelerator (`report_writer_workflow.js`)

**Files:**
- Create: `.xhs-ceramics-analytics/report_writer_workflow.js`
- Test: `tests/test_report_writer_workflow.py`

**Interfaces:**
- Produces: an optional Claude-Code Workflow script mirroring `merchant_voice_workflow.js`'s API
  (`pipeline`/`parallel`/`agent`/`log`), shaped as `seed → parallel(≤6 writers) → synthesizer`. Each
  agent prompt instructs the sub-agent to **Read the neutral `orchestration/prompts/<role>.md`** (the
  source of truth) and follow it — the `.js` is an accelerator, not a second copy of the contract. The
  structured-output schemas are embedded as JS objects (the Workflow API needs a JS schema at
  `agent({schema})`; there is no filesystem read at script runtime), with a comment pointing to the
  canonical `orchestration/schemas/*.json`. The test asserts the file exists, exports a `meta`, drives
  the seed→writers→synthesizer pipeline, references the neutral prompts, and hard-codes no model id.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report_writer_workflow.py
from pathlib import Path

JS = Path(__file__).resolve().parents[1] / ".xhs-ceramics-analytics" / "report_writer_workflow.js"
BANNED_MODEL_TOKENS = ("claude-", "gpt-", "o1-", "o3-", "sonnet-", "opus-", "haiku-")


def test_workflow_file_exists():
    assert JS.is_file()


def test_exports_meta_and_drives_pipeline():
    text = JS.read_text(encoding="utf-8")
    assert "export const meta" in text
    assert "report-writer" in text
    assert "pipeline(" in text
    assert "parallel(" in text
    assert "agent(" in text


def test_reads_neutral_prompts_not_a_second_contract():
    text = JS.read_text(encoding="utf-8")
    assert "orchestration/prompts/seed.md" in text
    assert "orchestration/prompts/writer.md" in text
    assert "orchestration/prompts/synthesizer.md" in text


def test_uses_effort_tiers_not_model_ids():
    text = JS.read_text(encoding="utf-8")
    assert "effort" in text
    lower = text.lower()
    for token in BANNED_MODEL_TOKENS:
        assert token not in lower, f"workflow hard-codes a model id: {token}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_report_writer_workflow.py -v`
Expected: FAIL — file missing.

- [ ] **Step 3: Write the workflow script**

Create `.xhs-ceramics-analytics/report_writer_workflow.js`:

```javascript
export const meta = {
  name: 'report-writer',
  description: 'Claude-Code accelerator for the L3 merchant-narrative DAG: seed → ≤6 domain writers → synthesizer. Reads the neutral orchestration/ contract; deterministic gate/render run as xhs-ca subcommands outside this script.',
  phases: [
    { title: 'Seed', detail: '主线假设器：facts.json 数字与结构 → spine_brief' },
    { title: 'Fan', detail: '≤6 域写手并行 → section_bundle' },
    { title: 'Confirm', detail: '综合器 → narrative_bundle' },
  ],
}

// The SOURCE OF TRUTH for every role's instructions is orchestration/prompts/<role>.md and the
// handoff shapes are orchestration/schemas/*.json. This script is an OPTIONAL accelerator: each agent
// is told to Read the neutral prompt file and follow it, so the contract lives in one place. Model
// choice is role tier + reasoning effort only — never a model id — so the same DAG runs on any host.
//
// `args` is { facts_path, domains: [{section_id, slice_note}], seed_note? } supplied by the caller.

const FACTS = (args && args.facts_path) || '.xhs-ceramics-analytics/outputs/facts.json'
const DOMAINS = ((args && args.domains) || []).slice(0, 6) // Fan is capped at 6 writers.

// Embedded structured-output schemas. Canonical copies live in orchestration/schemas/*.json; kept
// minimal here because the Workflow API needs a JS object at agent({schema}) and cannot read a file
// at script runtime. The gate (xhs-ca gate) is the real validator; these just shape agent output.
const SPINE_BRIEF_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['decomposition_backbone', 'headline_candidate', 'broadcast_facts'],
  properties: {
    decomposition_backbone: { type: 'array', items: { type: 'object' } },
    headline_candidate: { type: 'string' },
    section_callbacks: { type: 'object' },
    broadcast_facts: { type: 'array', items: { type: 'string' } },
  },
}
const SECTION_BUNDLE_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['section_id', 'title', 'claims'],
  properties: {
    section_id: { type: 'string' },
    title: { type: 'string' },
    claims: { type: 'array', items: { type: 'object' } },
    spine_callbacks: { type: 'array', items: { type: 'string' } },
    spine_dissent: { type: ['string', 'null'] },
  },
}
const NARRATIVE_BUNDLE_SCHEMA = {
  type: 'object', additionalProperties: true,
  required: ['facts_hash', 'headline', 'first_screen', 'spine_final', 'sections', 'cannot_say'],
  properties: {
    facts_hash: { type: 'string' },
    headline: { type: 'string' },
    first_screen: { type: 'object' },
    spine_final: { type: 'object' },
    sections: { type: 'array', items: { type: 'object' } },
    cannot_say: { type: 'array', items: { type: 'string' } },
  },
}

function seedPrompt() {
  return `Read orchestration/prompts/seed.md and follow it exactly (tier: judgment/high).
Read the facts file at ${FACTS} — numbers and structure ONLY, never module prose.
Emit a spine_brief per orchestration/schemas/spine_brief.json. ${(args && args.seed_note) || ''}`
}

function writerPrompt(domain) {
  return `Read orchestration/prompts/writer.md and follow it exactly (tier: draft/medium).
You write ONLY the "${domain.section_id}" section. Read ${FACTS} for your domain slice and the
broadcast spine facts. ${domain.slice_note || ''}
Sentences carry opaque {tN} tokens ONLY — never a digit. Emit a section_bundle per
orchestration/schemas/section_bundle.json.`
}

function synthesizerPrompt(spine, sections) {
  return `Read orchestration/prompts/synthesizer.md and follow it exactly (tier: judgment/high).
spine_brief:
${JSON.stringify(spine, null, 1)}
section_bundles:
${JSON.stringify(sections, null, 1)}
Assemble one narrative_bundle per orchestration/schemas/narrative_bundle.json. 首屏篇幅内容驱动，
不硬凑不硬删。Never invent a number or entity; every magnitude stays a {tN} token.`
}

const spine = await agent(seedPrompt(), {
  label: 'seed', phase: 'Seed', effort: 'high', schema: SPINE_BRIEF_SCHEMA,
})

const sections = (await parallel(
  DOMAINS.map((d) => () =>
    agent(writerPrompt(d), {
      label: `writer:${d.section_id}`, phase: 'Fan', effort: 'medium', schema: SECTION_BUNDLE_SCHEMA,
    })
  )
)).filter(Boolean)

const narrative = await agent(synthesizerPrompt(spine, sections), {
  label: 'synthesizer', phase: 'Confirm', effort: 'high', schema: NARRATIVE_BUNDLE_SCHEMA,
})

log(`report-writer: seed + ${sections.length} writers → narrative_bundle assembled. ` +
    `Next (outside this script): xhs-ca gate → render-draft → Continuity → finalize → render-frozen.`)
return { spine, sections, narrative }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_report_writer_workflow.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add .xhs-ceramics-analytics/report_writer_workflow.js tests/test_report_writer_workflow.py
git commit -m "feat(orchestration): optional Claude-Code report-writer accelerator (reads neutral contract)"
```

---

### Task 5: `run` emits facts.json + telemetry on render/skeleton (`cli.py`)

**Files:**
- Modify: `xhs_ceramics_analytics/cli.py` (the `run`, `render-frozen`, `skeleton` commands)
- Test: `tests/test_cli_run_facts_telemetry.py`

**Interfaces:**
- Consumes: `report_telemetry.build_run_record`/`append_run_record` (T1), `facts_export.build_factbook`/
  `factbook_to_json`/`facts_hash` (Plan 1), `frozen_narrative.is_cache_hit` (Plan 2).
- Produces: `run` writes `facts.json` beside the report (the cache key that makes step 7b reachable);
  `render-frozen` appends a `frozen` telemetry record (cache_hit reflects the frozen match);
  `skeleton` appends a `skeleton` record with `degradation_reason`. Telemetry is best-effort — a
  telemetry failure never breaks the report.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_run_facts_telemetry.py
import json
from pathlib import Path

from typer.testing import CliRunner

from xhs_ceramics_analytics.cli import app
from xhs_ceramics_analytics.db.build import build_database

runner = CliRunner()


def _build_db(tmp_path: Path, fixture_dir: Path) -> None:
    state = tmp_path / ".xhs-ceramics-analytics"
    state.mkdir(parents=True, exist_ok=True)
    build_database(
        db_path=state / "analytics.duckdb",
        files=[fixture_dir / "business_overview_daily.csv", fixture_dir / "traffic_source.csv"],
    )


def test_run_emits_facts_json_beside_report(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = runner.invoke(app, ["run", "core_business_diagnosis", "--project-root", str(tmp_path),
                                 "--name", "诊断"])
    assert result.exit_code == 0, result.output
    outputs = tmp_path / ".xhs-ceramics-analytics" / "outputs"
    assert (outputs / "诊断.md").exists()
    facts = outputs / "facts.json"
    assert facts.exists()
    data = json.loads(facts.read_text(encoding="utf-8"))
    assert len(data["facts_hash"]) == 64


def test_skeleton_appends_telemetry_record(tmp_path, fixture_dir):
    _build_db(tmp_path, fixture_dir)
    result = runner.invoke(app, ["skeleton", "core_business_diagnosis",
                                 "--project-root", str(tmp_path), "--name", "骨架"])
    assert result.exit_code == 0, result.output
    runs = tmp_path / ".xhs-ceramics-analytics" / "report_runs.jsonl"
    assert runs.exists()
    record = json.loads(runs.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert record["mode"] == "skeleton"
    assert record["degradation_reason"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_run_facts_telemetry.py -v`
Expected: FAIL — `run` writes no facts.json; `skeleton` writes no telemetry.

- [ ] **Step 3: Modify `cli.py`**

In `run()`, immediately after the markdown write (`markdown_out.write_text(...)` /
`typer.echo(f"Wrote report: {markdown_out}")`), add facts.json emission using the same `results` and
the blocked set. Insert:

```python
    from xhs_ceramics_analytics.analysis.registry import TASKS as _ALL_TASKS
    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook as _build_factbook,
        factbook_to_json as _factbook_to_json,
    )

    blocked = tuple(t for t in _ALL_TASKS if t not in task_ids)
    facts_out = output_dir / "facts.json"
    facts_out.write_text(
        _factbook_to_json(_build_factbook(results, blocked_modules=blocked)), encoding="utf-8"
    )
    typer.echo(f"Wrote facts: {facts_out}")
```

> Note: `TASKS` / `run_task` are already imported at the top of `run()`; the aliased re-import above
> keeps the insertion self-contained and avoids reordering existing imports. If `TASKS` is already in
> scope at the insertion point, use it directly instead of the alias.

In `skeleton()` (from Plan 2), after writing the md+html, append a telemetry record:

```python
    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook as _build_factbook,
        facts_hash as _facts_hash,
    )
    from xhs_ceramics_analytics.reporting.report_telemetry import (
        append_run_record,
        build_run_record,
    )

    book = _build_factbook(results, blocked_modules=tuple(t for t in TASKS if t not in task_ids))
    record = build_run_record(
        mode="skeleton", facts_hash=_facts_hash(book), cache_hit=False,
        degradation_reason="skeleton_cli",
    )
    append_run_record(state_dir(project_root) / "report_runs.jsonl", record)
```

In `render_frozen_command()` (from Plan 2), after writing the md+html, append a `frozen` record:

```python
    from xhs_ceramics_analytics.reporting.report_telemetry import (
        append_run_record,
        build_run_record,
    )

    record = build_run_record(
        mode="frozen", facts_hash=facts_data.get("facts_hash", ""), cache_hit=True,
    )
    append_run_record(outputs_dir(None).parent / "report_runs.jsonl", record)
```

> `render-frozen` takes no `--project-root`; `outputs_dir(None).parent` is the state dir root for the
> default project. Keep the telemetry write in a `try/except Exception: pass` so a telemetry error
> never breaks the delivered report.

Wrap each telemetry `append_run_record` call in:

```python
    try:
        append_run_record(...)
    except Exception:
        pass  # telemetry is best-effort; never break the report
```

- [ ] **Step 4: Run the new test + the Plan 2 CLI tests to verify green**

Run: `.venv/bin/python -m pytest tests/test_cli_run_facts_telemetry.py tests/test_cli_narrative.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add xhs_ceramics_analytics/cli.py tests/test_cli_run_facts_telemetry.py
git commit -m "feat(cli): run emits facts.json; render-frozen/skeleton append run telemetry"
```

---

### Task 6: Skill wiring — mirror `orchestration/` + SKILL.md step 7b

**Files:**
- Modify: `skills/data-analyze-for-zcl/scripts/sync-runtime` (add `orchestration/` to the rsync + banner set)
- Modify: `skills/data-analyze-for-zcl/SKILL.md` (insert step 7b)
- Test: `tests/test_skill_wiring.py`

**Interfaces:**
- Produces: `scripts/sync-runtime` mirrors the repo-root `orchestration/` tree into
  `assets/xhs-ca/orchestration/`; SKILL.md gains a host-neutral「7b. Compose merchant narrative」step
  between step 7 and step 8. The test asserts both wirings are present in the source files.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skill_wiring.py
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "skills" / "data-analyze-for-zcl" / "scripts" / "sync-runtime"
SKILL = ROOT / "skills" / "data-analyze-for-zcl" / "SKILL.md"


def test_sync_runtime_mirrors_orchestration():
    text = SYNC.read_text(encoding="utf-8")
    assert "$repo_root/orchestration" in text
    assert "$runtime_dir/orchestration" in text  # bannered too


def test_skill_has_step_7b_host_neutral():
    text = SKILL.read_text(encoding="utf-8")
    assert "7b" in text
    assert "orchestration/dag.md" in text
    # host-neutral: names the three host paths, no hard model binding
    assert "Codex" in text
    assert "skeleton" in text


def test_skill_step_7b_precedes_step_8():
    text = SKILL.read_text(encoding="utf-8")
    assert text.index("7b") < text.index("8. **Custom integrated reports**")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_wiring.py -v`
Expected: FAIL — no `orchestration` in sync-runtime, no step 7b.

- [ ] **Step 3a: Add `orchestration/` to `scripts/sync-runtime`**

In the rsync source list (currently `pyproject.toml`, `xhs_ceramics_analytics`, `references`,
`task_templates`, `tests`), add the orchestration tree:

```bash
rsync -a --delete \
  "$repo_root/pyproject.toml" \
  "$repo_root/xhs_ceramics_analytics" \
  "$repo_root/orchestration" \
  "$repo_root/references" \
  "$repo_root/task_templates" \
  "$repo_root/tests" \
  "$runtime_dir/"
```

And add the mirrored orchestration dir to `banner_dirs` so its `.md` files get the DO-NOT-EDIT banner
(the `.json` schemas are untouched — the banner loop only targets `*.md` and `__init__.py`):

```bash
banner_dirs=(
  "$runtime_dir/references"
  "$runtime_dir/task_templates"
  "$runtime_dir/orchestration"
  "$runtime_dir/xhs_ceramics_analytics"
)
```

- [ ] **Step 3b: Insert step 7b into `SKILL.md`**

Between step 7 (line ending `…report structure.`) and step 8 (`8. **Custom integrated reports**`),
insert:

```markdown
7b. **(可选) 商家叙事编排 — Compose merchant narrative** — step 7 已 0-agent 产出确定性报告与
`facts.json`。若要把它升级为「读物级」商家叙事,按 `assets/xhs-ca/orchestration/dag.md` 跑 L3 多 agent
写手管线(host 中立):先用 `facts.json` 做缓存校验 `(facts_hash, narrative_schema_version,
renderer_version)`——命中即 `xhs-ca render-frozen`(0 agent)。未命中则**用你所在 host 的 subagent
机制** fan out 同一份 DAG(**Claude Code**: 可选 `.xhs-ceramics-analytics/report_writer_workflow.js`
或 Task 工具;**Codex**: 其自带 subagent;**无 subagent 的 host**: 顺序 in-session role-pass),读取
`orchestration/prompts/*.md` 与 `schemas/*.json` 作为唯一契约 → `xhs-ca gate` → 硬失败时 0–2 个定向
补丁 agent → `xhs-ca render-draft` → 一个 Continuity agent 全篇连读 → `xhs-ca finalize`。任一环节耗尽
预算 → `xhs-ca skeleton` 确定性骨架兜底。模型选择一律「判断层/起草层 + reasoning effort」,不绑定任何
模型 id。每次运行都会向 `.xhs-ceramics-analytics/report_runs.jsonl` 追加一条计数记录(降级率/命中/骨架
兜底/硬失败计数),在 step 9 交付说明里如实汇报,避免骨架成为静默默认值。仍然是**恰好两份产物**。
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_skill_wiring.py -v`
Expected: PASS (3 tests). Also `bash -n skills/data-analyze-for-zcl/scripts/sync-runtime` — no syntax error.

- [ ] **Step 5: Commit**

```bash
git add skills/data-analyze-for-zcl/scripts/sync-runtime skills/data-analyze-for-zcl/SKILL.md \
        tests/test_skill_wiring.py
git commit -m "feat(skill): mirror orchestration/ + SKILL.md step 7b (host-neutral narrative)"
```

---

### Post-code steps (spec §Global constraints — run once after all tasks green)

- [ ] **Full suite + ruff**

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check xhs_ceramics_analytics/ tests/
```

Expected: all green (Plan 1+2+3 tests), ruff clean.

- [ ] **Sync the skill mirror**

```bash
skills/data-analyze-for-zcl/scripts/sync-runtime
```

Verify `skills/data-analyze-for-zcl/assets/xhs-ca/orchestration/{dag.md,schemas,prompts}` now exist
and the mirrored `.md` files carry the DO-NOT-EDIT banner (schemas `.json` unbannered).

- [ ] **Regen the real-data demo + verify exactly two artifacts**

Locate the real 千帆 export (per memory: WeChat cache, copy OUT to /tmp — never write inside the
cache), build into a temp project root, then:

```bash
.venv/bin/xhs-ca run auto --name 千帆经营诊断报告 --project-root /tmp/xhs-demo
ls /tmp/xhs-demo/.xhs-ceramics-analytics/outputs/
```

Confirm exactly `千帆经营诊断报告.md` + `千帆经营诊断报告.html` (+ `facts.json` as the new cache-key
side-output; that is expected, not a stray per-slug artifact). No stray per-slug
`data_quality_check.md/.html`. If HTML render fails, keep the md and report the error path.

- [ ] **Commit the regenerated mirror** (if `sync-runtime` changed mirrored bytes)

```bash
git add skills/data-analyze-for-zcl/assets/xhs-ca/
git commit -m "chore(skill): sync runtime mirror — orchestration assets + Plan 3 code"
```

---

## Self-review

**Spec coverage (Plan-3 slice of §New/modified files + §Harness portability + §Error handling):**
- Host-neutral `orchestration/` contract — `dag.md` (tier not model id), `schemas/*.json` (7 atoms
  matching the Plan-2 gate/render shapes), `prompts/*.md` (5 roles) → T2, T3. Portability asserted by
  the "no model id" tests.
- Optional Claude-Code accelerator `report_writer_workflow.js` that *reads* the neutral prompts → T4.
- `run auto` also emits facts.json (spec §New/modified `cli.py`) → T5.
- Telemetry `report_runs.jsonl` + step-9 surfacing (spec §Error handling "Telemetry, not silent
  skeleton") → T1 + T5 wiring + T6 SKILL.md step-7b mention.
- SKILL.md step 7b, host-neutral (spec §Skill-runtime wiring) → T6.
- Mirror via `scripts/sync-runtime` (spec: assets auto-mirror) → T6 + post-code sync.
- Post-code: sync mirror, regen demo, verify two artifacts (spec §Global constraints last line) →
  Post-code steps.

**Deferred / explicitly out of scope (not gaps):** live wiring of the agent DAG into `run auto`
(spec: "SKILL.md's `run auto` is pure Python / 0 agents today" — the DAG is host-driven per step 7b,
not auto-invoked); building blocked modules; cross-period bet tracking. `mid-DAG resume` is
non-goal per spec (§Error handling "Not mid-DAG resumable").

**Placeholder scan:** none — every schema, prompt, JS block, cli insertion, and bash edit is complete
literal content.

**Type consistency:** schema field names (`claim_kind` enum, `confidence` 强/中/弱, `number_tokens`
item fields, `narrative_bundle` keys, `gate_report.status`) match `factcheck_gate`/`narrative_render`
exactly (Plan 2). `build_run_record` kwargs match the T5 call sites. `build_factbook(results, *,
blocked_modules=...)` / `factbook_to_json` / `facts_hash` signatures match Plan 1. `TASKS`/`run_task`/
`outputs_dir`/`state_dir` usages match the existing `cli.py`.

**Execution order (parallel-safe):** T1, T2, T3, T6 touch distinct files → parallelizable; T4 reads
T2/T3 assets (its test checks their referenced paths as strings, so it can run alongside but is
ordered after for clarity); T5 edits the shared `cli.py` and imports T1 → runs last. Each task ends
green + committed. Post-code steps run once at the end.
