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
    # table cells filled from the source table, formatted via the shared fact-layer
    # formatter (money columns get thousands separators; never a raw dump/fabrication)
    assert "<td>转化</td>" in md
    assert "<td>12,000</td>" in md
    assert "<td>8,000</td>" in md
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
    assert "12,000" in html


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


def test_provenance_confidence_derived_from_supporting_claim_facts():
    # Rule 5: the badge (强/中/弱) is derived from the supporting CLAIM's fact anchors
    # in the trusted FactBook — the same strength the gate would allow — never from an
    # agent-authored view field.
    facts = _facts()
    facts["facts"] = {"m.gmv": {"evidence_strength": "strong", "descriptive_reliability": "high"}}
    claim = {**_claim(), "number_tokens": [{"token_id": "t0", "fact_id": "m.gmv"}]}
    b = _bundle([_table_view()])  # the view carries NO evidence_strength
    b["sections"][0]["claims"] = [claim]
    md = nr.bundle_to_markdown(b, facts, result_tables=_tables())
    assert "证据:强" in md


def test_view_evidence_strength_field_cannot_forge_a_stronger_badge():
    # F2: an agent stamping evidence_strength="strong" on the view spec must NOT lift
    # the badge above what the supporting claim's WEAK fact anchor allows.
    facts = _facts()
    facts["facts"] = {"m.gmv": {"evidence_strength": "weak", "descriptive_reliability": "low"}}
    claim = {**_claim(), "number_tokens": [{"token_id": "t0", "fact_id": "m.gmv"}]}
    b = _bundle([_table_view(evidence_strength="strong")])  # forgery attempt
    b["sections"][0]["claims"] = [claim]
    md = nr.bundle_to_markdown(b, facts, result_tables=_tables())
    assert "证据:弱" in md
    assert "证据:强" not in md


def test_view_supports_unresolvable_claim_degrades_to_weak():
    # No claim to anchor the badge → degrade to the weakest tag, even if the agent
    # stamped a strong evidence_strength on the view.
    b = _bundle([_table_view(supports_claim="nope", evidence_strength="strong")])
    md = nr.bundle_to_markdown(b, _facts(), result_tables=_tables())
    assert "证据:弱" in md
    assert "证据:强" not in md


def test_garbage_curated_views_never_raise():
    for views in (None, "garbage", 42, [None, 7, {}], [{"template": "pie_3d"}]):
        b = _bundle([])
        b["sections"][0]["curated_views"] = views
        md = nr.bundle_to_markdown(b, _facts(), result_tables=_tables())
        # prose always survives; a pathological view never blocks the report
        assert "GMV 回落。" in md


# ---- raw-HTML passthrough sentinel is non-forgeable by agent prose --------
#
# The narrative HTML converter treats a standalone ``<!--raw-html-->`` line as the
# start of an UNESCAPED verbatim block (used to inline the deterministic curated
# table/chart HTML). The ONLY legitimate producer is ``_raw_html_block``; if any
# agent-authored string could carry the marker, a forged line would flip the
# converter into passthrough and let a following ``<script>`` (or a fabricated
# number) ship raw — an XSS bypass and a numeric-trust breach.

def test_forged_marker_in_how_to_read_cannot_open_passthrough():
    # A curated view whose how_to_read forges the open marker must not turn its
    # own why_it_matters <script> into live, unescaped HTML.
    attack = _table_view(
        how_to_read=nr.RAW_HTML_OPEN,
        why_it_matters="<script>xss</script>",
    )
    md = nr.bundle_to_markdown(_bundle([attack]), _facts(), result_tables=_tables())
    html = render_markdown_document_html(md)
    # the script is escaped, never executable
    assert "<script>xss</script>" not in html
    assert "&lt;script&gt;xss" in html
    # the fix did not over-strip: the legit deterministic table still passed through
    assert "<table>" in html
    assert "12,000" in html


def test_forged_marker_in_claim_sentence_cannot_open_passthrough():
    # A bare claim (no confidence tag) whose sentence equals the open marker must
    # not flip a following claim's <script> into unescaped passthrough.
    forged = {**_claim(), "claim_id": "cf", "confidence": None,
              "rendered_sentence": nr.RAW_HTML_OPEN}
    payload = {**_claim(), "claim_id": "cp", "confidence": None,
               "rendered_sentence": "<script>xss</script>"}
    b = _bundle([])
    b["sections"][0]["claims"] = [forged, payload]
    md = nr.bundle_to_markdown(b, _facts(), result_tables=_tables())
    html = render_markdown_document_html(md)
    assert "<script>xss</script>" not in html
    assert "&lt;script&gt;xss" in html


