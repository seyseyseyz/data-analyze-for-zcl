"""Render-wiring tests: bundle_to_markdown inlines a section's curated_views.

This closes the missing pipe (spec §Problem/§Architecture): the narrative renderer
consumed only prose and never rendered ``section.curated_views``. Here we assert the
deterministic curated table/chart HTML actually lands in ``<name>.md`` AND survives the
narrative markdown→HTML conversion (raw ``<table>``/``<svg`` NOT escaped), while an
empty ``result_tables`` degrades cleanly to today's prose-only output.

Numbers live only in the ``result_tables`` fixture; the engine surfaces them verbatim,
so a value appearing in the output proves it came from the source, never from prose.
"""
from xhs_ceramics_analytics.reporting import narrative_render as nr
from xhs_ceramics_analytics.reporting.html import render_markdown_document_html


# ---- fixtures -------------------------------------------------------------

def _facts():
    return {
        "facts_hash": "h",
        "facts": {},
        "entity_registry": [],
        "absent_link_registry": [],
        "non_additive_ledger": {},
    }


def _tables():
    # Numbers live ONLY here; the engine must surface them verbatim into the view.
    return {
        "growth_bridge": [
            {"component": "转化", "delta_gmv": 12000, "note": "a"},
            {"component": "流量", "delta_gmv": 8000, "note": "b"},
            {"component": "客单价", "delta_gmv": -3000, "note": "c"},
        ]
    }


def _table_view(**overrides):
    v = {
        "view_id": "core.gmv_bridge_table",
        "section_id": "core_business",
        "supports_claim": "c0",
        "template": "ranking_table",
        "source": {"task_id": "core_business_diagnosis", "table": "growth_bridge"},
        "columns": ["component", "delta_gmv"],
        "column_labels": {"component": "增长来源", "delta_gmv": "对GMV的拉动"},
        "rows": {"sort_by": "delta_gmv", "order": "desc"},
        "title": "GMV 增长拆解",
        "how_to_read": "越靠上影响越大",
        "why_it_matters": "锁定被抵消的那一块",
    }
    v.update(overrides)
    return v


def _chart_view(**overrides):
    v = _table_view(
        view_id="core.gmv_bridge_chart",
        template="breakdown_waterfall",
        chart={"x": "component", "y": "delta_gmv"},
        title="GMV 瀑布",
        how_to_read="向右为拉动、向左为抵消",
        why_it_matters="看谁在抵消",
    )
    v.update(overrides)
    return v


def _claim():
    return {
        "claim_id": "c0",
        "section_id": "core_business",
        "claim_kind": "measurement",
        "sentence": "GMV 回落。",
        "rendered_sentence": "GMV 回落。",
        "number_tokens": [],
        "entity_refs": [],
        "confidence": "强",
        "causal_link": None,
    }


def _bundle(views):
    return {
        "facts_hash": "h",
        "headline": "标题。",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "sections": [
            {
                "section_id": "core_business",
                "title": "生意大盘",
                "claims": [_claim()],
                "curated_views": views,
            }
        ],
        "cannot_say": [],
    }


# ---- the missing pipe: curated views render inline in the markdown --------

def test_bundle_to_markdown_renders_curated_view_tables_and_charts():
    md = nr.bundle_to_markdown(
        _bundle([_table_view(), _chart_view()]), _facts(), result_tables=_tables()
    )
    # prose survives unchanged
    assert "GMV 回落。" in md
    assert "生意大盘" in md
    # table cells surfaced verbatim from the source table (no fabrication, no rounding)
    assert "<td>转化</td>" in md
    assert "<td>12000</td>" in md
    assert "<td>8000</td>" in md
    # the unselected `note` column never leaks
    assert "<td>a</td>" not in md
    # chart template inlined as SVG
    assert "<svg" in md
    # curated view titles, captions and the interpretive hook are rendered
    assert "GMV 增长拆解" in md
    assert "越靠上影响越大" in md
    assert "锁定被抵消的那一块" in md
    # provenance stamp footer
    assert "来源:core_business_diagnosis · growth_bridge · 证据:" in md


def test_html_conversion_preserves_raw_table_and_svg_not_escaped():
    md = nr.bundle_to_markdown(
        _bundle([_table_view(), _chart_view()]), _facts(), result_tables=_tables()
    )
    html = render_markdown_document_html(md)
    # the raw curated HTML/SVG passes through verbatim — the whole point of the fix
    assert "<table>" in html
    assert "<svg" in html
    # and is NOT escaped into visible source
    assert "&lt;table" not in html
    assert "&lt;svg" not in html
    # the source-derived cell value survived into the HTML document
    assert "12000" in html


def test_empty_result_tables_degrades_to_prose_only():
    md = nr.bundle_to_markdown(
        _bundle([_table_view(), _chart_view()]), _facts(), result_tables={}
    )
    # prose intact
    assert "GMV 回落。" in md
    assert "生意大盘" in md
    # no curated tables/charts when there are no source tables to trust
    assert "<td>" not in md
    assert "<svg" not in md


def test_default_signature_skips_curated_views_backward_compatible():
    # Existing callers pass (bundle, facts[, title]) with no result_tables; behaviour
    # must be exactly today's prose-only output.
    md = nr.bundle_to_markdown(_bundle([_table_view()]), _facts(), title="报告")
    assert "# 报告" in md
    assert "GMV 回落。" in md
    assert "<td>" not in md


def test_degraded_view_is_skipped_report_still_renders():
    bad = _table_view(source={"task_id": "x", "table": "does_not_exist"})
    md = nr.bundle_to_markdown(
        _bundle([bad, _table_view()]), _facts(), result_tables=_tables()
    )
    # the good view still renders; the bad one is silently dropped (never raises)
    assert "<td>转化</td>" in md
    assert "GMV 回落。" in md


def test_provenance_confidence_derived_from_view_evidence_strength():
    # Confidence (强/中/弱) is derived deterministically from the source Finding's
    # evidence_strength (forwarded on the view), never authored by the agent.
    md = nr.bundle_to_markdown(
        _bundle([_table_view(evidence_strength="strong")]),
        _facts(),
        result_tables=_tables(),
    )
    assert "证据:强" in md


def test_garbage_curated_views_never_raise():
    for views in (None, "garbage", 42, [None, 7, {}], [{"template": "pie_3d"}]):
        b = _bundle([])
        b["sections"][0]["curated_views"] = views
        md = nr.bundle_to_markdown(b, _facts(), result_tables=_tables())
        # prose always survives; a pathological view never blocks the report
        assert "GMV 回落。" in md
