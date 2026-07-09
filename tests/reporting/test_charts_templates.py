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
    # every displayed number is filled from the rows via the 过万用万 rule (≥1万 → 万).
    assert "80.0万" in svg and "41.4万" in svg and "12.0万" in svg
    # known enum keys are localized deterministically via labels.value_label.
    assert "笔记" in svg and "商品卡" in svg


def test_value_labels_are_type_aware_percent_column():
    # A percent-typed y column (``*_share``) must read as a percent — the same
    # fact-layer rule the tables use (format_scalar) — never a raw ratio "0.64".
    rows = [
        {"carrier_zh": "商品卡", "gmv_share": 0.6445},
        {"carrier_zh": "笔记", "gmv_share": 0.3555},
    ]
    svg = str(
        render_chart_template("share_bar", rows, {"x": "carrier_zh", "y": "gmv_share"})
    )
    assert "64.5%" in svg and "35.5%" in svg   # scaled ×100 with a % sign
    assert "0.64" not in svg and "0.36" not in svg  # never a bare ratio label


def test_value_labels_are_type_aware_money_column_unchanged():
    # A money y column reads via the shared 过万用万 rule (≥1万 → 万-notation) — the
    # type-aware switch must not regress the money path (format_scalar == format_money).
    svg = str(
        render_chart_template("share_bar", _share_rows(), {"x": "channel", "y": "gmv"})
    )
    assert "80.0万" in svg and "41.4万" in svg and "12.0万" in svg


def test_boolean_category_label_renders_yes_no_not_raw_bool():
    # A boolean x-column category must read 是/否 — same as the tables (format_scalar)
    # — never the raw Python "True"/"False" (the "False/True值" complaint). Value labels
    # were already type-aware; the category axis is closed here too.
    rows = [
        {"is_promo": True, "gmv": 12000.0},
        {"is_promo": False, "gmv": 8000.0},
    ]
    svg = str(
        render_chart_template("share_bar", rows, {"x": "is_promo", "y": "gmv"})
    )
    assert ">是<" in svg and ">否<" in svg
    assert "True" not in svg and "False" not in svg


# ---- breakdown_waterfall (reuses _waterfall) ------------------------------

def test_breakdown_waterfall_stacks_one_rect_per_component():
    svg = str(
        render_chart_template(
            "breakdown_waterfall", _bridge_rows(), {"x": "component", "y": "delta_gmv"}
        )
    )
    assert svg.count("<rect x=") == 3
    # 过万用万: 12000 → 1.2万; the two sub-1万 deltas stay precise grouped.
    assert "1.2万" in svg and "8,000" in svg and "3,000" in svg
    assert "转化" in svg  # merchant category value passes through verbatim


# ---- trend_line (reuses _line) --------------------------------------------

def test_trend_line_draws_path_markers_and_x_labels():
    svg = str(
        render_chart_template("trend_line", _trend_rows(), {"x": "date", "y": "gmv"})
    )
    assert "<svg" in svg
    assert "<path" in svg  # a polyline connecting the observations
    assert svg.count("<circle") == 3  # one marker per observation
    # x labels are trimmed to MM-DD (no 4-digit year) so a dense date axis never
    # overlaps — full ISO dates (~70px) collide at the tick spacing; MM-DD does not.
    assert ">04-01<" in svg and ">06-01<" in svg
    assert "2026-04-01" not in svg


# ---- horizontal_bar (reuses _hbar — readable for long CJK category labels) --

def _ranking_rows():
    return [
        {"term": "青瓷茶具套装礼盒", "gmv": 42000.0},
        {"term": "手工陶瓷马克杯", "gmv": 28000.0},
        {"term": "日式粗陶饭碗", "gmv": 15000.0},
    ]


def test_horizontal_bar_renders_one_bar_per_row_with_labels():
    svg = str(
        render_chart_template("horizontal_bar", _ranking_rows(), {"x": "term", "y": "gmv"})
    )
    assert "<svg" in svg
    assert svg.count("<rect x=") == 3          # one horizontal bar per row
    assert "4.2万" in svg and "1.5万" in svg  # value labels (≥1万 → 万) filled from rows
    # long category labels survive as full text in each bar's <title> (hbar truncates
    # the visible label but keeps the whole string reachable — the readability win).
    assert "青瓷茶具套装礼盒" in svg


