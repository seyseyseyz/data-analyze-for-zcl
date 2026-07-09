"""net_margin / sweet_net_margin are ratios (加购转化率 − 退款率), not money.

They were caught by the ``_margin`` entry in ``MONEY_SUFFIXES`` and rendered as
whole yuan, so a real 0.45 (45 个百分点) rounded to "0" — the price-band 甜点 table
showed 净收益 全为 0. They are differences of two 0-1 rates and must render as
percents. ``marginal_roas`` (the only other margin-ish key) ends ``_roas`` and is
untouched.
"""

from xhs_ceramics_analytics.reporting.formatting import (
    format_scalar,
    is_money_field,
    is_percent_field,
)


def test_net_margin_is_percent_not_money():
    assert is_percent_field("net_margin")
    assert is_percent_field("sweet_net_margin")
    assert not is_money_field("net_margin")
    assert not is_money_field("sweet_net_margin")


def test_net_margin_renders_as_percent_not_zero_yuan():
    # 0.45 was rounding to "0" under money formatting; must read as 45%.
    assert format_scalar("net_margin", 0.45) == "45%"
    assert format_scalar("sweet_net_margin", 0.3) == "30%"


def test_negative_net_margin_keeps_sign():
    # refund can exceed conversion → a negative net margin must not collapse to 0.
    assert format_scalar("net_margin", -0.05) == "-5%"


def test_marginal_roas_still_not_percent():
    # regression guard: removing the _margin money suffix must not touch _roas.
    assert not is_percent_field("marginal_roas")
