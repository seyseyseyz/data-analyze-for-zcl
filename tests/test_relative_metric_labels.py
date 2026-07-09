"""The self-benchmark top/weak metric labels must frame themselves as *relative*.

``top_metric`` is ``max(bench_rows, key=self_percentile)`` — the metric with the
highest self-percentile among the shop's own metrics, not an absolute champion.
When even that metric sits at P12, the old label "最强指标" read as a contradiction
("strongest metric, 12th percentile"). The copy now says 相对最强/相对最弱 so the
reader understands it is relative-among-metrics and may still be historically low.
"""

from xhs_ceramics_analytics.reporting.formatting import field_help, field_label


def test_top_metric_label_is_relative():
    assert field_label("top_metric") == "相对最强指标"
    assert field_label("top_percentile") == "相对最强历史排名"
    # help text must warn that "strongest" can still be low
    assert "相对" in field_help("top_metric")
    assert "偏低" in field_help("top_metric") or "低于" in field_help("top_metric")


def test_weak_metric_label_is_relative():
    assert field_label("weak_metric") == "相对最弱指标"
    assert field_label("weak_percentile") == "相对最弱历史排名"


def test_no_absolute_strongest_claim_remains():
    # the bare 最强/最弱 (no 相对 qualifier) must be gone from these four labels
    for key in ("top_metric", "top_percentile", "weak_metric", "weak_percentile"):
        assert field_label(key).startswith("相对")