def test_agent_markers_stripped_from_every_field_only_engine_block_remains():
    # Stuff the sentinels into every agent-authored surface; after rendering, the
    # ONLY raw-HTML markers left must be the single legit engine table block, so no
    # forged (standalone or inline) marker can survive into the .md transport.
    view = _table_view(
        title=f"标题{nr.RAW_HTML_OPEN}",
        how_to_read=nr.RAW_HTML_OPEN,
        why_it_matters=f"钩子{nr.RAW_HTML_CLOSE}",
    )
    b = _bundle([view])
    b["headline"] = f"大标题{nr.RAW_HTML_OPEN}"
    b["sections"][0]["title"] = f"生意大盘{nr.RAW_HTML_CLOSE}"
    b["sections"][0]["claims"] = [
        {**_claim(), "confidence": None, "rendered_sentence": nr.RAW_HTML_OPEN}
    ]
    b["cannot_say"] = [f"疑问{nr.RAW_HTML_OPEN}"]
    md = nr.bundle_to_markdown(b, _facts(), title=f"报告{nr.RAW_HTML_CLOSE}",
                               result_tables=_tables())
    # exactly one legit engine block (a ranking_table view → one table, no chart)
    assert md.count(nr.RAW_HTML_OPEN) == 1
    assert md.count(nr.RAW_HTML_CLOSE) == 1
    # and that lone block still round-trips through the converter as a real table
    html = render_markdown_document_html(md)
    assert "<table>" in html
    assert "12,000" in html


# ---- deterministic per-domain chart fallback -------------------------------
#
# The narrative shipped prose-only (curated_views all empty) yet finalized as a
# success. The renderer must guarantee charts: when a CORE domain section produced
# ZERO chart-template curated views but the fact layer has a chartable table for that
# domain, a deterministic chart is auto-injected from the source table cells (numbers
# never authored by prose). An agent-authored chart suppresses the fallback (no double
# render); a non-core domain / thin data degrades silently to prose-only.

def _core_tables():
    # Tables the per-domain fallback knows how to chart. Numbers live ONLY here, so a
    # value in the output proves it came from the source table, never from prose.
    return {
        "business_trend": [
            {"date": "2026-04-01", "gmv": 14356.0},
            {"date": "2026-04-02", "gmv": 22687.0},
        ],
        "channel_scale": [
            {"carrier_zh": "商品卡", "gmv_share": 0.6445},
            {"carrier_zh": "笔记", "gmv_share": 0.3555},
        ],
    }


def _prose_only_bundle(domain_title):
    # A domain section with prose but ZERO curated views — the exact real-run failure.
    return {
        "facts_hash": "h",
        "headline": "标题。",
        "first_screen": {"spine": [], "panel": [], "actions": []},
        "sections": [
            {"section_id": "s", "title": domain_title,
             "claims": [_claim()], "curated_views": []}
        ],
        "cannot_say": [],
    }


def test_fallback_injects_chart_when_section_has_no_curated_chart():
    md = nr.bundle_to_markdown(
        _prose_only_bundle("生意大盘"), _facts(), result_tables=_core_tables()
    )
    assert "GMV 回落。" in md            # prose preserved
    assert nr.RAW_HTML_OPEN in md         # deterministic passthrough block emitted
    assert "<svg" in md                   # a chart was auto-injected
    assert "GMV 走势" in md               # the fallback title
    html = render_markdown_document_html(md)
    assert "<svg" in html and "&lt;svg" not in html   # survives md→HTML unescaped


def test_fallback_numbers_come_from_source_table_cells():
    md = nr.bundle_to_markdown(
        _prose_only_bundle("流量与内容"), _facts(), result_tables=_core_tables()
    )
    assert "<svg" in md
    assert "商品卡" in md      # category label from the source cell
    assert "0.64" in md        # value formatted from the source cell (0.6445 → 0.64)


def test_fallback_suppressed_when_curated_chart_present_no_double_render():
    # The section already has an agent chart (waterfall on growth_bridge); a mapped
    # table (business_trend) is also present — the fallback must NOT add a 2nd chart.
    tables = {**_tables(), **_core_tables()}
    md = nr.bundle_to_markdown(_bundle([_chart_view()]), _facts(), result_tables=tables)
    assert md.count("<svg") == 1     # exactly the curated chart, no fallback
    assert "GMV 走势" not in md       # the fallback title never appears
    assert "GMV 瀑布" in md           # the curated chart is what rendered


def test_fallback_only_for_mapped_core_domains():
    # a non-core domain title has no fallback mapping → prose-only, no chart
    md = nr.bundle_to_markdown(
        _prose_only_bundle("实验与下周行动"), _facts(), result_tables=_core_tables()
    )
    assert "GMV 回落。" in md
    assert "<svg" not in md


def test_fallback_never_raises_on_garbage_tables():
    for tables in ({"business_trend": "notalist"},
                   {"business_trend": [None, 7]},
                   {"business_trend": []},
                   {"channel_scale": [{"wrong": 1}]}):
        md = nr.bundle_to_markdown(
            _prose_only_bundle("生意大盘"), _facts(), result_tables=tables
        )
        assert "GMV 回落。" in md   # prose always survives; fallback degrades silently


def test_has_chartable_tables_detects_mapped_nonempty_tables():
    assert nr.has_chartable_tables(_core_tables()) is True
    assert nr.has_chartable_tables({"growth_bridge": [{"a": 1}]}) is False  # not mapped
    assert nr.has_chartable_tables({"business_trend": []}) is False          # empty
    for bad in (None, "x", 42, {"business_trend": "nope"}):
        assert nr.has_chartable_tables(bad) is False
