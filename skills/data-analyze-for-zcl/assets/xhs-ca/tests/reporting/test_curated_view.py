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


# ---- every rendered cell is FORMATTED from the source value ---------------


def test_table_cells_are_formatted_from_source():
    view = render_view(_table_spec(), _tables(), finding=_finding())
    assert not view.degraded
    assert view.chart_svg is None  # a table template renders no chart
    html = view.table_html
    # each cell is filled from the source but presented via the shared fact-layer
    # formatter: the _gmv money column follows the 过万用万 rule (12000 → 1.2万; the
    # sub-1万 amounts stay precise grouped); text passes through.
    for cell in (
        "<td>转化</td>",
        "<td>1.2万</td>",
        "<td>流量</td>",
        "<td>8,000</td>",
        "<td>客单价</td>",
        "<td>-3,000</td>",
    ):
        assert cell in html
    # a raw, unformatted money dump must never appear.
    assert "<td>12000</td>" not in html
    # the unselected `note` column is not surfaced.
    assert "<td>a</td>" not in html


def test_engine_never_invents_a_number_absent_from_source():
    view = render_view(_table_spec(), _tables(), finding=_finding())
    # 9000 is a plausible but fabricated value — it must never appear (formatted or not).
    assert "9000" not in view.table_html
    assert "9,000" not in view.table_html


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
    tables = {"t": [{"name": "手作瓷 🍵", "v": 5}, {"name": "素坯", "v": 2}]}
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


# ---- chart templates render ONLY the chart, no redundant companion table ---


def test_chart_template_produces_svg_without_a_redundant_table():
    view = render_view(_chart_spec(), _tables(), finding=_finding())
    assert not view.degraded
    assert view.chart_svg is not None and "<svg" in view.chart_svg
    # #6: a chart view shows ONLY the chart — the numbers ARE the chart, so a
    # companion data table of the same rows is pure redundancy in the 叙事版.
    assert view.table_html is None
    # displayed numbers in the SVG are filled from the source via the 过万用万 rule.
    assert "1.2万" in view.chart_svg


def test_svg_is_byte_stable_across_two_calls():
    first = render_view(_chart_spec(), _tables(), finding=_finding())
    second = render_view(_chart_spec(), _tables(), finding=_finding())
    assert first.chart_svg == second.chart_svg
    assert first.table_html == second.table_html


# ---- confidence derived deterministically from the finding ----------------


def test_confidence_derived_from_finding_strength():
    assert (
        render_view(_table_spec(), _tables(), finding=_finding(EvidenceStrength.STRONG)).confidence
        == "强"
    )
    assert (
        render_view(_table_spec(), _tables(), finding=_finding(EvidenceStrength.MEDIUM)).confidence
        == "中"
    )
    assert (
        render_view(_table_spec(), _tables(), finding=_finding(EvidenceStrength.WEAK)).confidence
        == "弱"
    )


def test_confidence_degrades_to_weak_without_a_finding():
    assert render_view(_table_spec(), _tables(), finding=None).confidence == "弱"


# ---- provenance stamp format ----------------------------------------------


def test_provenance_stamp_drops_task_id_and_names_table_by_label():
    view = render_view(_table_spec(), _tables(), finding=_finding(EvidenceStrength.MEDIUM))
    # De-leak: the internal task_id no longer reaches the merchant-facing footer; the
    # table is named by its human label (this synthetic key degrades to a readable form).
    assert view.provenance == "来源:growth bridge · 证据:中"
    assert "core_business_diagnosis" not in view.provenance


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


# ---- cells formatted via the shared fact-layer formatter (bool/percent/None) --


def test_boolean_cell_renders_yes_no_not_raw_bool():
    tables = {
        "t": [{"name": "促销周", "is_anomaly": True}, {"name": "常规周", "is_anomaly": False}]
    }  # 2 rows (min-row rule)
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["name", "is_anomaly"],
        column_labels={},
        rows={},
    )
    html = render_view(spec, tables, finding=_finding()).table_html
    assert "<td>是</td>" in html and "<td>否</td>" in html
    # the raw Python booleans must never leak into the merchant view.
    assert "True" not in html and "False" not in html


def test_percent_column_renders_as_percentage():
    tables = {
        "t": [{"term": "手作杯", "click_rate": 0.046}, {"term": "手作盘", "click_rate": 0.03}]
    }
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["term", "click_rate"],
        column_labels={},
        rows={},
    )
    html = render_view(spec, tables, finding=_finding()).table_html
    assert "4.6%" in html
    assert "0.046" not in html  # never the raw ratio


def test_none_cell_renders_placeholder_not_empty():
    tables = {"t": [{"name": "缺口", "gmv": None}, {"name": "其他", "gmv": 100}]}
    spec = _table_spec(
        source={"task_id": "x", "table": "t"}, columns=["name", "gmv"], column_labels={}, rows={}
    )
    html = render_view(spec, tables, finding=_finding()).table_html
    assert "暂无数据" in html


def test_missing_column_label_falls_back_to_human_field_label():
    # no agent label for `delta_gmv`; the header uses a human label, never the raw
    # snake_case source column name.
    spec = _table_spec(column_labels={"component": "增长来源"})
    html = render_view(spec, _tables(), finding=_finding()).table_html
    assert "<th>delta_gmv</th>" not in html