def test_horizontal_bar_value_labels_are_type_aware():
    # a percent y column reads as a percent here too (shared format_scalar path)
    rows = [{"term": "礼盒", "gmv_share": 0.42}, {"term": "自用", "gmv_share": 0.58}]
    svg = str(
        render_chart_template("horizontal_bar", rows, {"x": "term", "y": "gmv_share"})
    )
    assert "42%" in svg and "58%" in svg
    assert "0.42" not in svg


def test_horizontal_bar_is_registered_as_a_chart_template():
    from xhs_ceramics_analytics.reporting.view_spec import CHART_TEMPLATES, TEMPLATES

    assert "horizontal_bar" in CHART_TEMPLATES
    assert "horizontal_bar" in TEMPLATES


# ---- large-series form guards (label walls + oversized dumps) -------------

def _daily_rows(n):
    # n ascending-valued daily points; deterministic, no Date.now.
    return [{"date": f"2026-04-{i + 1:02d}", "gmv": float(1000 + i)} for i in range(n)]


def test_trend_line_thins_x_labels_and_drops_markers_for_long_series():
    # A 90-point daily series must NOT render a 90-label x-axis wall or 90 dots.
    svg = str(render_chart_template("trend_line", _daily_rows(90), {"x": "date", "y": "gmv"}))
    assert "<path" in svg                       # the line shape is preserved (all points)
    assert svg.count('class="ca-cat"') <= 12    # x-axis thinned to a readable handful
    assert svg.count("<circle") == 0            # per-point markers dropped for a long series
    assert "2026-" not in svg                   # every date tick trimmed to MM-DD (no overlap)


def test_trend_line_keeps_all_labels_and_markers_for_short_series():
    # The small-series behaviour is untouched: 3 points → 3 labels, 3 markers.
    svg = str(render_chart_template("trend_line", _trend_rows(), {"x": "date", "y": "gmv"}))
    assert svg.count('class="ca-cat"') == 3
    assert svg.count("<circle") == 3


def test_share_bar_caps_categories_to_top_values():
    # 50 categories would render as unreadable 2px bars — cap to the top-12 by value.
    rows = [{"sku": f"sku{i}", "gmv": float(i)} for i in range(50)]
    svg = str(render_chart_template("share_bar", rows, {"x": "sku", "y": "gmv"}))
    assert svg.count("<rect x=") == 12
    assert ">sku49<" in svg and ">sku0<" not in svg  # kept the highest, dropped the lowest


def test_horizontal_bar_caps_categories_to_top_values():
    rows = [{"term": f"词{i}", "gmv": float(i)} for i in range(50)]
    svg = str(render_chart_template("horizontal_bar", rows, {"x": "term", "y": "gmv"}))
    assert svg.count("<rect x=") == 12


def test_chart_svg_caps_render_width_to_its_native_viewbox():
    # The SVG must not stretch to the full content column (the "太大了" complaint):
    # each chart caps at its own viewBox width via an inline max-width.
    line = str(render_chart_template("trend_line", _trend_rows(), {"x": "date", "y": "gmv"}))
    assert "max-width:640px" in line              # line viewBox is 640 wide
    bar = str(render_chart_template("share_bar", _share_rows(), {"x": "channel", "y": "gmv"}))
    assert "max-width:308px" in bar               # vbar viewBox is 308 wide


# ---- byte-determinism (no random ids, no timestamps) ----------------------

def test_every_template_is_byte_deterministic():
    cases = [
        ("share_bar", _share_rows(), {"x": "channel", "y": "gmv"}),
        ("breakdown_waterfall", _bridge_rows(), {"x": "component", "y": "delta_gmv"}),
        ("trend_line", _trend_rows(), {"x": "date", "y": "gmv"}),
        ("horizontal_bar", _ranking_rows(), {"x": "term", "y": "gmv"}),
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
    assert "80.0万" in svg and "41.4万" in svg
