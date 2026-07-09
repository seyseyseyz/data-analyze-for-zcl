"""Regression tests for the chart visual refresh.

These lock the *new* visual invariants introduced when the charts moved off the
"slab-black bar / seismograph line" look: pill bars over a track rail with a
per-rank charcoal fade, and line charts carrying a gridline + soft area + a bold
moving-average trend lifted out of the faded raw daily series.

They assert SEMANTIC substrings (fill tokens, stroke widths, class names, the
smoothing caption), never a byte-exact SVG — consistent with the rest of the
chart suite, so cosmetic geometry tweaks don't churn the tests.
"""

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting import charts


def _trend_result(n: int) -> AnalysisResult:
    """core_business_diagnosis with an n-day GMV trend, HIGH reliability so the
    chart renders at full emphasis (area + trend, not the greyed thin-data look)."""
    rows = [
        {"date": f"2026-04-{i + 1:02d}"[:10], "gmv": 1000.0 + (i % 7) * 120.0,
         "is_changepoint": False}
        for i in range(n)
    ]
    # keep dates valid past April by rolling the month — the builder only needs
    # a parseable date string; spacing is uniform for our purposes.
    for i, r in enumerate(rows):
        month = 4 + (i // 28)
        day = (i % 28) + 1
        r["date"] = f"2026-{month:02d}-{day:02d}"
    return AnalysisResult(
        task_id="core_business_diagnosis",
        title="t",
        findings=[Finding(
            title="f", conclusion="c",
            evidence_strength=EvidenceStrength.WEAK,
            descriptive_reliability=DescriptiveReliability.HIGH,
        )],
        tables={"business_trend": rows},
    )


# --- pure helpers -----------------------------------------------------------

def test_moving_avg_identity_when_k_non_positive():
    vals = [1.0, 5.0, 2.0]
    assert charts._moving_avg(vals, 0) == vals
    assert charts._moving_avg(vals, -3) == vals


def test_moving_avg_centered_edge_clamped_window():
    vals = [0.0, 3.0, 6.0, 9.0, 12.0]
    out = charts._moving_avg(vals, 1)  # window = 2k+1 = 3, clamped at the edges
    assert out[0] == (0.0 + 3.0) / 2          # left edge: only 2 samples
    assert out[2] == (3.0 + 6.0 + 9.0) / 3    # interior: full 3-sample window
    assert out[-1] == (9.0 + 12.0) / 2        # right edge: only 2 samples


def test_hgrid_emits_default_number_of_hairlines():
    svg = charts._hgrid(0.0, 100.0, 10.0, 210.0)
    assert svg.count('class="ca-grid"') == charts._GRID_LEVELS


def test_hgrid_empty_when_no_vertical_room():
    assert charts._hgrid(0.0, 100.0, 200.0, 200.0) == ""


def test_area_fill_needs_two_points_and_uses_pale_green():
    assert charts._area_fill([1.0], [2.0], 50.0) == ""
    fill = charts._area_fill([0.0, 10.0], [5.0, 8.0], 50.0)
    assert "var(--green-bg, #EDF3EC)" in fill  # literal fallback → both roots match
    assert fill.startswith("<path") and fill.rstrip().endswith("/>")
    assert "Z" in fill  # closed back to the baseline


# --- horizontal bars --------------------------------------------------------

def _hbar(rows, de_emphasize=False):
    return charts._hbar(rows, value_max=100.0, de_emphasize=de_emphasize)


def test_hbar_draws_track_rail_behind_each_bar():
    rows = [("甲", 90.0, "90", "var(--ink-strong)"),
            ("乙", 40.0, "40", "var(--ink-strong)")]
    svg = _hbar(rows)
    # one round-capped rail line per row, never a <rect> (keeps template rect counts)
    assert svg.count('stroke="var(--track, #F1F0ED)"') == 2
    assert svg.count('stroke-width="20"') == 2
    assert 'stroke-linecap="round"' in svg


def test_hbar_bars_are_pills_with_charcoal_tier_fade():
    rows = [("甲", 90.0, "90", "var(--ink-strong)"),
            ("乙", 40.0, "40", "var(--ink-strong)")]
    svg = _hbar(rows)
    assert svg.count('rx="10"') == 2                 # pill bars, not slabs
    assert 'fill="var(--ink)"' in svg                # charcoal, not #111 slab
    assert 'fill="var(--ink-strong)"' not in svg     # the loud slab tone is gone
    assert 'fill-opacity="1"' in svg                 # top rank stays saturated
    assert 'fill-opacity="0.82"' in svg              # second rank fades (0.92-0.1)


def test_hbar_de_emphasized_uses_hatch_not_charcoal():
    rows = [("甲", 90.0, "90", "var(--ink-strong)")]
    svg = _hbar(rows, de_emphasize=True)
    assert "url(#ca-hatch)" in svg
    assert 'fill="var(--ink)"' not in svg


# --- long time series (smoothed) --------------------------------------------

def test_long_trend_lifts_moving_average_over_faded_raw():
    html = str(charts.for_result(_trend_result(40)))
    assert "日移动平均" in html                       # honest smoothing caption
    assert "var(--green-bg, #EDF3EC)" in html          # soft area under the trend
    assert 'stroke="var(--muted)"' in html             # faded raw daily hairline...
    assert 'stroke-opacity="0.45"' in html             # ...drawn behind, dimmed
    assert 'stroke="var(--ink-strong)"' in html        # bold trend line on top
    assert 'r="4"' in html                             # endpoint anchors on the trend


def test_short_trend_stays_exact_no_smoothing():
    html = str(charts.for_result(_trend_result(10)))  # below _MAX_LINE_MARKERS
    assert "日移动平均" not in html                    # no derived trend claimed
    assert 'stroke-opacity="0.45"' not in html         # no faded raw underlay
    assert 'stroke="var(--ink-strong)"' in html        # the sole line stays bold
