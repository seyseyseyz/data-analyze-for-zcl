"""Tests for the per-section confidence pill (its span builder + self-contained CSS).

The narrative used to suffix every single sentence with （强/中/弱） — the merchant
complaint "每条结论后跟个弱": the tag repeated after every line, mostly reading 弱,
burying the prose. D2 shows the confidence ONCE per section as a small pill, using the
SAME tier tokens/`.tag` markup as the fact-layer report (templates/report.html.j2) so
the two layers read as one design language. The span is deterministic (never
agent-authored); the CSS is self-contained (own :root, no external refs, no script) so
the single-file HTML deliverable stays URL-free.
"""
import re

from xhs_ceramics_analytics.reporting.confidence_pill import (
    CONFIDENCE_PILL_STYLE,
    confidence_pill_html,
)


# ---- the pill span builder -------------------------------------------------

def test_pill_maps_each_tier_to_its_fact_layer_class():
    assert confidence_pill_html("强") == '<span class="tag strong">证据 强</span>'
    assert confidence_pill_html("中") == '<span class="tag medium">证据 中</span>'
    assert confidence_pill_html("弱") == '<span class="tag weak">证据 弱</span>'


def test_pill_degrades_to_empty_on_unknown_tag():
    for bad in (None, "", "高", 3, "strong", "STRONG"):
        assert confidence_pill_html(bad) == ""


# ---- the CSS is pure, self-contained, single-file-safe --------------------

def test_pill_style_is_pure_css_no_script_or_external_refs():
    lowered = CONFIDENCE_PILL_STYLE.lower()
    assert "<script" not in lowered
    assert "http://" not in lowered and "https://" not in lowered
    assert "url(" not in lowered  # no external asset fetch


def test_pill_style_defines_every_tier_token_it_references():
    used = set(re.findall(r"var\((--[a-z-]+)\)", CONFIDENCE_PILL_STYLE))
    defined = set(re.findall(r"(--[a-z-]+)\s*:", CONFIDENCE_PILL_STYLE))
    assert used  # it does reference tier tokens
    assert used <= defined  # ...and defines all of them itself (self-contained)


def test_pill_style_styles_the_tag_base_and_all_three_tiers():
    for selector in (".tag", ".tag.strong", ".tag.medium", ".tag.weak"):
        assert selector in CONFIDENCE_PILL_STYLE
