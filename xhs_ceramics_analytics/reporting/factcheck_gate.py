# xhs_ceramics_analytics/reporting/factcheck_gate.py
"""Structural fact-check gate — the truth owner (pure Python, never an agent).

The writer's sentences carry only opaque ``{tN}`` tokens; every magnitude is a
declared ``number_token`` pointing at a ``fact_id``. This gate validates that
structure against the FactBook and registries, so a fabricated number-string is
unrepresentable. HARD failures block render (编造数字/发明实体/引用不存在切片/
异口径池相加/带数字的既成归因/悬空回指). WARN codes fight timidity and label gaps
but never block a bold, tagged conclusion. Confidence is capped deterministically
(mechanism → 弱; else ≤ the strongest anchor) — the honesty mechanism that replaces
the nondeterministic "spine skeptic" agent. Immutable: capping returns a NEW bundle.
"""
import copy
import json
import re
from dataclasses import dataclass, field
from html import escape

from xhs_ceramics_analytics.reporting.curated_view import render_view
from xhs_ceramics_analytics.reporting.formatting import format_scalar, is_timeseries_table
from xhs_ceramics_analytics.reporting.view_spec import (
    CHART_TEMPLATES,
    validate_view_spec,
)

_TOKEN_RE = re.compile(r"\{t\d+\}")
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL)

# There is deliberately NO per-domain view cap. Anti-dump is enforced per view
# (rules 1-3: every curated view must be spec-valid, value-matched, and support a
# real claim), so a section may carry as many tables/charts as it can back.
_DIGIT_RE = re.compile(r"\d")
# first_screen.actions are writer free-text (no token mechanism), so the {tN} gate can't
# cover them. We can't ban every digit — advice legitimately says "发 2 到 3 条内容" — but a
# currency / percent / 万·亿 figure there is an un-anchored data magnitude the writer invented.
_ACTION_MAGNITUDE_RE = re.compile(r"[¥￥$%]|\d+(?:\.\d+)?\s*[万亿]")
_TAG_RANK = {"弱": 1, "中": 2, "强": 3}
_RANK_TAG = {1: "弱", 2: "中", 3: "强"}


@dataclass(frozen=True)
class GateReport:
    status: str
    hard_failures: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    capped_claims: list[dict] = field(default_factory=list)
    bundle: dict = field(default_factory=dict)


def _fail(code: str, claim_id: str | None, detail: str) -> dict:
    return {"code": code, "claim_id": claim_id, "detail": detail}


def _iter_claims(bundle: dict):
    """Yield every claim in the bundle (sections + first_screen), with its claim_id."""
    for section in bundle.get("sections") or []:
        for claim in section.get("claims") or []:
            yield claim
    fs = bundle.get("first_screen") or {}
    for key in ("spine", "panel"):
        for claim in fs.get(key) or []:
            if isinstance(claim, dict) and "sentence" in claim:
                yield claim


def allowed_confidence_tag(claim: dict, facts: dict) -> str:
    """Strongest tag the claim's anchors support (mirrors trust_routing.confidence_tag).

    The single source of truth for "what confidence does this claim's evidence
    defensibly allow" — used by the gate to CAP an overstated claim and by the
    narrative renderer to derive a curated view's badge from the claim it supports
    (never from an agent-authored field). Pure, never raises."""
    if claim.get("claim_kind") == "mechanism":
        return "弱"
    best = 1
    for tok in claim.get("number_tokens") or []:
        fact = facts.get(tok.get("fact_id")) or {}
        es = fact.get("evidence_strength")
        dr = fact.get("descriptive_reliability")
        if es == "strong" or dr == "high":
            rank = 3
        elif dr == "medium":
            rank = 2
        else:
            rank = 1
        best = max(best, rank)
    return _RANK_TAG[best]


