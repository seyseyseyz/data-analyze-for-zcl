# xhs_ceramics_analytics/reporting/confidence_pill.py
"""Per-section confidence pill — one evidence chip per section, not per sentence.

The narrative used to suffix every claim with （强/中/弱）; the merchant complaint was
"每条结论后跟个弱" — the tag repeated after every line, mostly reading 弱, which buried
the prose in de-emphasis. D2 shows the confidence ONCE per section as a small pill,
using the SAME tier tokens and ``.tag`` markup as the fact-layer report
(``templates/report.html.j2``) so the two report layers read as one design language.

:func:`confidence_pill_html` builds the deterministic ``<span>`` (never agent-authored);
:data:`CONFIDENCE_PILL_STYLE` is the self-contained CSS injected into the narrative
document's single ``<style>`` — its own ``:root`` tier tokens, no external refs, no
script — so the single-file HTML deliverable stays URL-free and self-contained. Pure;
never raises.
"""

# Narrative confidence tag → fact-layer ``.tag`` tier class. 强/中 collapse to the
# green (usable) tier and 弱 to the neutral (directional) tier exactly as
# report.html.j2 does (high/medium/strong→green, low/weak→neutral) — mirrored here so
# the pill matches the fact layer instead of inventing a second visual language.
_PILL_CLASS: dict[str, str] = {"强": "strong", "中": "medium", "弱": "weak"}


def confidence_pill_html(tag: object) -> str:
    """Return the deterministic pill ``<span>`` for a confidence tag, or ``""`` for
    anything unknown. The label is ``证据 {tag}`` — the same "证据" wording the per-view
    provenance stamp uses, so the section pill and the view stamps read consistently.
    Never raises."""
    cls = _PILL_CLASS.get(tag) if isinstance(tag, str) else None
    if not cls:
        return ""
    return f'<span class="tag {cls}">证据 {tag}</span>'


# Self-contained tier tokens + ``.tag`` rules mirroring report.html.j2 (§:root tier
# tokens + §.tag). Kept as its own ``:root`` so the narrative ``<style>`` needs no other
# edit — CSS merges multiple ``:root`` blocks. Green = usable (strong/medium), neutral =
# directional (weak): calm grey, never alarm-yellow, matching the fact layer's intent.
CONFIDENCE_PILL_STYLE = """
    :root {
      --green-bg: #EDF3EC;
      --green-text: #346538;
      --neutral-bg: #F1F1EF;
      --neutral-text: #787774;
    }
    .tag {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      border-radius: 9999px;
      padding: 5px 11px;
      margin: 4px 0 2px;
      font-size: 11px;
      line-height: 1;
      letter-spacing: 0.04em;
      font-family: 'Geist Mono', 'SF Mono', monospace;
      font-weight: 700;
    }
    .tag.strong,
    .tag.medium { background: var(--green-bg); color: var(--green-text); }
    .tag.weak { background: var(--neutral-bg); color: var(--neutral-text); }
"""
