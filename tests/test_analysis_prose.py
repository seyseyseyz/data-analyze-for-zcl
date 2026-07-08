"""Prose number/date formatting shares the SAME primitives as the table path.

The conclusion sentence that leads each finding used to build its numbers with
bare ``round()`` / f-strings, so a value read one way in the headline
(``1302239``, ``20260628``, ``diff=-0.8pct``) and another in the table
(``1,302,239``, ``2026-06-28``, ``-0.77%``). These helpers close that gap.
"""
from xhs_ceramics_analytics.analysis.prose import cn_date, money, pp, qty


def test_money_groups_and_rounds_to_whole_yuan():
    # the headline GMV used to render as a bare ``1302239``; group it like the table
    assert money(1302239.01) == "1,302,239"
    assert money(200.07) == "200"
    assert money(0) == "0"
    assert money(None) == "0"


def test_qty_groups_counts():
    # note/sku counts can exceed 1000 and must group; small counts pass through
    assert qty(1272) == "1,272"
    assert qty(3405) == "3,405"
    assert qty(94) == "94"
    assert qty(None) == "0"


def test_pp_never_emits_negative_zero():
    # A gap that rounds to 0.0 個百分點 must read "0", never "-0" (a numeric-form bug).
    assert pp(-0.0004) == "0 个百分点"      # -0.04pp rounds to 0 → no minus sign
    assert pp(-0.008) == "-0.8 个百分点"     # a real negative gap still keeps its sign


def test_pp_is_plain_language_not_machine_token():
    # ``pp`` / ``diff=…pct`` machine tokens become 个百分点 in reader prose
    assert pp(-0.008) == "-0.8 个百分点"
    assert pp(-0.0177) == "-1.8 个百分点"
    assert pp(0.0) == "0 个百分点"
    token = pp(-0.008)
    assert "pp" not in token and "pct" not in token


def test_cn_date_normalizes_integer_yyyymmdd():
    # the changepoint date leaked as bare 20260628; normalize like the table
    assert cn_date(20260628) == "2026-06-28"
    assert cn_date(20260628.0) == "2026-06-28"
    assert cn_date("2026-06-28") == "2026-06-28"
    # a non-date value must not crash — fall back to its string form
    assert cn_date("上新日") == "上新日"
