"""Passive, file-based narrative-workflow controller (host-neutral).

The controller prepares durable briefs and state and ingests sub-agent JSON,
but never spawns sub-agents. The host agent drives it (see runbook.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from xhs_ceramics_analytics.paths import outputs_dir, state_dir
from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
from xhs_ceramics_analytics.reporting.narrative_render import (
    apply_continuity_edits,
    bundle_to_markdown,
    render_draft,
)
from xhs_ceramics_analytics.reporting.report_telemetry import (
    append_run_record,
    build_run_record,
)

MAX_FAN_AGENTS = 6
MAX_GATE_ROUNDS = 2
# Review-stage patch budget (spec §Multi-Reviewer Review): a view whose 3 reviewers
# reach no keep/drop majority is re-authored at most this many times; a view still
# unconverged after the budget is spent is dropped, never blocking the report.
MAX_REVIEW_PATCH_ROUNDS = 2

_STATE_FILE = "state.json"
_RESULT_TABLES_FILE = "result_tables.json"
_SLUG_STRIP = re.compile(r"[^\w一-鿿]+")
_TERMINAL_STAGES = {"finalized", "blocked"}

# The three adversarial reviewer lenses (spec §Multi-Reviewer Review). Each is a
# distinct failure-mode lens — not a redundant voter. Prose only, no digits.
_REVIEW_LENSES: tuple[tuple[str, str], ...] = (
    ("价值", "能让商家做出一个动作吗?还是内部统计琐碎?默认拒绝无行动价值的视图。"),
    ("可读性", "非分析师商家 5 秒看得懂吗?列太多/列名黑话/该用趋势线却用表,默认拒绝。"),
    ("支撑", "真的证明了 supports_claim 那条结论吗?无关或方向相反,默认拒绝。"),
)

# Verdict vocabulary a reviewer may return (spec: keep / revise / drop). Anything
# outside this set counts toward neither keep nor drop, pushing the tally to patch.
_KEEP_VERDICT = "keep"
_DROP_VERDICT = "drop"
_KNOWN_VERDICTS: frozenset[str] = frozenset({"keep", "revise", "drop"})

_NEXT_ACTION = {
    "seed": "read briefs/seed.md, spawn one sub-agent, ingest --stage seed, then advance",
    "fan": "read briefs/fan_*.md, spawn one sub-agent per brief, ingest --stage fan each, then advance",
    "synth": "read briefs/synth.md, spawn one sub-agent to assemble the first screen, "
             "ingest --stage synth, then advance",
    "gate": "run advance to apply the deterministic fact-check gate",
    "patch": "read the patch brief, spawn one sub-agent, ingest --stage patch, then advance",
    "review": "read briefs/review_*.md, spawn 3 reviewers (价值/可读性/支撑) per domain, "
              "ingest --stage review each verdict, then advance",
    "continuity": "spawn one sub-agent to smooth transitions, ingest --stage continuity, then advance",
    "finalized": "done — deliver <name>.md + <name>.html",
    "blocked": "deterministic skeleton delivered — report degradation reason",
}


def tally_votes(verdicts) -> str:
    """Resolve one curated view's 3 reviewer verdicts to ``keep`` / ``drop`` / ``patch``.

    PURE and total: the exact strict precedence of spec §Multi-Reviewer Review, so
    every verdict combination maps to exactly one outcome:

    1. ``drop >= 2`` → ``drop`` (a clear majority to remove wins first).
    2. else ``keep >= 2`` → ``keep`` (2 keep + 1 drop, or 2 keep + 1 revise → keep).
    3. else → ``patch`` (any mix with no majority, incl. empty / all-revise).

    Tolerant of missing/garbled input and NEVER raises: a non-list, non-string
    elements, and unrecognized tokens (``revise`` or noise) simply count toward
    neither keep nor drop — they push the tally to ``patch``. Case- and
    whitespace-insensitive.
    """
    keep = drop = 0
    if isinstance(verdicts, (list, tuple)):
        for verdict in verdicts:
            if not isinstance(verdict, str):
                continue
            token = verdict.strip().lower()
            if token == _DROP_VERDICT:
                drop += 1
            elif token == _KEEP_VERDICT:
                keep += 1
    if drop >= 2:
        return "drop"
    if keep >= 2:
        return "keep"
    return "patch"


def _view_action(verdicts, *, patch_rounds: int) -> str:
    """Final fate of one curated view: ``keep`` / ``drop`` / ``patch``. Never raises.

    Layers stage policy on the pure :func:`tally_votes`:

    - Missing / garbled reviewer input (no recognized keep/revise/drop verdict at
      all) degrades to ``drop`` — the adversarial default is "prefer fewer visuals
      over a dump", and a view no reviewer could judge is dropped, not kept.
    - A ``patch`` outcome whose patch budget is already spent degrades to ``drop``
      (bounded to ``MAX_REVIEW_PATCH_ROUNDS``), so an unconvergeable view never
      blocks the report.
    - ``keep`` / ``drop`` pass through.
    """
    recognized = [
        v for v in (verdicts or [])
        if isinstance(v, str) and v.strip().lower() in _KNOWN_VERDICTS
    ]
    if not recognized:
        return "drop"
    outcome = tally_votes(recognized)
    if outcome == "patch" and patch_rounds >= MAX_REVIEW_PATCH_ROUNDS:
        return "drop"
    return outcome


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
            f"为版块 `{section_id}` 写「claims + 策展视图」。数字只出现在 claim 的 number_tokens 里,",
            "由确定性引擎从下方 facts 回填 —— 你只写句子模板(用 {tN} 占位)与结构,绝不写裸数字。",
            "",
            "每条 claim 的结构:",
            '  {"claim_id","section_id","claim_kind":"measurement|mechanism|sizing",',
            '   "sentence":"…{t0}…(仅含 {tN} 占位,不得含任何裸数字)",',
            '   "number_tokens":[{"token_id":"t0","fact_id":"<下方 facts 里的 fact_id>",'
            '"expected_metric_key":"<该 fact 的 metric_key>"}],',
            '   "entity_refs":[],"confidence":"强|中|弱"}',
            "每个 number_token 的 fact_id 必须精确等于下方某个 facts[].fact_id;",
            "没有 fact_id 的 fact 是标签(非数值),不能被 number_token 绑定。",
            "",
            "curated_views(可选,每域 ≤2 表 + ≤1 图):只从已算好的源表里选列/排序/TopN,",
            "supports_claim 必须指向本域某条 claim_id;标题/图注是纯文字,不得含裸数字。",
            "",
            'Return JSON only: {"section_id","title","claims":[...],"curated_views":[...]}.',
            "",
            "```json",
            json.dumps(payload, ensure_ascii=False, indent=2),
            "```",
        ]
        path = briefs / f"fan_{idx:02d}_{section_id}.md"
        path.write_text("\n".join(body) + "\n", encoding="utf-8")
        paths.append(path)
    return paths


def _claim_summaries(state: dict) -> list[dict]:
    """Flatten the recorded fan claims into compact summaries so the synth agent can
    reference real ``claim_id``s when assembling the first screen. Ordered by the
    prepared slice order (falling back to any extra recorded sections at the end)."""
    sections = state.get("sections", {})
    order = state.get("_section_order", [])
    ordered_ids = [sid for sid in order if sid in sections]
    seen = set(ordered_ids)
    ordered_ids += [sid for sid in sections if sid not in seen]
    out: list[dict] = []
    for sid in ordered_ids:
        section = sections[sid]
        for claim in section.get("claims", []):
            if not isinstance(claim, dict):
                continue
            out.append(
                {
                    "claim_id": claim.get("claim_id", ""),
                    "section_id": claim.get("section_id", section.get("section_id", sid)),
                    "claim_kind": claim.get("claim_kind", ""),
                    "sentence": claim.get("sentence", ""),
                    "confidence": claim.get("confidence", ""),
                }
            )
    return out


def _write_synth_brief(run_dir: Path, state: dict) -> None:
    """Write the synth brief: surface every recorded fan claim (so synth can reference
    real ``claim_id``s) and request the bundle-level first screen. The synth agent
    invents no numbers — spine/panel entries stay claim-like dicts whose ``{tN}`` tokens
    the deterministic engine later fills from facts.json."""
    summaries = _claim_summaries(state)
    lines = [
        "# Synth brief — 组装首屏与全局综合",
        "",
        "下面是各版块 fan agent 已产出的 claims 摘要。据此组装「首屏」:挑出最能支撑主结论的",
        "claim 进 spine/panel(整条 claim-like dict,含 sentence 与 number_tokens;数字仍由确定性",
        "引擎回填,你绝不写裸数字),并给出 headline / cannot_say / spine_final。",
        "",
        'Return JSON only: {"headline","first_screen":{"spine":[…],"panel":[…],"actions":[…]},'
        '"cannot_say":[…],"spine_final":{…}}.',
        "spine/panel 每条须是 claim-like dict(可直接复用下方某条 claim,或组合其 claim_id);",
        "actions 是纯文字行动建议;cannot_say 是本次数据答不了的问题。",
        "",
        "## 已产出的 claims",
        "",
        "```json",
        json.dumps(summaries, ensure_ascii=False, indent=2),
        "```",
    ]
    (run_dir / "briefs" / "synth.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    # persist the already-computed result.tables (numeric-trust source for the
    # curated-view engine + gate). Absent/garbage degrades to {} → prose-only.
    tables = results.get("result_tables")
    if not isinstance(tables, dict):
        tables = results.get("tables") if isinstance(results.get("tables"), dict) else {}
    (run_dir / _RESULT_TABLES_FILE).write_text(
        json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return state


def _load_result_tables(run_dir: Path) -> dict:
    """Load the persisted ``result.tables``. Missing/garbage degrades to ``{}`` so
    the curated-view path silently falls back to prose-only. Never raises."""
    path = Path(run_dir) / _RESULT_TABLES_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _run_gate(bundle: dict, facts_json: dict, result_tables: dict):
    """Call ``run_gate`` with ``result_tables`` only when there are tables to police.

    When no tables were provided (today's prose-only runs, and the existing test
    suite's 2-arg ``run_gate`` monkeypatches), this stays a 2-arg call so the gate's
    behavior and signature expectations are unchanged. When tables ARE present the
    3rd arg lets the gate enforce the curated-view trust/anti-dump rules."""
    if result_tables:
        return run_gate(bundle, facts_json, result_tables)
    return run_gate(bundle, facts_json)


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)

_EXPECTED_STATUS = {
    "seed": {"seed"},
    "fan": {"fan"},
    "synth": {"synth"},
    "patch": {"patch"},
    "review": {"review"},
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
    recorded = {
        "section_id": section_id,
        "title": title,
        "body": section.get("body", ""),
    }
    # Preserve the agent-emitted claims (Option A: the renderer/gate/first_screen are
    # all built on ``section.claims[]``, not on prose ``body``). Kept as opaque dicts —
    # sentence carries only {tN}, number_tokens bind to real fact_ids, confidence is
    # gate-capped. Only added when present, so prose-only/skeleton sections that carry
    # no claims stay byte-identical to before.
    claims = section.get("claims")
    if isinstance(claims, (list, tuple)):
        recorded["claims"] = [c for c in claims if isinstance(c, dict)]
    # Preserve the agent-emitted curated view-specs so they survive into the
    # bundle (via _bundle_from_state) and reach the gate / review / render.
    views = section.get("curated_views")
    if isinstance(views, (list, tuple)):
        recorded["curated_views"] = [v for v in views]
    # Preserve section→spine callbacks so the gate's cross-section continuity check
    # (DANGLING_CALLBACK / MISSING_SPINE_CALLBACK) sees them.
    callbacks = section.get("spine_callbacks")
    if isinstance(callbacks, (list, tuple)):
        recorded["spine_callbacks"] = list(callbacks)
    state["sections"][section_id] = recorded


# Bundle-level synthesis the SYNTH agent assembles once, across all sections (spec
# §First screen). Captured into state['_synth'] and re-emitted by _bundle_from_state.
_BUNDLE_LEVEL_KEYS = ("first_screen", "headline", "cannot_say", "spine_final")
# What marks a synth dict as a section payload (vs a pure first-screen payload) — used
# so a bare {first_screen, headline, ...} is NOT mis-recorded as a bogus section.
_SECTION_MARKERS = ("section_id", "claims", "body", "curated_views")


def _capture_bundle_fields(state: dict, parsed) -> None:
    """Capture the synth agent's bundle-level synthesis into ``state['_synth']``.

    Only keys actually present are copied, so a synth output carrying just some of the
    fields (or none) degrades gracefully — a later ``_bundle_from_state`` simply omits
    the absent ones. Never raises."""
    if not isinstance(parsed, dict):
        return
    synth = state.setdefault("_synth", {})
    for key in _BUNDLE_LEVEL_KEYS:
        if key in parsed:
            synth[key] = parsed[key]


def _looks_like_section(parsed) -> bool:
    """True if a dict carries section content (so synth can still fold in a section it
    re-emits alongside the first screen), False for a pure bundle-level payload."""
    return isinstance(parsed, dict) and any(k in parsed for k in _SECTION_MARKERS)


def _ingest_synth(state: dict, text: str) -> None:
    """Ingest a SYNTH result: capture the bundle-level first screen AND record any
    section(s) the synth agent re-emitted. Unlike the generic path, a bare
    ``{first_screen, headline, …}`` payload (no section markers) records NO section, so
    it is never mistaken for a section titled 'section'. Never raises beyond a genuinely
    unparseable payload (extract_json), matching the other stages."""
    parsed = extract_json(text)
    if isinstance(parsed, list):
        for section in parsed:
            _record_section(state, section)
        return
    if isinstance(parsed, dict):
        _capture_bundle_fields(state, parsed)
        sections = parsed.get("sections")
        if isinstance(sections, list):
            for section in sections:
                _record_section(state, section)
        elif _looks_like_section(parsed):
            _record_section(state, parsed)
        return
    raise ValueError("ingested JSON is neither an object nor a list of sections")


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

    if stage == "review":
        # Reviewer verdicts, not sections. Parse tolerantly — garbled/unparseable
        # reviewer output records nothing (never raises); the advance step then
        # degrades any view with no usable verdict to a drop.
        try:
            parsed = extract_json(text)
        except ValueError:
            parsed = None
        _ingest_review_verdicts(state, parsed)
        state.setdefault("history", []).append("ingest:review")
        _write_state(run_dir, state)
        return state

    if stage == "synth":
        # SYNTH assembles the bundle-level first screen (+ may re-emit sections). Handled
        # separately so a pure first-screen payload is captured, not recorded as a section.
        _ingest_synth(state, text)
        state.setdefault("history", []).append("ingest:synth")
        _write_state(run_dir, state)
        return state

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
    bundle: dict = {"sections": ordered + extras}
    # Fold in the synth agent's bundle-level synthesis (first_screen / headline /
    # cannot_say / spine_final). Only keys actually captured are added, so a prose-only
    # or pre-synth run yields exactly {"sections": [...]} as before (backward compatible).
    synth = state.get("_synth") or {}
    for key in _BUNDLE_LEVEL_KEYS:
        if key in synth:
            bundle[key] = synth[key]
    return bundle


# ---- curated-view review stage (spec §Multi-Reviewer Review) --------------


def _view_key(section_id, view, idx: int) -> str:
    """Stable identity for one curated view: its ``view_id`` when present, else a
    positional ``{section_id}#{idx}`` fallback. Used to key reviewer verdicts."""
    if isinstance(view, dict):
        vid = view.get("view_id")
        if isinstance(vid, str) and vid.strip():
            return vid.strip()
    return f"{section_id}#{idx}"


def _iter_curated_views(bundle):
    """Yield ``(section_id, idx, view)`` for every curated view in the bundle.
    Never raises — malformed sections/views are skipped."""
    for section in (bundle or {}).get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = section.get("section_id")
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)):
            continue
        for idx, view in enumerate(views):
            yield section_id, idx, view


