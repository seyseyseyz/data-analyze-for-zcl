"""HHI concentration indices must not collapse to a flat "0".

gmv_hhi over 3,405 SKUs is inherently ~0.002; format_number rounds it to "0.00"
→ "0", which reads as *zero* concentration and directly contradicts the gini
(0.55) and the "高度集中" conclusion on the same card. HHI fields now render with
two significant figures so a small-but-real index stays visible.
"""

from xhs_ceramics_analytics.reporting.formatting import format_scalar


def test_small_hhi_keeps_significant_figures():
    assert format_scalar("gmv_hhi", 0.0024) == "0.0024"
    assert format_scalar("note_gmv_hhi", 0.02) == "0.02"
    assert format_scalar("repeat_gmv_hhi", 0.31) == "0.31"


def test_tiny_hhi_does_not_become_bare_zero():
    out = format_scalar("gmv_hhi", 0.0018)
    assert out != "0"
    assert out.startswith("0.001")


def test_genuine_zero_hhi_still_reads_zero():
    assert format_scalar("gmv_hhi", 0.0) == "0"


def test_none_hhi_is_placeholder():
    assert format_scalar("gmv_hhi", None) == "暂无数据"
