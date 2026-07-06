"""Threshold hint bar — an honest 'you are here vs a hint line' for measured metrics.

The hint line is ALWAYS labelled as a policy/experience line, never an industry
benchmark (the data cannot support cross-shop benchmarking). Only measurement
metrics should be passed in. Never raises.
"""
from xhs_ceramics_analytics.analytics.numeric import to_finite_float


def threshold_bar(
    metric_key: str,
    observed: object,
    hint_line: object,
    *,
    hint_source: str = "政策/经验线，非行业基准",
) -> dict:
    """Compare an observed measurement to a labelled hint line. Never a benchmark."""
    obs = to_finite_float(observed)
    hint = to_finite_float(hint_line)
    if obs is None or hint is None:
        status = "not_judgable"
    elif obs > hint:
        status = "above"
    elif obs < hint:
        status = "below"
    else:
        status = "at"
    return {
        "metric_key": metric_key,
        "observed": obs,
        "hint_line": hint,
        "status": status,
        "hint_source": hint_source,
    }