def _check_tokens(claim: dict, facts: dict, absent: set, hard: list) -> None:
    cid = claim.get("claim_id")
    sentence = str(claim.get("sentence") or "")
    tokens = claim.get("number_tokens") or []
    # MAGNITUDE_UNBOUND — declared tokens must match {tN} in the sentence exactly,
    # and no bare digit may survive token removal (writer never emits a number).
    in_sentence = set(_TOKEN_RE.findall(sentence))
    token_ids = [str(t.get("token_id")) for t in tokens]
    declared = {"{" + tid + "}" for tid in token_ids}
    if in_sentence != declared:
        hard.append(_fail("MAGNITUDE_UNBOUND", cid,
                          f"token mismatch: sentence {sorted(in_sentence)} vs declared "
                          f"{sorted(declared)}"))
    if len(token_ids) != len(set(token_ids)):
        hard.append(_fail("MAGNITUDE_UNBOUND", cid,
                          "duplicate token_id within a claim (only the first would fill)"))
    if _DIGIT_RE.search(_TOKEN_RE.sub("", sentence)):
        hard.append(_fail("MAGNITUDE_UNBOUND", cid, "bare digit outside a {tN} token"))
    for tok in tokens:
        fid = tok.get("fact_id")
        if fid in absent:
            hard.append(_fail("NONEXISTENT_SLICE", cid, f"cites absent slice/link: {fid}"))
            continue
        fact = facts.get(fid)
        if fact is None:
            hard.append(_fail("MISSING_FACT", cid, f"no such fact_id: {fid}"))
            continue
        if tok.get("expected_metric_key") not in (None, fact.get("metric_key")):
            hard.append(_fail("METRIC_MISBIND", cid,
                              f"{fid}: expected metric {tok.get('expected_metric_key')} "
                              f"!= fact {fact.get('metric_key')}"))
        td, fd = tok.get("direction"), fact.get("direction")
        if td is not None and fd is not None and td != fd:
            hard.append(_fail("DIRECTION_CONFLICT", cid, f"{fid}: token {td} != fact {fd}"))


def _check_pools(claim: dict, facts: dict, hard: list) -> None:
    pools = set()
    for tok in claim.get("number_tokens") or []:
        pid = (facts.get(tok.get("fact_id")) or {}).get("pool_id")
        if pid:
            pools.add(pid)
    if len(pools) >= 2:
        hard.append(_fail("SUMMED_POOLS", claim.get("claim_id"),
                          f"claim mixes incompatible pools {sorted(pools)} (use 不可加台账)"))


def _check_causal(claim: dict, absent_links: set, hard: list) -> None:
    link = claim.get("causal_link")
    if not link:
        return
    key = f"{link.get('from_entity_type')}->{link.get('to_entity_type')}"
    if link.get("quantified") and key in absent_links:
        hard.append(_fail("QUANTIFIED_ATTRIBUTION", claim.get("claim_id"),
                          f"quantified attribution on absent link {key}"))


# ---- curated-view policing (spec §Trust & anti-dump rules) ----------------


def _all_claim_ids(bundle: dict) -> set[str]:
    """Every real claim_id in the bundle — the anti-dump anchor set for rule 3."""
    ids: set[str] = set()
    for claim in _iter_claims(bundle):
        cid = claim.get("claim_id")
        if isinstance(cid, str) and cid:
            ids.add(cid)
    return ids


def _view_label(view: object, section_id: object, idx: int) -> str:
    """Human-readable id for a view failure (view_id, else positional fallback)."""
    if isinstance(view, dict):
        vid = view.get("view_id")
        if isinstance(vid, str) and vid:
            return vid
    return f"{section_id}:curated_view[{idx}]"


def _source_cell_strings(view: dict, result_tables: dict) -> set[str]:
    """Every source cell value (for the selected columns), escaped exactly as the
    engine escapes a rendered ``<td>``. The value-match set the display must be a
    subset of — numbers come only from here, never from agent text."""
    source = view.get("source") if isinstance(view.get("source"), dict) else {}
    rows = result_tables.get(source.get("table"))
    if not isinstance(rows, (list, tuple)):
        return set()
    columns = view.get("columns")
    columns = list(columns) if isinstance(columns, (list, tuple)) else []
    cells: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for col in columns:
            # Format exactly as the engine renders a <td> (via the shared
            # format_scalar), so the value-match compares formatted-vs-formatted:
            # both sides derive deterministically from the same source row, keeping
            # the numeric-trust boundary intact.
            cells.add(escape(format_scalar(col, row.get(col))))
    return cells


def _is_timeseries_table_view(view: dict, result_tables: dict) -> bool:
    """True for a TABLE-template view whose source is a per-period (timeseries)
    table — the wall-of-dates grid the form guard suppresses. A chart-template over
    the same source is the correct form and is NOT flagged."""
    template = view.get("template")
    if template in CHART_TEMPLATES:
        return False
    source = view.get("source") if isinstance(view.get("source"), dict) else {}
    table_name = str(source.get("table") or "")
    rows = result_tables.get(source.get("table"))
    columns: list[str] = []
    if isinstance(rows, (list, tuple)):
        for row in rows:
            if isinstance(row, dict):
                columns = list(row.keys())
                break
    return is_timeseries_table(table_name, columns)