def _bundle_has_curated_views(bundle) -> bool:
    """True iff at least one section carries a (dict) curated view to review."""
    for _sid, _idx, view in _iter_curated_views(bundle):
        if isinstance(view, dict):
            return True
    return False


def _iter_verdict_items(parsed):
    """Yield the per-view verdict dicts from a tolerant range of shapes. Never raises.

    Accepts ``{"verdicts": [...]}`` / ``{"views": [...]}`` / ``{"reviews": [...]}``,
    a bare list of verdict dicts, or a single ``{"verdict": ...}`` object.
    """
    if isinstance(parsed, dict):
        for field_name in ("verdicts", "views", "reviews"):
            seq = parsed.get(field_name)
            if isinstance(seq, (list, tuple)):
                for item in seq:
                    if isinstance(item, dict):
                        yield item
                return
        if "verdict" in parsed:
            yield parsed
    elif isinstance(parsed, (list, tuple)):
        for item in parsed:
            if isinstance(item, dict):
                yield item


def _ingest_review_verdicts(state: dict, parsed) -> None:
    """Accumulate one reviewer's verdicts into ``state['_reviews']`` (view_key →
    list[str]) and their reasons into ``state['_review_reasons']``. Never raises —
    entries lacking a view id or verdict string are skipped."""
    reviews = state.setdefault("_reviews", {})
    reasons = state.setdefault("_review_reasons", {})
    for item in _iter_verdict_items(parsed):
        key = item.get("view_id") or item.get("view_key")
        verdict = item.get("verdict")
        if not (isinstance(key, str) and key):
            continue
        if not isinstance(verdict, str) or not verdict.strip():
            continue
        reviews.setdefault(key, []).append(verdict)
        reason = item.get("reason")
        if isinstance(reason, str) and reason.strip():
            reasons.setdefault(key, []).append(reason.strip())


