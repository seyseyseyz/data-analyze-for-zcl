"""Regression tests for mixed-sign (diverging) bar/waterfall geometry.

The GMV bridge (LMDI 增长归因) feeds the ``breakdown_waterfall`` template signed
contributions — e.g. 流量 +17689 / 转化 -17105 / 客单价 +2673 — whose *sum* (≈3257)
is tiny next to the components. The old ``_waterfall`` normalised each segment by
that sum, so a single bar rendered at ``17689/3257*180 ≈ 977px`` — 3× outside the
300px canvas — and negative contributions produced negative-height rects. A share
bar (`_vbar`) fed a negative value had the same negative-height defect.

These lock the fix: every bar stays inside the plot band with a non-negative
height, anchored to a shared zero baseline. Assertions parse rect geometry (not
byte-exact SVG) so cosmetic tweaks don't churn them.
"""

import re

from xhs_ceramics_analytics.reporting import charts

# geometry constants mirrored from the primitives (viewBox 0 0 308 300)
_HEIGHT = 300
_PAD_T = 56
_PAD_B = 64
_PLOT_BOTTOM = _HEIGHT - _PAD_B  # 236 — bottom of the plot band
_EPS = 0.5  # sub-pixel rounding tolerance

_RECT_RE = re.compile(r'<rect\b[^>]*\by="([-\d.]+)"[^>]*\bheight="([-\d.]+)"')


def _rects(svg: str) -> list[tuple[float, float]]:
    """Return (y, height) for every bar rect in the SVG."""
    return [(float(y), float(h)) for y, h in _RECT_RE.findall(svg)]


def _assert_within_plot(svg: str) -> list[tuple[float, float]]:
    rects = _rects(svg)
    assert rects, "expected at least one bar rect"
    for y, h in rects:
        assert h >= -_EPS, f"bar height must be non-negative, got {h}"
        assert y >= _PAD_T - _EPS, f"bar top {y} escapes above the plot band"
        assert y + h <= _PLOT_BOTTOM + _EPS, (
            f"bar bottom {y + h} escapes below the plot band ({_PLOT_BOTTOM})"
        )
    return rects


# --- waterfall / GMV bridge -------------------------------------------------

def test_waterfall_mixed_sign_stays_in_canvas():
    cats = ["流量贡献", "转化贡献", "客单价贡献"]
    values = [17689.0, -17105.0, 2673.0]
    texts = ["+17689", "-17105", "+2673"]
    svg = charts._waterfall(cats, values, texts, title="", de_emphasize=False)
    _assert_within_plot(svg)


def test_waterfall_all_negative_stays_in_canvas():
    svg = charts._waterfall(
        ["甲", "乙"], [-500.0, -300.0], ["-500", "-300"],
        title="", de_emphasize=False,
    )
    _assert_within_plot(svg)


def test_waterfall_all_positive_still_renders_stacked():
    # part-to-whole (refund layers) must keep working: bars fill the plot band.
    svg = charts._waterfall(
        ["发货前", "发货后"], [0.6, 0.4], ["0.6", "0.4"],
        title="", de_emphasize=False,
    )
    rects = _assert_within_plot(svg)
    assert len(rects) == 2


# --- diverging vertical bar -------------------------------------------------

def test_vbar_with_negative_value_stays_in_canvas():
    svg = charts._vbar(
        ["甲", "乙", "丙"], [80.0, -40.0, 20.0], ["80", "-40", "20"],
        title="", de_emphasize=False,
    )
    _assert_within_plot(svg)


def test_vbar_all_positive_unchanged_bytes():
    # the all-positive path must stay byte-identical (many existing chart tests
    # depend on it): a full-height top bar anchored at the baseline.
    svg = charts._vbar(
        ["甲", "乙"], [100.0, 50.0], ["100", "50"],
        title="", de_emphasize=False,
    )
    rects = _rects(svg)
    # baseline_y = 56 + 180 = 236; top bar (100) fills full plot_h=180 → y=56.
    assert (56.0, 180.0) in rects
    assert (146.0, 90.0) in rects  # second bar: 50/100*180=90, y=236-90=146
