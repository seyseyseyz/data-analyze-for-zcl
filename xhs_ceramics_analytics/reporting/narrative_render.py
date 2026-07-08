# xhs_ceramics_analytics/reporting/narrative_render.py
"""Deterministic narrative renderer — fills {tN}, applies continuity edits, freezes, skeletons.

Python owns rounding: ``fill_sentence`` copies ``fact.rendered`` verbatim into each
``{tN}`` slot with zero numeric derivation, so a fabricated number is unrepresentable.
``apply_continuity_edits`` lets the Continuity pass rewrite prose only — the digit and
``{tN}`` multisets of every edit are invariant (the shipped merchant_voice ``{…}``
contract, generalized). ``render_frozen`` re-gates at render time (tamper evidence).
``skeleton_markdown`` is the 0-agent floor reusing the existing compositor. Pure; the
edit/hash guards raise ValueError by design (callers treat them as gate failures).
"""
import copy
import re

from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.curated_view import render_view
from xhs_ceramics_analytics.reporting.factcheck_gate import (
    allowed_confidence_tag,
    run_gate,
)
from xhs_ceramics_analytics.reporting.first_screen import first_screen_markdown
from xhs_ceramics_analytics.reporting.html import (
    RAW_HTML_CLOSE,
    RAW_HTML_OPEN,
    render_markdown_document_html,
)
from xhs_ceramics_analytics.reporting.markdown import render_markdown

_TOKEN_RE = re.compile(r"\{t\d+\}")
_DIGIT_RE = re.compile(r"\d")
_SKELETON_BANNER = (
    "> **本报告为确定性骨架版：叙事层未通过事实校验，数字与表格仍完整可核。**"
)


def fill_sentence(sentence: str, number_tokens: list[dict], facts: dict) -> str:
    """Replace each {token_id} with facts[fact_id]['rendered']. No numeric derivation."""
    out = sentence
    for tok in number_tokens or []:
        fid = tok.get("fact_id")
        rendered = str((facts.get(fid) or {}).get("rendered", "—"))
        out = out.replace("{" + str(tok.get("token_id")) + "}", rendered)
    return out


def _all_claim_lists(bundle: dict):
    for section in bundle.get("sections") or []:
        yield section.get("claims") or []
    fs = bundle.get("first_screen") or {}
    for key in ("spine", "panel"):
        yield [c for c in (fs.get(key) or []) if isinstance(c, dict) and "sentence" in c]


def _claims_by_id(bundle: dict) -> dict[str, dict]:
    """Map claim_id → claim across the whole bundle (sections + first_screen).

    The index a curated view is badged against: its ``supports_claim`` resolves here
    so the confidence tag comes from the claim's trusted fact anchors, never from an
    agent-authored view field. Never raises."""
    index: dict[str, dict] = {}
    for claims in _all_claim_lists(bundle):
        for claim in claims or []:
            if isinstance(claim, dict):
                cid = claim.get("claim_id")
                if isinstance(cid, str) and cid:
                    index.setdefault(cid, claim)
    return index