def _resolve_section_views(section_id, views, reviews: dict, patch_rounds: int):
    """Decide each view's fate for one section. Returns ``(kept_views, patched_keys)``.

    ``kept_views`` retains keep AND patch views (a patch view is re-authored in
    place); dropped views are omitted. ``patched_keys`` lists views still needing a
    patch round. Never raises."""
    kept: list = []
    patched: list[str] = []
    if not isinstance(views, (list, tuple)):
        return kept, patched
    for idx, view in enumerate(views):
        key = _view_key(section_id, view, idx)
        action = _view_action(reviews.get(key, []), patch_rounds=patch_rounds)
        if action == "drop":
            continue
        kept.append(view)
        if action == "patch":
            patched.append(key)
    return kept, patched


def _sync_recorded_curated_views(state: dict, reviews: dict, patch_rounds: int) -> None:
    """Apply the same drop decisions to ``state['sections']`` so a later patch
    rebuild (via :func:`_bundle_from_state`) does not resurrect a dropped view.
    Rebuilds each ``curated_views`` list; never raises."""
    for sid, section in (state.get("sections") or {}).items():
        if not isinstance(section, dict):
            continue
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)) or not views:
            continue
        kept, _patched = _resolve_section_views(
            section.get("section_id", sid), views, reviews, patch_rounds
        )
        section["curated_views"] = kept


