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
