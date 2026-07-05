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

from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
from xhs_ceramics_analytics.reporting.first_screen import first_screen_markdown
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
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


def render_draft(bundle: dict, facts_json: dict) -> dict:
    """Return a new bundle where every claim carries a filled ``rendered_sentence``."""
    bundle = copy.deepcopy(bundle)
    facts = facts_json.get("facts") or {}
    for claims in _all_claim_lists(bundle):
        for claim in claims:
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


def bundle_to_markdown(bundle: dict, facts_json: dict, *, title: str | None = None) -> str:
    parts: list[str] = []
    if title:
        parts.append(f"# {title}")
    parts.append(first_screen_markdown(bundle).rstrip())
    for section in bundle.get("sections") or []:
        heading = str(section.get("title") or section.get("section_id") or "").strip()
        parts.append(f"## {heading}")
        for claim in section.get("claims") or []:
            sentence = _rendered(claim)
            if not sentence:
                continue
            conf = claim.get("confidence")
            parts.append(f"{sentence}（{conf}）" if conf else sentence)
    cannot = [str(c).strip() for c in (bundle.get("cannot_say") or []) if str(c).strip()]
    if cannot:
        parts.append("## 暂时答不了的问题")
        parts.extend(f"- {c}" for c in cannot)
    return "\n\n".join(parts) + "\n"


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