def _view_value_matches(rendered: object, view: dict, result_tables: dict) -> bool:
    """rule 2 (VALUE-MATCH): every number the engine would display must come from
    the source table — never from agent-authored cells. We delegate the fill to the
    deterministic engine (:func:`render_view`) and independently re-check that every
    displayed cell traces back to ``result_tables``.

    A degraded render (engine could not fill trustworthy numbers), a vacuous render
    (zero source-derived values to back the claim), or any displayed value absent
    from the source all fail the match. A chart-only view (a per-period series whose
    companion grid the engine suppressed) has no agent-authored numeric surface to
    re-verify — the engine plots the numbers straight from the source — so it passes
    by construction as long as a chart was actually produced. Never raises.
    """
    if getattr(rendered, "degraded", True):
        return False
    table_html = getattr(rendered, "table_html", None)
    if isinstance(table_html, str) and table_html:
        displayed = _TD_RE.findall(table_html)
        non_empty = [cell for cell in displayed if cell != ""]
        if not non_empty:
            return False  # nothing to value-match — backs its claim with no data
        source_cells = _source_cell_strings(view, result_tables)
        return all(cell in source_cells for cell in non_empty)
    # No table: a chart-only view fills its numbers deterministically from the source
    # (charts.render_chart_template), so it is trustworthy iff a chart was produced.
    chart_svg = getattr(rendered, "chart_svg", None)
    return isinstance(chart_svg, str) and bool(chart_svg)


def _check_one_view(
    view: object, section_id: object, idx: int, claim_ids: set[str],
    result_tables: dict, hard: list,
) -> None:
    """Apply rules 1-3 to a single curated view. Never raises."""
    label = _view_label(view, section_id, idx)

    # rule 3: supports_claim must reference a REAL claim in the bundle. Checked
    # independently of rule 1 so a structurally-valid view with a dangling claim
    # ref still fails distinctly. (An empty/missing supports_claim is rule 1's job.)
    sc = view.get("supports_claim") if isinstance(view, dict) else None
    if isinstance(sc, str) and sc.strip() and sc not in claim_ids:
        hard.append(_fail("VIEW_SUPPORTS_UNKNOWN_CLAIM", label,
                          f"supports_claim {sc!r} 不是 bundle 中的真实 claim_id"))

    # rule 1: structural validity against the real result.tables (refs real, columns
    # subset, no aggregation, supports_claim present, no invented digits in captions).
    errors = validate_view_spec(view, result_tables)
    if errors:
        hard.append(_fail("VIEW_SPEC_INVALID", label, "; ".join(errors)))
        return  # an invalid spec cannot be value-matched — stop here for this view

    # form guard (defense-in-depth): a table-template over a per-period series is a
    # wall-of-dates grid. HARD-fail with a dedicated code — clearer than the generic
    # VIEW_VALUE_MISMATCH the suppressed render would otherwise produce.
    if _is_timeseries_table_view(view, result_tables):
        hard.append(_fail("VIEW_TIMESERIES_AS_TABLE", label,
                          "逐期时间序列不应以表格呈现,请改用趋势图"))
        return

    # rule 2: value-match the engine's output against the source table.
    rendered = render_view(view, result_tables)
    if not _view_value_matches(rendered, view, result_tables):
        detail = getattr(rendered, "reason", None) or "显示数值无法与源表核对"
        hard.append(_fail("VIEW_VALUE_MISMATCH", label,
                          f"数值一致性核对失败:{detail}"))


def _check_curated_views(bundle: dict, result_tables: dict, hard: list) -> None:
    """Police every section's ``curated_views`` (rules 1-3). Never raises — a
    malformed section/view degrades to a hard failure or is skipped, but the gate
    still returns a report (the whole report must still produce its artifacts).

    There is no per-domain view cap: a section may carry as many curated views as it
    can back. Anti-dump is enforced per view (rules 1-3), not by a table/chart count."""
    claim_ids = _all_claim_ids(bundle)
    for section in bundle.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section_id = section.get("section_id")
        views = section.get("curated_views")

        if not isinstance(views, (list, tuple)):
            continue
        for idx, view in enumerate(views):
            try:
                _check_one_view(view, section_id, idx, claim_ids, result_tables, hard)
            except Exception:  # never-raise: a pathological view drops, gate survives
                hard.append(_fail("VIEW_SPEC_INVALID", _view_label(view, section_id, idx),
                                  "视图校验发生内部错误"))