def render_draft(bundle: dict, facts_json: dict) -> dict:
    """Return a new bundle where every claim carries a filled ``rendered_sentence``.

    An already-rendered sentence (e.g. one a Continuity pass polished before freezing)
    is preserved — it is only (re)filled when absent or still holding an unfilled {tN}.
    This lets a frozen bundle re-render at 0 LLM calls without reverting its edits.
    """
    bundle = copy.deepcopy(bundle)
    facts = facts_json.get("facts") or {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
            existing = str(claim.get("rendered_sentence") or "")
            if existing and not _TOKEN_RE.search(existing):
                continue  # already rendered (e.g. continuity-edited) — keep it verbatim
            claim["rendered_sentence"] = fill_sentence(
                str(claim.get("sentence") or ""), claim.get("number_tokens"), facts
            )
    return bundle


def _digit_multiset(text: str) -> list[str]:
    return sorted(_DIGIT_RE.findall(text))


def _token_multiset(text: str) -> list[str]:
    return sorted(_TOKEN_RE.findall(text))


def apply_continuity_edits(bundle: dict, edits: list[dict]) -> dict:
    """Apply prose-only edits. old must occur once; digits/{tN} invariant. Raises on violation."""
    bundle = copy.deepcopy(bundle)
    index: dict[str, dict] = {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
            index[claim.get("claim_id")] = claim
    for edit in edits or []:
        cid = edit.get("claim_id")
        claim = index.get(cid)
        if claim is None:
            raise ValueError(f"continuity edit for unknown claim_id {cid}")
        old, new = str(edit.get("old")), str(edit.get("new"))
        text = str(claim.get("rendered_sentence") or "")
        if text.count(old) != 1:
            raise ValueError(f"continuity 'old' must occur exactly once in claim {cid}")
        if _digit_multiset(old) != _digit_multiset(new):
            raise ValueError(f"continuity edit changes the digit multiset in claim {cid}")
        if _token_multiset(old) != _token_multiset(new):
            raise ValueError(f"continuity edit changes the {{tN}} multiset in claim {cid}")
        claim["rendered_sentence"] = text.replace(old, new)
    return bundle


def _rendered(claim: dict) -> str:
    return str(claim.get("rendered_sentence") or claim.get("sentence") or "").strip()


def bundle_to_markdown(
    bundle: dict,
    facts_json: dict,
    *,
    title: str | None = None,
    result_tables: dict | None = None,
) -> str:
    """Render the narrative bundle to markdown, inlining each section's curated views.

    ``result_tables`` is the already-computed ``result.tables`` the deterministic
    curated-view engine fills every displayed number from (the numeric-trust
    boundary). It defaults to ``{}`` so existing callers/tests keep working; with no
    tables the curated views are skipped and the report degrades to today's
    prose-only output. A single malformed/missing-table view drops silently — the
    report always renders.
    """
    tables = result_tables if isinstance(result_tables, dict) else {}
    claims_by_id = _claims_by_id(bundle)
    facts = facts_json.get("facts") if isinstance(facts_json, dict) else None
    facts = facts if isinstance(facts, dict) else {}
    parts: list[str] = []
    if title:
        parts.append(f"# {_strip_raw_html_markers(str(title))}")
    parts.append(_strip_raw_html_markers(first_screen_markdown(bundle)).rstrip())
    for section in bundle.get("sections") or []:
        heading = _strip_raw_html_markers(
            str(section.get("title") or section.get("section_id") or "").strip()
        )
        parts.append(f"## {heading}")
        for claim in section.get("claims") or []:
            sentence = _strip_raw_html_markers(_rendered(claim))
            if not sentence:
                continue
            conf = claim.get("confidence")
            parts.append(f"{sentence}（{conf}）" if conf else sentence)
        if tables:
            parts.extend(_curated_view_parts(section, tables, claims_by_id, facts))
    cannot = [
        s
        for s in (
            _strip_raw_html_markers(str(c).strip())
            for c in (bundle.get("cannot_say") or [])
        )
        if s
    ]
    if cannot:
        parts.append("## 暂时答不了的问题")
        parts.extend(f"- {c}" for c in cannot)
    return "\n\n".join(parts) + "\n"


class _EvidenceCarrier:
    """Minimal Finding-shim carrying only ``evidence_strength`` for
    :func:`curated_view.derive_confidence` — used to forward a deterministically
    resolved strength without pulling a full Finding into the render path."""

    __slots__ = ("evidence_strength",)

    def __init__(self, evidence_strength: object) -> None:
        self.evidence_strength = evidence_strength


# The gate tag a claim's anchors allow, mapped back to the EvidenceStrength that
# ``derive_confidence`` re-projects to the same tag (强↔STRONG, 中↔MEDIUM, 弱↔WEAK) —
# so the curated view's badge equals the gate's allowed tag with no agent input.
_TAG_TO_EVIDENCE: dict[str, EvidenceStrength] = {
    "强": EvidenceStrength.STRONG,
    "中": EvidenceStrength.MEDIUM,
    "弱": EvidenceStrength.WEAK,
}


def _finding_for_view(
    spec: object, claims_by_id: dict[str, dict], facts: dict
) -> object | None:
    """Resolve a view's confidence-bearing finding from its supporting claim's facts.

    Rule 5: confidence (强/中/弱) is derived deterministically from the FactBook —
    NEVER from an agent-authored field. We resolve the view's ``supports_claim`` to a
    real claim and take :func:`allowed_confidence_tag` (the same strongest-anchor tag
    the gate caps to). An agent-authored ``evidence_strength`` on the view spec is
    ignored, so it cannot forge a stronger badge than the evidence allows. A view with
    no resolvable claim degrades to the weakest tag (``None``). Never raises.
    """
    if not isinstance(spec, dict):
        return None
    claim = claims_by_id.get(str(spec.get("supports_claim") or ""))
    if not isinstance(claim, dict):
        return None
    tag = allowed_confidence_tag(claim, facts)
    return _EvidenceCarrier(_TAG_TO_EVIDENCE.get(tag, EvidenceStrength.WEAK))


def _curated_view_parts(
    section: object, result_tables: dict, claims_by_id: dict[str, dict], facts: dict
) -> list[str]:
    """Render one section's ``curated_views`` to inline markdown parts.

    Each passing view contributes: its title (a subheading), the deterministic table
    HTML and/or chart SVG (wrapped in raw-HTML passthrough markers so the narrative
    HTML converter emits them verbatim instead of escaping the angle brackets), the
    how_to_read caption, the why_it_matters hook, and the provenance stamp. A degraded
    view (bad spec / missing table / missing column) contributes nothing — the section
    keeps the prose rendered above it. Never raises: a pathological view is skipped.
    """
    if not isinstance(section, dict):
        return []
    views = section.get("curated_views")
    if not isinstance(views, (list, tuple)):
        return []
    parts: list[str] = []
    for spec in views:
        try:
            finding = _finding_for_view(spec, claims_by_id, facts)
            view = render_view(spec, result_tables, finding=finding)
        except Exception:  # never-raise: render_view is already defensive, stay so
            continue
        parts.extend(_single_view_parts(view))
    return parts


def _single_view_parts(view: object) -> list[str]:
    """Markdown parts for one rendered :class:`curated_view.CuratedView`. Empty when
    the view degraded or carries no renderable html — the section degrades silently."""
    if getattr(view, "degraded", True):
        return []
    table_html = getattr(view, "table_html", None) or None
    chart_svg = getattr(view, "chart_svg", None) or None
    if not table_html and not chart_svg:
        return []

    parts: list[str] = []
    # Every caption below is agent-authored prose and is marker-neutralized so it
    # cannot forge a raw-HTML passthrough sentinel (see _strip_raw_html_markers).
    # table_html / chart_svg are the DETERMINISTIC engine blocks and are the only
    # content allowed to carry real markers, added here by _raw_html_block.
    title = _strip_raw_html_markers(str(getattr(view, "title", "") or "").strip())
    if title:
        parts.append(f"### {title}")
    if table_html:
        parts.append(_raw_html_block(str(table_html)))
    if chart_svg:
        parts.append(_raw_html_block(str(chart_svg)))
    how_to_read = _strip_raw_html_markers(str(getattr(view, "how_to_read", "") or "").strip())
    if how_to_read:
        parts.append(how_to_read)
    why_it_matters = _strip_raw_html_markers(
        str(getattr(view, "why_it_matters", "") or "").strip()
    )
    if why_it_matters:
        parts.append(f"**{why_it_matters}**")
    provenance = _strip_raw_html_markers(str(getattr(view, "provenance", "") or "").strip())
    if provenance:
        parts.append(f"> {provenance}")
    return parts


def _strip_raw_html_markers(text: str) -> str:
    """Neutralize the raw-HTML passthrough sentinels in agent-authored prose.

    The narrative HTML converter (``reporting.html._markdown_document_body``) treats
    a standalone ``RAW_HTML_OPEN`` line as the start of an UNESCAPED verbatim block —
    the mechanism that inlines the deterministic curated table/chart HTML. Its only
    legitimate producer is :func:`_raw_html_block`. If any agent-authored string (a
    claim sentence, headline, caption, title, or cannot_say line) carried the marker,
    a forged line would flip the converter into passthrough and let a following
    ``<script>`` — or a fabricated number — ship raw, an XSS bypass and a breach of
    the numeric-trust boundary. Removing the marker tokens from all agent prose makes
    the sentinels non-forgeable: the only markers reaching the transport are the ones
    :func:`_raw_html_block` wraps around engine HTML. Never raises.
    """
    return str(text).replace(RAW_HTML_OPEN, "").replace(RAW_HTML_CLOSE, "")


def _raw_html_block(html: str) -> str:
    """Wrap already-safe deterministic HTML so the narrative HTML converter passes it
    through verbatim (see reporting.html.RAW_HTML_OPEN)."""
    return f"{RAW_HTML_OPEN}\n{html}\n{RAW_HTML_CLOSE}"


def render_frozen(frozen: dict, facts_json: dict) -> tuple[str, str]:
    """Render (md, html) from a frozen narrative. Re-gates + checks facts_hash (tamper evidence)."""
    if frozen.get("facts_hash") != facts_json.get("facts_hash"):
        raise ValueError("frozen facts_hash does not match the supplied facts.json")
    bundle = frozen.get("narrative_bundle") or {}
    report = run_gate(bundle, facts_json)
    if report.status != "PASS":
        raise ValueError(f"frozen narrative fails the render-time gate: {report.hard_failures}")
    drafted = render_draft(report.bundle, facts_json)
    md = bundle_to_markdown(drafted, facts_json)
    html = render_markdown_document_html(md)
    return md, html


def skeleton_markdown(results, *, title: str | None = None) -> str:
    """Deterministic 0-agent floor: banner + the existing compositor's markdown."""
    body = render_markdown(results, title=title)
    return f"{_SKELETON_BANNER}\n\n{body}"