def _write_review_briefs(run_dir: Path, bundle: dict) -> None:
    """Write one reviewer brief per (domain, lens) — 3 lenses per domain, each
    judging that domain's curated views through its single failure-mode lens. Prose
    + column names only (no numbers — the gate already locked those). Never raises."""
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    by_section: dict = {}
    for section_id, idx, view in _iter_curated_views(bundle):
        by_section.setdefault(section_id, []).append((idx, view))
    for section_id, views in by_section.items():
        payload_views = []
        for idx, view in views:
            v = view if isinstance(view, dict) else {}
            payload_views.append(
                {
                    "view_id": _view_key(section_id, view, idx),
                    "template": v.get("template", ""),
                    "title": v.get("title", ""),
                    "columns": list(v.get("columns") or []),
                    "how_to_read": v.get("how_to_read", ""),
                    "why_it_matters": v.get("why_it_matters", ""),
                    "supports_claim": v.get("supports_claim", ""),
                }
            )
        for lens, question in _REVIEW_LENSES:
            lines = [
                f"# Review brief — 域『{section_id}』· 视角『{lens}』",
                "",
                f"你是「{lens}」评审员。只问一件事:{question}",
                "对下面每个策展视图给出 keep / revise / drop 之一 + 一句理由。",
                "你只评判价值/可读性/支撑,不能改数字(确定性 gate 已锁定数值)。",
                "宁可少放视图,也不要堆砌。返回 JSON:",
                '{"section_id","lens","verdicts":[{"view_id","verdict":"keep|revise|drop","reason"}]}',
                "",
                "```json",
                json.dumps(
                    {"section_id": section_id, "lens": lens, "views": payload_views},
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
            ]
            path = briefs_dir / f"review_{_slug(str(section_id))}_{_slug(lens)}.md"
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_review_patch_brief(
    run_dir: Path, bundle: dict, patched_keys, reasons: dict
) -> None:
    """Write the patch brief for views the reviewers could not converge on. The
    patch agent re-authors only the view-spec (template/columns/rows/source/prose)
    using the merged reviewer reasons — never writes a number. Never raises."""
    briefs_dir = run_dir / "briefs"
    briefs_dir.mkdir(parents=True, exist_ok=True)
    targets = set(patched_keys)
    payload = []
    for section_id, idx, view in _iter_curated_views(bundle):
        key = _view_key(section_id, view, idx)
        if key not in targets:
            continue
        v = view if isinstance(view, dict) else {}
        payload.append(
            {
                "view_id": key,
                "section_id": section_id,
                "template": v.get("template", ""),
                "title": v.get("title", ""),
                "columns": list(v.get("columns") or []),
                "supports_claim": v.get("supports_claim", ""),
                "merged_reasons": list(reasons.get(key, [])),
            }
        )
    lines = [
        "# Patch brief — 评审未收敛的策展视图",
        "",
        "以下视图三位评审投票无多数(既非 keep 也非 drop)。请按 merged_reasons 重挑列/减列/",
        "换模板/换源表后重写其 view-spec。只改 view-spec,不得写入任何数值(确定性引擎从源表填数)。",
        '返回 JSON:{"sections":[{"section_id","title","body","curated_views":[...]}]}',
        "",
        "```json",
        json.dumps({"views_to_repatch": payload}, ensure_ascii=False, indent=2),
        "```",
    ]
    (briefs_dir / "review_patch.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _enter_review_or_continuity(run_dir: Path, state: dict) -> dict:
    """Post-gate router: a bundle carrying curated views goes to the ``review``
    stage (fresh verdict slate + reviewer briefs); a prose-only bundle skips
    straight to ``continuity`` (today's behavior). Persists + returns state."""
    bundle = state.get("_bundle") or {}
    if _bundle_has_curated_views(bundle):
        state["_reviews"] = {}
        state["_review_reasons"] = {}
        state.setdefault("_review_patch_rounds", 0)
        state.pop("_review_patch_pending", None)
        _write_review_briefs(run_dir, bundle)
        state["stage"] = "review"
    else:
        state["stage"] = "continuity"
    _write_state(run_dir, state)
    return state


def _resolve_review_stage(run_dir: Path, state: dict) -> dict:
    """Tally each curated view's verdicts and route: drop → remove; keep → retain;
    no-majority → patch (bounded to ``MAX_REVIEW_PATCH_ROUNDS``, then dropped).

    When any view still needs a patch round, routes to the existing ``patch`` stage
    with a re-author brief and a fresh verdict slate. Otherwise applies the drops
    and advances to ``continuity``. Never raises; a section left with zero views
    degrades to prose-only, and the report still finalizes."""
    reviews = state.get("_reviews") or {}
    reasons = state.get("_review_reasons") or {}
    patch_rounds = state.get("_review_patch_rounds", 0)
    bundle = state.get("_bundle") or _bundle_from_state(state)

    patched_keys: list[str] = []
    new_sections: list = []
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            new_sections.append(section)
            continue
        views = section.get("curated_views")
        if not isinstance(views, (list, tuple)) or not views:
            new_sections.append(section)
            continue
        kept, patched = _resolve_section_views(
            section.get("section_id"), views, reviews, patch_rounds
        )
        patched_keys.extend(patched)
        new_sections.append({**section, "curated_views": kept})

    new_bundle = {**bundle, "sections": new_sections}
    state["_bundle"] = new_bundle
    # keep the recorded sections in sync so a patch rebuild preserves the drops
    _sync_recorded_curated_views(state, reviews, patch_rounds)

    if patched_keys:
        state["_review_patch_rounds"] = patch_rounds + 1
        state["_reviews"] = {}
        state["_review_reasons"] = {}
        state["_review_patch_pending"] = list(patched_keys)
        _write_review_patch_brief(run_dir, new_bundle, patched_keys, reasons)
        state["stage"] = "patch"
        _write_state(run_dir, state)
        return state

    state["_reviews"] = {}
    state["_review_reasons"] = {}
    state.pop("_review_patch_pending", None)
    state["stage"] = "continuity"
    _write_state(run_dir, state)
    return state


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
    elif stage == "synth":
        briefs = [str(briefs_dir / "synth.md")]
    elif stage == "review":
        briefs = [str(p) for p in sorted(briefs_dir.glob("review_*.md")) if p.name != "review_patch.md"]
    elif stage == "patch" and state.get("_review_patch_pending"):
        briefs = [str(briefs_dir / "review_patch.md")]
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
    result_tables = _load_result_tables(run_dir)
    report = _run_gate(state.get("_bundle", _bundle_from_state(state)), facts_json, result_tables)
    if report.status == "PASS":
        state["_bundle"] = report.bundle
        # numeric trust is now locked; a bundle with curated views goes to the
        # adversarial review stage, a prose-only bundle straight to continuity.
        return _enter_review_or_continuity(run_dir, state)
    rounds = state.get("_gate_rounds", 0) + 1
    state["_gate_rounds"] = rounds
    if rounds > MAX_GATE_ROUNDS:
        return _route_deterministic(run_dir, state, project_root, "gate_exhausted")
    state["_gate_failures"] = list(report.hard_failures)
    state["stage"] = "patch"
    _write_state(run_dir, state)
    return state


def _route_deterministic(run_dir: Path, state: dict, project_root, reason: str) -> dict:
    """Adopt the state finalize_deterministic returns rather than re-deriving one.

    Defensively re-asserts stage/degradation_reason on top of the returned dict so
    a monkeypatched finalize_deterministic (which may return a minimal stand-in
    without degradation_reason) still yields a correctly-routed state. Builds one
    new dict and persists it exactly once — never double-writes state.json.
    """
    result = finalize_deterministic(run_dir, project_root=project_root, reason=reason)
    result = {**result, "stage": "blocked", "degradation_reason": reason}
    _write_state(run_dir, result)
    return result


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
        # Surface the recorded fan claims so the synth agent can assemble the first
        # screen from real claim_ids (Option A). Falls through to _write_state below.
        _write_synth_brief(run_dir, state)
    elif stage == "synth":
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["_gate_rounds"] = 0
        state["_review_patch_rounds"] = 0
        state["stage"] = "gate"
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "gate":
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "patch":
        bundle = render_draft(_bundle_from_state(state), facts_json)
        state["_bundle"] = bundle
        state["stage"] = "gate"
        return _run_gate_stage(run_dir, state, facts_json, project_root)
    elif stage == "review":
        # Passive multi-reviewer resolution: tally per view, route keep/drop/patch.
        return _resolve_review_stage(run_dir, state)
    elif stage == "continuity":
        edits = state.get("_continuity_edits", [])
        bundle = apply_continuity_edits(state.get("_bundle", _bundle_from_state(state)), edits)
        report = _run_gate(bundle, facts_json, _load_result_tables(run_dir))
        if report.status == "PASS":
            state["_bundle"] = report.bundle
            _write_state(run_dir, state)
            return finalize_narrative(run_dir, project_root=project_root)
        state["_bundle"] = bundle
        return _route_deterministic(run_dir, state, project_root, "continuity_gate_failed")
    _write_state(run_dir, state)
    return state


def _fmt_value(value):
    """Render a fact value for the skeleton table: thousands-separated for numbers."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f"{value:,}"
    return str(value)


def _deterministic_markdown(run_dir, facts_json: dict, report_name: str) -> str:
    """Build the '确定性骨架版' markdown straight from capped slices + facts.

    Preserves conclusions/actions/caveats verbatim (no paraphrasing) and lists
    any blocked modules under an explicit "暂时答不了的问题" section. Never raises
    on missing/partial data — absent fields are simply omitted.
    """
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
        reading = s.get("reading") or {}
        lines.append(f"## {title}")
        lines.append("")
        if reading.get("conclusion"):
            lines.append(f"**结论：** {reading['conclusion']}")
            lines.append("")
        if reading.get("action"):
            lines.append(f"**建议动作：** {reading['action']}")
            lines.append("")
        facts = s.get("facts") or []
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

    blocked = slices_doc.get("blocked_modules") or []
    if blocked:
        lines.append("## 暂时答不了的问题")
        lines.append("")
        for b in blocked:
            if isinstance(b, dict):
                slug = b.get("slug", "")
                reason = b.get("reason", "")
            else:
                slug = str(b)
                reason = ""
            lines.append(f"- {slug}：{reason}")
        lines.append("")

    return "\n".join(lines) + "\n"


def finalize_narrative(run_dir, *, project_root=None) -> dict:
    """Success delivery boundary — render the gate-passed narrative bundle to the two
    artifacts (<report_name>.md + <report_name>.html) under outputs_dir(project_root).

    The .md is written unconditionally from ``state["_bundle"]`` via bundle_to_markdown
    (the narrative renderer, NOT the skeleton one — no 确定性骨架版 banner). HTML render/write
    and gate-mode telemetry are each best-effort, mirroring finalize_deterministic's
    never-raise discipline: a failure there can never prevent the .md artifact from landing
    or prevent this function from returning the finalized state. Marks the run finalized and
    returns the updated state. Never raises on missing/partial bundle or fact data.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    project_root = Path(project_root or state.get("project_root") or ".")
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    report_name = state["report_name"]
    bundle = state.get("_bundle") or _bundle_from_state(state)
    result_tables = _load_result_tables(run_dir)

    # Pass result_tables so each retained curated view's numbers are filled by the
    # deterministic engine from the source table (the numeric-trust boundary). With
    # no tables the views degrade to prose-only — the report still delivers.
    markdown = bundle_to_markdown(
        bundle, facts_json, title=report_name, result_tables=result_tables
    )
    out_dir = outputs_dir(project_root)
    (out_dir / f"{report_name}.md").write_text(markdown, encoding="utf-8")

    try:
        html = render_markdown_document_html(markdown, title=report_name)
        (out_dir / f"{report_name}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass  # HTML rendering is best-effort; the markdown artifact must still land

    try:
        record = build_run_record(
            mode="gate",
            facts_hash=facts_json.get("facts_hash", ""),
            cache_hit=False,
            hard_fail_counts={},
            degradation_reason=None,
        )
        append_run_record(state_dir(project_root) / "report_runs.jsonl", record)
    except Exception:
        pass  # telemetry is best-effort; never break the report

    state = {
        **state,
        "stage": "finalized",
        "history": [*state.get("history", []), "finalize_narrative"],
    }
    _write_state(run_dir, state)
    return state


def finalize_deterministic(run_dir, *, project_root=None, reason) -> dict:
    """Deterministic skeleton fallback — the delivery boundary that never fails open.

    Writes <report_name>.md unconditionally under outputs_dir(project_root), then
    best-effort renders <report_name>.html and appends skeleton-mode telemetry to
    state_dir(project_root)/"report_runs.jsonl" (the canonical telemetry file cli.py
    also writes to, read by summarize_runs). HTML render/write and telemetry are
    each wrapped so a failure there can never prevent the .md artifact from landing
    or prevent this function from returning the blocked state. Marks the run
    blocked with the given degradation reason and returns the updated state. Never
    raises on missing/partial slice or fact data.
    """
    run_dir = Path(run_dir)
    state = _load_state(run_dir)
    if state is None:
        raise FileNotFoundError(f"no run at {run_dir}")
    project_root = Path(project_root or state.get("project_root") or ".")
    facts_json = json.loads((run_dir / "facts.json").read_text(encoding="utf-8"))
    report_name = state["report_name"]

    markdown = _deterministic_markdown(run_dir, facts_json, report_name)
    out_dir = outputs_dir(project_root)
    (out_dir / f"{report_name}.md").write_text(markdown, encoding="utf-8")

    try:
        html = render_markdown_document_html(markdown, title=f"{report_name}（确定性骨架版）")
        (out_dir / f"{report_name}.html").write_text(html, encoding="utf-8")
    except Exception:
        pass  # HTML rendering is best-effort; the markdown artifact must still land

    try:
        record = build_run_record(
            mode="skeleton",
            facts_hash=facts_json.get("facts_hash", ""),
            cache_hit=False,
            degradation_reason=reason,
        )
        append_run_record(state_dir(project_root) / "report_runs.jsonl", record)
    except Exception:
        pass  # telemetry is best-effort; never break the report

    state = {
        **state,
        "stage": "blocked",
        "degradation_reason": reason,
        "history": [*state.get("history", []), f"finalize_deterministic:{reason}"],
    }
    _write_state(run_dir, state)
    return state
