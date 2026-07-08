"""Shared chart/curated-view CSS for the narrative report (reporting.chart_style).

The narrative document (``render_markdown_document_html``) auto-injects charts
(``<svg class="chart-svg">`` via ``render_chart_template``) and curated tables
(``.ca-table-fold`` folds + ``.ca-row-highlight`` rows), but its ``<style>``
historically styled NONE of those classes — so axis/grid strokes were invisible,
category/number text was unsized default-black, and the top-N fold + highlighted
row had no styling. ``CHART_STYLE`` is the single shared string that fixes this,
mirroring the fact report's chart look, safe to inject into the narrative
``<style>`` because it references ONLY design tokens the narrative already defines.
"""
from xhs_ceramics_analytics.reporting.chart_style import CHART_STYLE
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html


def test_chart_style_is_pure_css_no_script_or_external_refs():
    # Single-file HTML contract: no <script>, no network, no hardcoded hex — the
    # chart CSS must lean on the shared design tokens, exactly like TOC_STYLE.
    assert "<script" not in CHART_STYLE
    assert "http://" not in CHART_STYLE and "https://" not in CHART_STYLE
    assert "src=" not in CHART_STYLE
    assert "url(" not in CHART_STYLE  # no external asset() / image refs
    assert "var(--line)" in CHART_STYLE and "var(--muted)" in CHART_STYLE


def test_chart_style_styles_every_class_the_narrative_emits():
    # The classes the narrative render path actually emits (chart SVG descendants,
    # the top-N <details> fold, the highlighted row) must all be styled.
    for token in (
        ".chart-svg",
        ".ca-cat",
        ".ca-num",
        ".ca-axis",
        ".ca-grid",
        ".ca-empty",
        ".ca-table-fold",
        ".ca-row-highlight",
    ):
        assert token in CHART_STYLE, f"CHART_STYLE is missing a rule for {token}"


def test_chart_style_references_only_tokens_the_narrative_root_defines():
    # The narrative :root defines exactly these tokens; the chart CSS must not
    # reference a var the narrative never sets (that would render unstyled).
    import re

    narrative_root = {
        "--canvas", "--surface", "--ink", "--ink-strong",
        "--muted", "--line", "--yellow-bg", "--yellow-text",
    }
    used = set(re.findall(r"var\((--[a-z-]+)\)", CHART_STYLE))
    assert used <= narrative_root, f"CHART_STYLE uses undefined tokens: {used - narrative_root}"


def test_narrative_html_injects_chart_css():
    html = render_markdown_document_html("# T\n\n## 一\n\n正文。\n")
    # the chart + fold + row styling ships in every narrative document's <style>
    assert ".chart-svg" in html
    assert ".ca-table-fold" in html
    assert ".ca-row-highlight" in html
    # a hairline axis stroke is now defined (was invisible before)
    assert ".ca-axis" in html and "stroke: var(--line)" in html
    # still single-file: no script injected alongside the CSS
    assert "<script" not in html
