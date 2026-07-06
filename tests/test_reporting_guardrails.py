"""Threshold hint bar — observed value vs a labelled policy/experience line."""
from xhs_ceramics_analytics.reporting.guardrails import threshold_bar


def test_status_above_below_at():
    assert threshold_bar("refund_rate", 0.18, 0.15)["status"] == "above"
    assert threshold_bar("refund_rate", 0.12, 0.15)["status"] == "below"
    assert threshold_bar("refund_rate", 0.15, 0.15)["status"] == "at"


def test_hint_source_is_labelled_not_a_benchmark():
    bar = threshold_bar("per_visitor_gmv", 8.7, 10.0)
    assert bar["hint_source"] == "政策/经验线，非行业基准"
    assert bar["observed"] == 8.7 and bar["hint_line"] == 10.0


def test_dirty_input_not_judgable():
    assert threshold_bar("x", None, 0.15)["status"] == "not_judgable"
    assert threshold_bar("x", 0.1, float("nan"))["status"] == "not_judgable"
