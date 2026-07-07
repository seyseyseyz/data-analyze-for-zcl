"""Spec-driven chart template renderers (charts.render_chart_template).

A curation agent picks a chart template + an {x, y} column binding; this PURE
renderer fills the SVG deterministically from already-selected/ordered rows,
reusing the same SVG primitives the task-keyed builders use (`_line`,
`_waterfall`, `_vbar`). Byte-determinism is a hard contract (no random ids, no
timestamps, stable ordering), the renderer never raises on garbage, and the
existing `for_result` deterministic path must keep working.
"""
from markupsafe import Markup

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting import charts
from xhs_ceramics_analytics.reporting.charts import render_chart_template


# ---- fixtures (already-selected, already-ordered rows) --------------------

def _share_rows():
    return [
        {"channel": "note", "gmv": 800357.0},
        {"channel": "card", "gmv": 414126.0},
        {"channel": "search", "gmv": 120000.0},
    ]


def _bridge_rows():
    return [
        {"component": "转化", "delta_gmv": 12000.0},
        {"component": "流量", "delta_gmv": 8000.0},
        {"component": "客单价", "delta_gmv": 3000.0},
    ]


def _trend_rows():
    return [
        {"date": "2026-04-01", "gmv": 1000.0},
        {"date": "2026-05-01", "gmv": 1800.0},
        {"date": "2026-06-01", "gmv": 2600.0},
    ]


# ---- share_bar (reuses _vbar) ---------------------------------------------

def test_share_bar_renders_one_bar_per_row_from_binding():
    svg = str(
        render_chart_template("share_bar", _share_rows(), {"x": "channel", "y": "gmv"})
    )
    assert "<svg" in svg
    # `<rect x=` targets the bar rects; the shared _HATCH pattern emits a
    # `<rect width=` that must NOT be counted.
    assert svg.count("<rect x=") == 3
    # every displayed number is filled from the rows (grouped, whole-yuan).
    assert "800,357" in svg and "414,126" in svg and "120,000" in svg
    # known enum keys are localized deterministically via labels.value_label.
    assert "笔记" in svg and "商品卡" in svg


# ---- breakdown_waterfall (reuses _waterfall) ------------------------------

def test_breakdown_waterfall_stacks_one_rect_per_component():
    svg = str(
        render_chart_template(
            "breakdown_waterfall", _bridge_rows(), {"x": "component", "y": "delta_gmv"}
        )
    )
    assert svg.count("<rect x=") == 3
    assert "12,000" in svg and "8,000" in svg and "3,000" in svg
    assert "转化" in svg  # merchant category value passes through verbatim


# ---- trend_line (reuses _line) --------------------------------------------

def test_trend_line_draws_path_markers_and_x_labels():
    svg = str(
        render_chart_template("trend_line", _trend_rows(), {"x": "date", "y": "gmv"})
    )
    assert "<svg" in svg
    assert "<path" in svg  # a polyline connecting the observations
    assert svg.count("<circle") == 3  # one marker per observation
    assert "2026-04-01" in svg and "2026-06-01" in svg  # x labels from the bound column


# ---- byte-determinism (no random ids, no timestamps) ----------------------

def test_every_template_is_byte_deterministic():
    cases = [
        ("share_bar", _share_rows(), {"x": "channel", "y": "gmv"}),
        ("breakdown_waterfall", _bridge_rows(), {"x": "component", "y": "delta_gmv"}),
        ("trend_line", _trend_rows(), {"x": "date", "y": "gmv"}),
    ]
    for template, rows, binding in cases:
        first = str(render_chart_template(template, rows, binding))
        second = str(render_chart_template(template, rows, binding))
        assert first == second, f"{template} is not byte-deterministic"
        # the only id in the document is the fixed hatch-pattern id — nothing random.
        assert first.count('id="') == 1


# ---- confidence drives de-emphasis (reuses the existing convention) -------

def test_weak_confidence_de_emphasizes_the_chart():
    binding = {"x": "channel", "y": "gmv"}
    strong = str(render_chart_template("share_bar", _share_rows(), binding, confidence="强"))
    weak = str(render_chart_template("share_bar", _share_rows(), binding, confidence="弱"))
    # the hatch PATTERN is always defined; only weak evidence FILLS bars with it.
    assert "url(#ca-hatch)" not in strong
    assert "url(#ca-hatch)" in weak


def test_reader_confidence_object_is_accepted_for_de_emphasis():
    from xhs_ceramics_analytics.reporting.confidence import NOT_JUDGABLE

    binding = {"x": "channel", "y": "gmv"}
    svg = str(render_chart_template("share_bar", _share_rows(), binding, confidence=NOT_JUDGABLE))
    assert "url(#ca-hatch)" in svg  # not_judgable → de_emphasize=True


# ---- never-raise / graceful degradation -----------------------------------

def test_unknown_template_degrades_to_empty_markup():
    out = render_chart_template("pie_chart_3d", _share_rows(), {"x": "channel", "y": "gmv"})
    assert isinstance(out, Markup)
    assert str(out) == ""


def test_missing_binding_degrades_to_empty_markup():
    assert str(render_chart_template("share_bar", _share_rows(), {})) == ""
    assert str(render_chart_template("share_bar", _share_rows(), {"x": "channel"})) == ""
    assert str(render_chart_template("share_bar", _share_rows(), {"y": "gmv"})) == ""


def test_garbage_inputs_never_raise():
    assert str(render_chart_template("share_bar", None, {"x": "a", "y": "b"})) == ""
    assert str(render_chart_template("share_bar", [], {"x": "a", "y": "b"})) == ""
    assert str(render_chart_template(None, None, None)) == ""
    # all-None y column → framed empty state, still a Markup, no raise.
    empty = render_chart_template("trend_line", [{"date": "x"}], {"x": "date", "y": "gmv"})
    assert isinstance(empty, Markup)


def test_non_dict_rows_are_tolerated():
    rows = [{"channel": "note", "gmv": 100.0}, "garbage", None, 42]
    svg = str(render_chart_template("share_bar", rows, {"x": "channel", "y": "gmv"}))
    assert "<svg" in svg  # the one good row plots; junk rows contribute no bar, no raise
    assert svg.count("<rect x=") == 1


# ---- guard: the existing deterministic path is untouched ------------------

def test_for_result_still_renders_a_representative_chart():
    rows = [
        {"carrier_zh": "笔记", "gmv": 800357.48},
        {"carrier_zh": "商城", "gmv": 414126.02},
    ]
    result = AnalysisResult(
        task_id="channel_structure_diagnosis",
        title="渠道结构",
        findings=[
            Finding(
                title="渠道结构",
                conclusion="c",
                evidence_strength=EvidenceStrength.WEAK,
                descriptive_reliability=DescriptiveReliability.HIGH,
            )
        ],
        tables={"channel_scale": rows},
    )
    svg = str(charts.for_result(result))
    assert svg  # the task-keyed builder path still produces a chart
    assert "800,357" in svg and "414,126" in svg
