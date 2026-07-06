"""The scissors-gap hero suppresses the meaningless bold mean-of-series line."""
from xhs_ceramics_analytics.reporting import charts


def _series():
    return [
        ("GMV", [100.0, 120.0, 90.0]),
        ("人均产出", [10.0, 8.7, 8.0]),
    ]


def test_aggregate_drawn_by_default():
    svg = charts._line(_series(), ["4月", "5月", "6月"], de_emphasize=False)
    assert "var(--ink-strong)" in svg  # bold mean line present


def test_aggregate_suppressed_when_requested():
    svg = charts._line(
        _series(), ["4月", "5月", "6月"], de_emphasize=False, suppress_aggregate=True
    )
    assert "var(--ink-strong)" not in svg  # no bold mean-of-series line
    assert "var(--muted)" in svg  # the real per-series lines still render
