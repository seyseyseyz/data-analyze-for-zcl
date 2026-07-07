"""Tests for the deterministic curated-view executor (curated_view.render_view).

The curation agent emits only a declarative view-spec (template + column/row
selection + prose captions, NO numeric values). This engine fills every displayed
number from the REAL rows of ``result.tables`` — verbatim, never fabricated or
re-rounded. Contract: every rendered cell equals the source value, chart SVG is
byte-stable, sort/TopN/highlight are honored, and any malformed spec / missing
table / missing column degrades to a no-html result WITHOUT raising.
"""
from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting.curated_view import CuratedView, render_view


# ---- fixtures -------------------------------------------------------------

def _tables():
    # Numbers live only here; the engine must surface them verbatim.
    return {
        "growth_bridge": [
            {"component": "转化", "delta_gmv": 12000, "note": "a"},
            {"component": "流量", "delta_gmv": 8000, "note": "b"},
            {"component": "客单价", "delta_gmv": -3000, "note": "c"},
        ]
    }


def _table_spec(**overrides):
    spec = {
        "view_id": "core.gmv_bridge_table",
        "section_id": "core_business",
        "supports_claim": "core.gmv_bridge",
        "template": "ranking_table",
        "source": {"task_id": "core_business_diagnosis", "table": "growth_bridge"},
        "columns": ["component", "delta_gmv"],
        "column_labels": {"component": "增长来源", "delta_gmv": "对GMV的拉动"},
        "rows": {},
        "title": "GMV 增长拆解:谁在拉动、谁在抵消",
        "how_to_read": "越靠上影响越大",
        "why_it_matters": "锁定被转化抵消的那一块",
    }
    spec.update(overrides)
    return spec


def _chart_spec(**overrides):
    spec = _table_spec(
        view_id="core.gmv_bridge_chart",
        template="breakdown_waterfall",
        chart={"x": "component", "y": "delta_gmv"},
    )
    spec.update(overrides)
    return spec


def _finding(strength=EvidenceStrength.MEDIUM):
    return Finding(title="t", conclusion="c", evidence_strength=strength)


# ---- every rendered cell equals the source value (verbatim) ---------------

def test_table_cells_equal_source_value_verbatim():
    view = render_view(_table_spec(), _tables(), finding=_finding())
    assert not view.degraded
    assert view.chart_svg is None  # a table template renders no chart
    html = view.table_html
    # every selected cell is present verbatim — no re-rounding, no fabrication.
    for cell in ("<td>转化</td>", "<td>12000</td>",
                 "<td>流量</td>", "<td>8000</td>",
                 "<td>客单价</td>", "<td>-3000</td>"):
        assert cell in html
    # the unselected `note` column is not surfaced.
    assert "<td>a</td>" not in html


def test_engine_never_invents_a_number_absent_from_source():
    view = render_view(_table_spec(), _tables(), finding=_finding())
    # 9000 is a plausible but fabricated value — it must never appear.
    assert "9000" not in view.table_html


def test_column_labels_become_headers_source_names_do_not_leak():
    view = render_view(_table_spec(), _tables(), finding=_finding())
    assert "<th>增长来源</th>" in view.table_html
    assert "<th>对GMV的拉动</th>" in view.table_html


def test_table_reuses_deterministic_table_wrap_markup():
    view = render_view(_table_spec(), _tables(), finding=_finding())
    html = view.table_html
    assert '<div class="table-wrap">' in html
    assert "<table>" in html and "<thead>" in html and "<tbody>" in html


def test_emoji_in_source_cell_is_preserved():
    tables = {"t": [{"name": "手作瓷 🍵", "v": 5}]}
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["name", "v"],
        column_labels={},
        rows={},
    )
    view = render_view(spec, tables, finding=_finding())
    assert "🍵" in view.table_html


# ---- sort / order / TopN honored ------------------------------------------

def test_sort_desc_and_top_n_honored():
    spec = _table_spec(rows={"sort_by": "delta_gmv", "order": "desc", "top_n": 2})
    view = render_view(spec, _tables(), finding=_finding())
    html = view.table_html
    # top_n=2 keeps only the two largest; 客单价 (-3000) is dropped.
    assert "客单价" not in html
    # desc order: 转化 (12000) precedes 流量 (8000).
    assert html.index("转化") < html.index("流量")


def test_sort_asc_orders_smallest_first():
    spec = _table_spec(rows={"sort_by": "delta_gmv", "order": "asc"})
    view = render_view(spec, _tables(), finding=_finding())
    html = view.table_html
    # asc: 客单价 (-3000) first, 转化 (12000) last.
    assert html.index("客单价") < html.index("流量") < html.index("转化")


