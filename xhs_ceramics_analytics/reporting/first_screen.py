# xhs_ceramics_analytics/reporting/first_screen.py
"""Assemble the section-0 首屏导读 (headline + 因果主线 + 盘面 + 本周重点).

Content-driven length: a block with no qualifying content emits no heading — the
首屏 is an引子, never padded to a fixed three-line template nor truncated to fit one.
Consumes claims whose ``rendered_sentence`` is already filled by narrative_render.
Pure, never raises.
"""


def normalize_line(text: object) -> str:
    """Canonical form for verbatim-duplicate detection: drop surrounding ``**`` bold,
    strip, and collapse internal whitespace. Shared with narrative_render so the headline
    is recognized as the same sentence wherever it is echoed (#8). Never raises."""
    s = str(text or "").strip()
    if len(s) >= 4 and s.startswith("**") and s.endswith("**"):
        s = s[2:-2].strip()
    return " ".join(s.split())


def _lines(claims: list[dict], skip: set[str] = frozenset()) -> list[str]:
    # No per-line confidence suffix: the 首屏 is an 引子, and confidence now lives on a
    # per-section pill in the body (see narrative_render._section_confidence). Suffixing
    # every teaser line with （强/中/弱）was the "每条结论后跟个弱" repetition. A line whose
    # normalized text is in ``skip`` (the headline) is dropped so the hook shows once (#8).
    out: list[str] = []
    for claim in claims or []:
        sentence = str(claim.get("rendered_sentence") or claim.get("sentence") or "").strip()
        if not sentence:
            continue
        if normalize_line(sentence) in skip:
            continue
        out.append(f"- {sentence}")
    return out


def first_screen_markdown(bundle: dict) -> str:
    fs = (bundle or {}).get("first_screen") or {}
    parts: list[str] = ["## 首屏导读"]
    headline = str((bundle or {}).get("headline") or "").strip()
    # The headline shows once as the bold hook; a spine/panel teaser that restates it
    # verbatim is dropped (#8).
    skip = {normalize_line(headline)} if headline else set()
    if headline:
        parts.append(f"**{headline}**")

    spine = _lines(fs.get("spine"), skip)
    if spine:
        parts.append("**因果主线**")
        parts.extend(spine)

    panel = _lines(fs.get("panel"), skip)
    if panel:
        parts.append("**盘面**")
        parts.extend(panel)

    actions = [str(a).strip() for a in (fs.get("actions") or []) if str(a).strip()]
    if actions:
        parts.append("**本周重点**")
        parts.extend(f"- {a}" for a in actions)

    return "\n\n".join(parts) + "\n"
