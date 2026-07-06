"""Passive, file-based narrative-workflow controller (host-neutral).

The controller prepares durable briefs and state and ingests sub-agent JSON,
but never spawns sub-agents. The host agent drives it (see runbook.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
from xhs_ceramics_analytics.reporting.narrative_render import (
    apply_continuity_edits,
    render_draft,
)

MAX_FAN_AGENTS = 6
MAX_GATE_ROUNDS = 2

_STATE_FILE = "state.json"
_SLUG_STRIP = re.compile(r"[^\w一-鿿]+")
_TERMINAL_STAGES = {"finalized", "blocked"}

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
        "_section_order": [_slug(s["title"]) for s in capped],
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


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_EXPECTED_STATUS = {
    "seed": {"seed"},
    "fan": {"fan"},
    "synth": {"synth"},
    "patch": {"patch"},
    "continuity": {"continuity"},
}


def _scan_balanced(text: str):
    """Return the earliest balanced {...}/[...] substring that parses as JSON."""
    pairs = {"{": "}", "[": "]"}
    for start, ch in enumerate(text):
        closer = pairs.get(ch)
        if closer is None:
            continue
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == ch:
                depth += 1
            elif c == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break  # this opener didn't yield JSON; try the next opener position
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
    if not isinstance(section, dict):
        raise ValueError(f"section entry must be a JSON object, got {type(section).__name__}")
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


def _bundle_from_state(state: dict) -> dict:
    """Assemble a narrative bundle from the sections recorded so far, in prepared order.

    Ordered by the prepared slice order (recorded at ``prepare_run`` time), not by
    ingestion-completion order — under parallel fan-out, sections can complete out of
    order. Any recorded section whose id isn't in the prepared order (defensive) is
    appended at the end, stably. Builds a new list; never mutates ``state``.
    """
    sections = state.get("sections", {})
    order = state.get("_section_order", [])
    ordered = [sections[sid] for sid in order if sid in sections]
    ordered_ids = set(order)
    extras = [section for sid, section in sections.items() if sid not in ordered_ids]
    return {"sections": ordered + extras}


def status_json(run_dir) -> dict:
    """Machine-readable run status: stage, next action, pending briefs, degradation."""
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


def _run_gate_stage(run_dir: Path, state: dict, facts_json: dict, project_root) -> dict:
    report = run_gate(state.get("_bundle", _bundle_from_state(state)), facts_json)
    if report.status == "PASS":
        state["_bundle"] = report.bundle
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


def _route_deterministic(run_dir: Path, state: dict, project_root, reason: str) -> dict:
    finalize_deterministic(run_dir, project_root=project_root, reason=reason)
    state["stage"] = "blocked"
    state["degradation_reason"] = reason
    _write_state(run_dir, state)
    return state


def advance_run(run_dir, *, project_root=None) -> dict:
    """Move the run forward one step: seed→fan→synth→gate→(patch→gate)*→continuity→gate→finalized.

    On gate exhaustion, routes to finalize_deterministic and sets stage to blocked.
    Never raises a gate failure as an exception — degradation is always graceful.
    """
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
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["_gate_rounds"] = 0
        state["stage"] = "gate"
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "gate":
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "patch":
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["stage"] = "gate"
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "continuity":
        edits = state.get("_continuity_edits", [])
        bundle = apply_continuity_edits(state.get("_bundle", _bundle_from_state(state)), edits)
        report = run_gate(bundle, facts_json)
        if report.status == "PASS":
            state["_bundle"] = report.bundle
            state["stage"] = "finalized"
        else:
            state["_bundle"] = bundle
            return _route_deterministic(run_dir, state, project_root, "continuity_gate_failed")
    _write_state(run_dir, state)
    return state


def finalize_deterministic(run_dir, *, project_root=None, reason):
    """Deterministic skeleton fallback — full implementation lands in a later task."""
    raise NotImplementedError("finalize_deterministic implemented in a later task")
