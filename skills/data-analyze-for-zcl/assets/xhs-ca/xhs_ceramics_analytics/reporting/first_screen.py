# xhs_ceramics_analytics/reporting/first_screen.py
"""Assemble the section-0 首屏导读 (headline + 因果主线 + 盘面 + 本周重点).

Content-driven length: a block with no qualifying content emits no heading — the
首屏 is an引子, never padded to a fixed three-line template nor truncated to fit one.
Consumes claims whose ``rendered_sentence`` is already filled by narrative_render.
Pure, never raises.
"""


def _lines(claims: list[dict], *, tag: bool) -> list[str]:
    out: list[str] = []
    for claim in claims or []:
        sentence = str(claim.get("rendered_sentence") or claim.get("sentence") or "").strip()
        if not sentence:
            continue
        conf = claim.get("confidence")
        if tag and conf:
            sentence = f"{sentence}（{conf}）"
        out.append(f"- {sentence}")
    return out


def first_screen_markdown(bundle: dict) -> str:
    fs = (bundle or {}).get("first_screen") or {}
    parts: list[str] = ["## 首屏导读"]
    headline = str((bundle or {}).get("headline") or "").strip()
    if headline:
        parts.append(f"**{headline}**")

    spine = _lines(fs.get("spine"), tag=True)
    if spine:
        parts.append("**因果主线**")
        parts.extend(spine)

    panel = _lines(fs.get("panel"), tag=True)
    if panel:
        parts.append("**盘面**")
        parts.extend(panel)

    actions = [str(a).strip() for a in (fs.get("actions") or []) if str(a).strip()]
    if actions:
        parts.append("**本周重点**")
        parts.extend(f"- {a}" for a in actions)

    return "\n\n".join(parts) + "\n"
