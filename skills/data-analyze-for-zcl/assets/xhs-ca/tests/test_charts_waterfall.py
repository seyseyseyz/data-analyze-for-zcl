"""Refund waterfall — floating bars that descend from the total."""
from xhs_ceramics_analytics.reporting import charts


def test_waterfall_draws_one_rect_per_component():
    svg = charts._waterfall(
        ["发货前", "发货后"],
        [129019.0, 79344.0],
        ["¥12.9万", "¥7.9万"],
        title="退款结构",
        de_emphasize=False,
    )
    # `<rect x=` targets the bar rects; the shared _HATCH pattern also emits a
    # `<rect width=` that must not be counted.
    assert svg.count("<rect x=") == 2
    assert "¥12.9万" in svg and "¥7.9万" in svg


def test_second_segment_floats_below_the_first():
    # The second bar's top must sit at the first bar's cumulative height (floating),
    # so its y attribute is strictly greater than the first bar's y.
    svg = charts._waterfall(
        ["发货前", "发货后"], [129019.0, 79344.0], ["a", "b"],
        title="t", de_emphasize=False,
    )
    ys = [float(tok.split('"')[1]) for tok in svg.split("y=")[1:3]]
    assert ys[1] > ys[0]


def test_empty_degrades_to_frame():
    svg = charts._waterfall([], [], [], title="t", de_emphasize=False)
    assert "<svg" in svg  # framed empty state, never raises
    assert "<rect x=" not in svg  # no bar rects (the _HATCH pattern rect is fine)