# ---- timeseries form guard: a per-period series is chart-only, never a grid ---


def _ts_tables():
    return {
        "business_trend": [
            {"date": f"2026-04-{d:02d}", "gmv": 1000 + d * 10, "is_anomaly": d % 3 == 0}
            for d in range(1, 13)
        ]
    }


def test_timeseries_table_template_is_suppressed_entirely():
    # a table-template over a per-period source must degrade — never a wall-of-dates.
    spec = _table_spec(
        source={"task_id": "core", "table": "business_trend"},
        columns=["date", "gmv", "is_anomaly"],
        column_labels={},
        rows={},
        template="ranking_table",
    )
    view = render_view(spec, _ts_tables(), finding=_finding())
    assert view.degraded
    assert view.table_html is None and view.chart_svg is None


def test_timeseries_chart_keeps_chart_and_drops_companion_table():
    spec = _table_spec(
        source={"task_id": "core", "table": "business_trend"},
        columns=["date", "gmv"],
        column_labels={},
        rows={},
        template="trend_line",
        chart={"x": "date", "y": "gmv"},
    )
    view = render_view(spec, _ts_tables(), finding=_finding())
    assert not view.degraded
    assert view.chart_svg is not None and "<svg" in view.chart_svg
    assert view.table_html is None  # the trend lives in the chart, not a per-day grid


# ---- default row cap: only the most-valuable rows, foldable -----------------


def test_long_table_capped_to_default_max_with_fold_and_caption():
    rows = [{"cat": f"cat{i:02d}", "val": 100 - i} for i in range(20)]
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["cat", "val"],
        column_labels={},
        rows={"sort_by": "val", "order": "desc"},
    )
    html = render_view(spec, {"t": rows}, finding=_finding()).table_html
    # only the top 8 rows survive (sorted desc by val): cat00..cat07 kept, cat08 gone.
    assert "cat07" in html and "cat08" not in html
    # the truncation is captioned and the table is foldable via native <details>.
    assert "共 20 行" in html
    assert "<details" in html and "<summary>" in html


def test_short_table_is_not_capped_or_folded():
    html = render_view(_table_spec(), _tables(), finding=_finding()).table_html  # 3 rows
    assert "<details" not in html
    assert "共 " not in html


# ---- single-row suppression: a one-row grid is a scalar, not a table (#9) ------


def test_single_row_table_view_is_suppressed_as_low_value():
    # #9: a comparison/ranking table needs ≥2 rows to be worth a grid — a lone row is a
    # scalar (or a single rank) that belongs in the prose, not a one-row table. Such a
    # table-template view degrades; the section keeps its prose (and any charts).
    tables = {"t": [{"component": "转化", "delta_gmv": 12000}]}
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["component", "delta_gmv"],
        column_labels={},
        rows={},
    )
    view = render_view(spec, tables, finding=_finding())
    assert view.degraded
    assert view.table_html is None and view.chart_svg is None
    assert view.reason  # a human-readable reason, not silence


def test_table_view_truncated_to_a_single_row_is_suppressed():
    # top_n=1 selects a lone row — the grid still has nothing to compare, so it degrades.
    spec = _table_spec(rows={"sort_by": "delta_gmv", "order": "desc", "top_n": 1})
    view = render_view(spec, _tables(), finding=_finding())
    assert view.degraded
    assert view.table_html is None


def test_two_row_table_view_is_kept():
    # the boundary: exactly two rows is a real comparison — never suppressed.
    tables = {
        "t": [{"component": "转化", "delta_gmv": 12000}, {"component": "流量", "delta_gmv": 8000}]
    }
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["component", "delta_gmv"],
        column_labels={},
        rows={},
    )
    view = render_view(spec, tables, finding=_finding())
    assert not view.degraded
    assert view.table_html is not None


def test_empty_table_view_degrades_with_a_distinct_reason():
    # a 0-row table also falls under the min-row rule, but its reason must say "no data",
    # not "single-row" — the wording distinguishes an empty source from a lone-scalar grid.
    spec = _table_spec(
        source={"task_id": "x", "table": "t"},
        columns=["component", "delta_gmv"],
        column_labels={},
        rows={},
    )
    view = render_view(spec, {"t": []}, finding=_finding())
    assert view.degraded
    assert view.table_html is None and view.chart_svg is None
    assert "单行" not in view.reason  # not the single-row message
    assert "数据" in view.reason


def test_single_row_chart_view_is_not_suppressed():
    # a chart is exempt from the min-row rule — a one-point chart is handled by the chart
    # primitives, not this grid path, so the min-row suppression must not touch it.
    tables = {"t": [{"component": "转化", "delta_gmv": 12000}]}
    spec = _chart_spec(
        source={"task_id": "x", "table": "t"},
        columns=["component", "delta_gmv"],
        column_labels={},
        chart={"x": "component", "y": "delta_gmv"},
        rows={},
    )
    view = render_view(spec, tables, finding=_finding())
    assert not view.degraded
    assert view.chart_svg is not None and "<svg" in view.chart_svg