def run_gate(bundle: dict, facts_json: dict, result_tables: dict | None = None) -> GateReport:
    """Validate + confidence-cap a narrative_bundle. Returns a new (capped) bundle.

    ``result_tables`` is the already-computed ``result.tables`` used to police each
    section's ``curated_views`` (the numeric-trust boundary). It defaults to ``{}``
    so existing 2-arg callers keep working; a bundle with no ``curated_views`` is
    unaffected.
    """
    bundle = copy.deepcopy(bundle)  # never mutate the caller's bundle
    result_tables = result_tables if isinstance(result_tables, dict) else {}
    facts = facts_json.get("facts") or {}
    registry = set(facts_json.get("entity_registry") or [])
    absent = set(facts_json.get("absent_link_registry") or [])
    absent_links = {a for a in absent if "->" in a}

    hard: list[dict] = []
    warnings: list[dict] = []
    capped: list[dict] = []

    backbone_ids = {b.get("link_id") for b in (bundle.get("spine_final") or {}).get("backbone") or []}
    entity_facts = {fid for fid, f in facts.items() if f.get("entity_type")}
    mechanism_facts: set[str] = set()

    for claim in _iter_claims(bundle):
        cid = claim.get("claim_id")
        _check_tokens(claim, facts, absent, hard)
        _check_pools(claim, facts, hard)
        _check_causal(claim, absent_links, hard)
        for ent in claim.get("entity_refs") or []:
            if ent not in registry:
                hard.append(_fail("INVENTED_ENTITY", cid, f"entity not in registry: {ent}"))
        if claim.get("claim_kind") == "mechanism":
            for tok in claim.get("number_tokens") or []:
                mechanism_facts.add(tok.get("fact_id"))
        # WARN: mechanism without a tag
        if claim.get("claim_kind") == "mechanism" and claim.get("confidence") not in _TAG_RANK:
            warnings.append(_fail("UNTAGGED_MECHANISM", cid, "mechanism claim missing 强/中/弱 tag"))
        # WARN: sizing without a caliber/assumption label on any anchor
        if claim.get("claim_kind") == "sizing":
            labelled = any((facts.get(t.get("fact_id")) or {}).get("assumption")
                           for t in claim.get("number_tokens") or [])
            if not labelled:
                warnings.append(_fail("UNLABELED_SIZING", cid, "sizing claim lacks caliber label"))
        # Confidence cap (deterministic; mechanism -> 弱, else <= strongest anchor)
        allowed = allowed_confidence_tag(claim, facts)
        stated = claim.get("confidence")
        if stated in _TAG_RANK and _TAG_RANK[stated] > _TAG_RANK[allowed]:
            claim["confidence"] = allowed
            capped.append({"claim_id": cid, "from": stated, "to": allowed})
            warnings.append(_fail("CONFIDENCE_CAPPED", cid, f"{stated} -> {allowed}"))

    # first_screen.actions: writer free-text with no token anchor — reject a fabricated
    # data magnitude (¥/%/万) that would otherwise reach the reader un-gated.
    for idx, action in enumerate((bundle.get("first_screen") or {}).get("actions") or []):
        if _ACTION_MAGNITUDE_RE.search(str(action)):
            hard.append(_fail("MAGNITUDE_UNBOUND", f"first_screen.action[{idx}]",
                              "action free-text carries an un-anchored ¥/%/万 magnitude"))

    # Cross-section: dangling callbacks + missing callbacks
    for section in bundle.get("sections") or []:
        callbacks = section.get("spine_callbacks") or []
        if not callbacks:
            warnings.append(_fail("MISSING_SPINE_CALLBACK", section.get("section_id"),
                                  "section connects to no spine link"))
        for link_id in callbacks:
            if link_id not in backbone_ids:
                hard.append(_fail("DANGLING_CALLBACK", section.get("section_id"),
                                  f"callback to unknown spine link {link_id}"))

    # WARN: mechanism fact available but never claimed as mechanism
    for fid in sorted(entity_facts - mechanism_facts):
        warnings.append(_fail("MISSED_MECHANISM", None,
                              f"entity fact {fid} has no mechanism claim"))

    # WARN: headline duplicates a section claim verbatim
    headline = str(bundle.get("headline") or "").strip()
    if headline:
        for claim in _iter_claims(bundle):
            if str(claim.get("sentence") or "").strip() == headline:
                warnings.append(_fail("REDUNDANT_HEADLINE", claim.get("claim_id"),
                                      "headline duplicates a section claim"))
                break

    # Curated-view policing (spec §Trust & anti-dump rules). Additive — every rule
    # above is preserved; view failures join the same hard-failure list.
    _check_curated_views(bundle, result_tables, hard)

    status = "FAIL" if hard else "PASS"
    return GateReport(status=status, hard_failures=hard, warnings=warnings,
                      capped_claims=capped, bundle=bundle)


def gate_report_to_json(report: GateReport) -> str:
    payload = {
        "status": report.status,
        "hard_failures": report.hard_failures,
        "warnings": report.warnings,
        "capped_claims": report.capped_claims,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2)