# ---- highlight marks an existing category (no numeric threshold) ----------

def test_highlight_marks_only_the_matching_row():
    spec = _table_spec(rows={"highlight": {"component": "转化"}})
    view = render_view(spec, _tables(), finding=_finding())
    html = view.table_html
    # the highlighted row carries the marker class; the others stay plain.
    highlighted = '<tr class="ca-row-highlight"><td>转化</td>'
    assert highlighted in html
    assert '<tr class="ca-row-highlight"><td>流量</td>' not in html


# ---- chart templates render inline SVG + a companion table ----------------

def test_chart_template_produces_svg_and_a_table():
    view = render_view(_chart_spec(), _tables(), finding=_finding())
    assert not view.degraded
    assert view.chart_svg is not None and "<svg" in view.chart_svg
    # a chart view still carries the underlying data table (aria: "详见下方表格").
    assert view.table_html is not None and "<td>12000</td>" in view.table_html
    # displayed numbers in the SVG are filled from the source, grouped by labels.
    assert "12,000" in view.chart_svg


def test_svg_is_byte_stable_across_two_calls():
    first = render_view(_chart_spec(), _tables(), finding=_finding())
    second = render_view(_chart_spec(), _tables(), finding=_finding())
    assert first.chart_svg == second.chart_svg
    assert first.table_html == second.table_html


# ---- confidence derived deterministically from the finding ----------------

def test_confidence_derived_from_finding_strength():
    assert render_view(_table_spec(), _tables(),
                       finding=_finding(EvidenceStrength.STRONG)).confidence == "强"
    assert render_view(_table_spec(), _tables(),
                       finding=_finding(EvidenceStrength.MEDIUM)).confidence == "中"
    assert render_view(_table_spec(), _tables(),
                       finding=_finding(EvidenceStrength.WEAK)).confidence == "弱"


def test_confidence_degrades_to_weak_without_a_finding():
    assert render_view(_table_spec(), _tables(), finding=None).confidence == "弱"


# ---- provenance stamp format ----------------------------------------------

def test_provenance_stamp_format():
    view = render_view(_table_spec(), _tables(), finding=_finding(EvidenceStrength.MEDIUM))
    assert view.provenance == "来源:core_business_diagnosis · growth_bridge · 证据:中"


# ---- degradation: malformed spec / missing table / missing column ---------

def test_malformed_non_dict_spec_degrades_without_raising():
    view = render_view(None, _tables())
    assert isinstance(view, CuratedView)
    assert view.degraded
    assert view.table_html is None and view.chart_svg is None
    assert view.reason  # a human-readable reason, not an exception


def test_missing_table_degrades():
    spec = _table_spec(source={"task_id": "x", "table": "does_not_exist"})
    view = render_view(spec, _tables(), finding=_finding())
    assert view.degraded
    assert view.table_html is None and view.chart_svg is None


def test_missing_column_degrades():
    spec = _table_spec(columns=["component", "ghost_col"])
    view = render_view(spec, _tables(), finding=_finding())
    assert view.degraded
    assert view.table_html is None


def test_aggregation_attempt_degrades():
    spec = _table_spec(rows={"aggregate": "sum"})
    view = render_view(spec, _tables(), finding=_finding())
    assert view.degraded


def test_garbage_inputs_never_raise():
    for spec in (None, "garbage", 42, {}, {"template": "pie_3d"}):
        for tables in (None, "nope", {}, _tables()):
            view = render_view(spec, tables)
            assert isinstance(view, CuratedView)
            # never a crash; a bad view is simply degraded with no html.
            if view.degraded:
                assert view.table_html is None and view.chart_svg is None


# ---- prose captions pass through verbatim ---------------------------------

def test_titles_and_captions_pass_through():
    spec = _table_spec(title="标题 🚀", how_to_read="怎么读", why_it_matters="为什么重要")
    view = render_view(spec, _tables(), finding=_finding())
    assert view.title == "标题 🚀"
    assert view.how_to_read == "怎么读"
    assert view.why_it_matters == "为什么重要"


def test_why_it_matters_with_fabricated_number_degrades():
    # why_it_matters is agent-authored prose; a bare digit would carry a fabricated
    # number into the merchant view, breaching the numeric-trust boundary. Such a
    # spec must degrade (no html) rather than surfacing the fabricated text.
    spec = _table_spec(why_it_matters="被抵消了 9999 元,占 50%")
    view = render_view(spec, _tables(), finding=_finding())
    assert view.degraded
    assert view.table_html is None and view.chart_svg is None
