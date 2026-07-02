from markupsafe import Markup

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength
from xhs_ceramics_analytics.reporting import charts


def _result(task_id, strength, tables):
    return AnalysisResult(
        task_id=task_id,
        title="t",
        findings=[Finding(title="f", conclusion="c", evidence_strength=strength)],
        tables=tables,
    )


def test_for_result_returns_markup_empty_for_unknown_task():
    result = _result("account_baseline", EvidenceStrength.MEDIUM, {})
    out = charts.for_result(result)
    assert isinstance(out, Markup)
    assert out == ""


def test_for_result_suppresses_not_judgable():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.NOT_JUDGABLE,
        {"cover_effects": [{"composition_type": "flatlay", "notes": 3,
                             "avg_reads": 900.0, "avg_collects": 40.0}]},
    )
    assert charts.for_result(result) == ""


def test_for_result_isolates_builder_exceptions(monkeypatch):
    result = _result("cover_style_effect", EvidenceStrength.MEDIUM, {"cover_effects": [{}]})

    def boom(*args, **kwargs):
        raise ValueError("bad row")

    monkeypatch.setitem(charts._BUILDERS, "cover_style_effect", boom)
    assert charts.for_result(result) == ""


def test_escape_neutralizes_markup():
    assert "<script>" not in charts._esc("<script>alert(1)</script>")
    assert "&lt;script&gt;" in charts._esc("<script>alert(1)</script>")


def test_empty_state_carries_message():
    svg = charts._frame(charts._empty_state(640, 200), 640, 200)
    assert "数据不足，无法判断" in svg
    assert svg.startswith("<svg")


def test_evidence_distribution_renders_segments_with_counts():
    counts = [
        {"value": "strong", "label": "强", "count": 2, "help": "h"},
        {"value": "medium", "label": "中", "count": 3, "help": "h"},
        {"value": "weak", "label": "弱", "count": 1, "help": "h"},
        {"value": "not_judgable", "label": "不可判断", "count": 4, "help": "h"},
    ]
    svg = charts.evidence_distribution(counts)
    assert "<svg" in svg
    assert "var(--green-bg)" in svg   # strong+medium share green
    assert "var(--yellow-bg)" in svg  # weak
    assert "var(--red-bg)" in svg     # not_judgable
    assert "强 2" in svg and "中 3" in svg and "弱 1" in svg and "不可判断 4" in svg


def test_evidence_distribution_empty_when_no_findings():
    counts = [{"value": v, "label": v, "count": 0, "help": "h"}
              for v in ("strong", "medium", "weak", "not_judgable")]
    assert charts.evidence_distribution(counts) == ""


def test_evidence_distribution_escapes_and_has_no_raw_float():
    counts = [{"value": "strong", "label": "强", "count": 1, "help": "h"}]
    svg = charts.evidence_distribution(counts)
    assert "0.333333" not in svg  # widths are formatted, never raw ratios


def test_cover_chart_has_two_measure_panels_and_zero_baseline():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.MEDIUM,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 5, "avg_reads": 1200.0, "avg_collects": 48.0},
            {"composition_type": "lifestyle", "notes": 4, "avg_reads": 800.0, "avg_collects": 60.0},
        ]},
    )
    html = charts.for_result(result)
    assert "平均阅读数" in html and "平均收藏数" in html
    assert 'class="chart-multiples"' in html
    assert "可信度 中" in html          # evidence badge present
    assert html.count("<svg") == 2       # one panel per measure


def test_cover_chart_shows_empty_state_for_all_null_measure():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.MEDIUM,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 5, "avg_reads": 1200.0, "avg_collects": None},
        ]},
    )
    html = charts.for_result(result)
    assert "数据不足，无法判断" in html   # the collects panel degrades honestly


def test_cover_chart_weak_evidence_is_de_emphasized():
    result = _result(
        "cover_style_effect",
        EvidenceStrength.WEAK,
        {"cover_effects": [
            {"composition_type": "flatlay", "notes": 2, "avg_reads": 300.0, "avg_collects": 9.0},
        ]},
    )
    html = charts.for_result(result)
    assert "样本不足" in html
    assert "url(#ca-hatch)" in html


def test_copy_chart_uses_copy_angle_column():
    result = _result(
        "copy_angle_effect",
        EvidenceStrength.MEDIUM,
        {"copy_effects": [
            {"copy_angle": "gift", "notes": 6, "avg_reads": 1100.0, "avg_collects": 70.0},
        ]},
    )
    html = charts.for_result(result)
    assert "送礼角度" in html          # value_label("gift")
    assert "<svg" in html


def test_comment_demand_share_bar_uses_percent_labels():
    result = _result(
        "comment_demand_mining",
        EvidenceStrength.MEDIUM,
        {"comment_demands": [
            {"demand_group": "capacity", "comments": 12, "notes": 5,
             "comment_share": 0.48, "example_comments": ["多大容量"]},
            {"demand_group": "price", "comments": 8, "notes": 4,
             "comment_share": 0.32, "example_comments": ["多少钱"]},
            {"demand_group": "other", "comments": 5, "notes": 3,
             "comment_share": 0.20, "example_comments": ["好看"]},
        ]},
    )
    html = charts.for_result(result)
    assert "<svg" in html
    assert "48%" in html                # format_percent(0.48)
    assert "容量/尺寸需求" in html        # value_label("capacity")
    assert "0.48" not in html           # never a raw ratio


def test_comment_demand_skips_zero_comment_groups():
    result = _result(
        "comment_demand_mining",
        EvidenceStrength.WEAK,
        {"comment_demands": [
            {"demand_group": "capacity", "comments": 3, "notes": 1,
             "comment_share": 1.0, "example_comments": []},
            {"demand_group": "gift", "comments": 0, "notes": 0,
             "comment_share": 0.0, "example_comments": []},
        ]},
    )
    html = charts.for_result(result)
    assert "样本不足" in html            # weak evidence badge
    assert "送礼角度" not in html         # zero-comment group omitted


_WINDOWS = ("d0_1_units", "d1_3_units", "d4_7_units", "d8_14_units")


def _rw(note_id, sku_id, vals):
    row = {"note_id": note_id, "sku_id": sku_id, "publish_time": "2026-06-01"}
    row.update(dict(zip(_WINDOWS, vals)))
    return row


def test_response_curve_draws_lines_over_four_windows():
    result = _result(
        "content_response_curve",
        EvidenceStrength.MEDIUM,
        {"response_windows": [
            _rw("n1", "s1", [2.0, 5.0, 3.0, 1.0]),
            _rw("n2", "s1", [0.0, 4.0, 6.0, 2.0]),
        ]},
    )
    html = charts.for_result(result)
    assert "<svg" in html
    assert "<path" in html                 # multi-point series draw a line
    assert "发布后 0-1 天" in html          # value_label("d0_1")
    assert "发布后 8-14 天" in html


def test_response_curve_single_point_series_draws_dot_not_line():
    result = _result(
        "content_response_curve",
        EvidenceStrength.WEAK,
        {"response_windows": [
            _rw("n1", "s1", [3.0, None, None, None]),
        ]},
    )
    html = charts.for_result(result)
    assert "<circle" in html
    assert "<path" not in html             # one observed point never draws a line
    assert "样本不足" in html


def test_response_curve_empty_when_no_rows():
    result = _result("content_response_curve", EvidenceStrength.MEDIUM,
                     {"response_windows": []})
    assert charts.for_result(result) == ""
