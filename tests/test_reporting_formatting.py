"""Unified scalar formatter shared by the markdown + HTML renderers.

The two renderers used to format independently — HTML had a rich cell formatter
while markdown dumped raw ``str(value)``. This locks the single source of truth
so a date, percent or money value reads identically in both deliverables.
"""
from xhs_ceramics_analytics.reporting.formatting import (
    field_help,
    field_label,
    format_scalar,
    should_render_table,
)


def test_format_scalar_percent_field():
    assert format_scalar("collect_rate", 0.041666666) == "4.17%"


def test_format_scalar_rate_suffix_is_percent():
    # any *_rate field is a percent even if not in the explicit set
    assert format_scalar("refund_rate", 0.18) == "18%"


def test_format_scalar_share_suffix_is_percent():
    # every *_share field is a proportion — must render as a percent, not 0.64
    assert format_scalar("dominant_gmv_share", 0.64) == "64%"
    assert format_scalar("converting_share", 0.27) == "27%"
    assert format_scalar("mix_share", 0.5) == "50%"


def test_format_scalar_conversion_family_is_percent():
    # conversion rates / baselines / rate-diffs are 0-1 fractions; render as percent
    assert format_scalar("note_conversion", 0.03) == "3%"
    assert format_scalar("card_conversion", 0.05) == "5%"
    assert format_scalar("conversion", 0.11) == "11%"
    assert format_scalar("conversion_baseline", 0.11) == "11%"
    assert format_scalar("baseline_conversion", 0.02) == "2%"
    assert format_scalar("new_customer_dependence", 0.71) == "71%"
    assert format_scalar("cart_to_pay", 0.4) == "40%"
    # rate differences render as (signed) percent, not raw -0.02
    assert format_scalar("conv_diff", -0.02) == "-2%"
    assert format_scalar("refund_diff", -0.02) == "-2%"


def test_format_scalar_bare_proportion_columns_are_percent():
    # rate/share/effectiveness/ci bounds/avg_pay_conversion denote 0-1 fractions
    # in every producer, so the shared renderer must scale them to percents.
    assert format_scalar("rate", 0.73) == "73%"
    assert format_scalar("share", 0.62) == "62%"
    assert format_scalar("effectiveness", 0.01) == "1%"
    assert format_scalar("avg_pay_conversion", 0.06) == "6%"
    assert format_scalar("ci_low", 0.72) == "72%"
    assert format_scalar("ci_high", 0.74) == "74%"


def test_format_scalar_wilson_and_pay_conversion_are_percent():
    # Wilson CI bounds and the store-wide pay conversion are rate-scale.
    assert format_scalar("wilson_low", 0.01) == "1%"
    assert format_scalar("wilson_high", 0.02) == "2%"
    assert format_scalar("pay_conversion", 0.05) == "5%"


def test_format_scalar_caliber_suffixed_refund_rates_are_percent():
    # The 支付时间-caliber ``_rate_pay`` family is still a rate despite the
    # trailing caliber marker that hides the ``_rate`` suffix.
    assert format_scalar("refund_rate_pay", 0.27) == "27%"
    assert format_scalar("note_refund_rate_pay", 0.4) == "40%"
    assert format_scalar("pre_ship_refund_rate_pay", 0.2) == "20%"
    assert format_scalar("post_ship_refund_rate_pay", 0.06) == "6%"
    # p_value is a probability, NOT a percent — it must stay a bare decimal.
    assert format_scalar("p_value", 0.03) == "0.03"


def test_format_scalar_delta_columns_respect_their_unit():
    # ``delta`` is polymorphic, so each trend renames its column: the GMV delta
    # is money (must NOT be ×100 into a percent), the rate deltas are percent-scale.
    assert format_scalar("gmv_delta", 1234.5) == "1,234.5"
    assert format_scalar("refund_rate_delta", 0.05) == "5%"
    assert format_scalar("avg_pay_conversion_delta", -0.03) == "-3%"


def test_format_scalar_conversion_counts_and_source_are_not_percent():
    # look-alike fields that are NOT rates must stay counts / text
    assert format_scalar("conversion_universe", 3991) == "3,991"
    assert format_scalar("gmv_universe", 3405) == "3,405"
    assert format_scalar("conversion_source", "count") == "count"


def test_format_scalar_money_fields_never_become_percent():
    # money that happens to end in _pay or resemble a rate must stay a number
    assert format_scalar("net_gmv_pay", 1234.5) == "1,234.5"
    assert format_scalar("note_gmv", 903.0) == "903"


def test_format_scalar_relative_lift_signed():
    assert format_scalar("relative_lift", -0.333333333) == "下降 33.3%"
    assert format_scalar("relative_lift", 0.2) == "提升 20%"
    assert format_scalar("relative_lift", 0.0) == "持平 0%"


def test_format_scalar_money_and_plain_number():
    assert format_scalar("gmv", 903.0) == "903"
    assert format_scalar("units", 7) == "7"


def test_format_scalar_bool_and_none():
    assert format_scalar("needs_more_data", False) == "否"
    assert format_scalar("needs_more_data", True) == "是"
    assert format_scalar("anything", None) == "暂无数据"


def test_format_scalar_value_label_lookup():
    assert format_scalar("opportunity_type", "sales_response_present") == "已有销售反馈"


def test_format_scalar_list_joins_with_chinese_comma():
    assert format_scalar("tags", ["gift", "price"]) == "送礼角度、价格需求"


def test_format_scalar_date_field_hyphenates_integer_yyyymmdd():
    # Real exports carry date as integer 20260401 — a money formatter would render
    # "20,260,401". The date branch must hyphenate it instead.
    assert format_scalar("date", 20260401) == "2026-04-01"
    assert format_scalar("date", 20260401.0) == "2026-04-01"


def test_format_scalar_date_field_passes_iso_through():
    assert format_scalar("period", "2026-07-01") == "2026-07-01"


def test_format_scalar_date_field_non_date_value_degrades():
    # a date-named field carrying junk must not crash — fall back to string
    assert format_scalar("date", "上新日") == "上新日"


def test_format_scalar_date_field_numeric_non_date_is_not_comma_mangled():
    # a numeric value in a date-named field that isn't an 8-digit YYYYMMDD must
    # not be grouped like money ("2,026"); render the bare digits instead.
    assert format_scalar("date", 2026) == "2026"
    assert format_scalar("period", 202604) == "202604"


def test_field_label_known_and_unknown():
    assert field_label("gmv") == "销售额"
    assert field_label("totally_unknown_col") == "totally unknown col"


def test_field_help_unknown_has_generic_note():
    assert "追溯" in field_help("totally_unknown_col")


def test_should_render_table_skips_empty():
    assert should_render_table([{"a": 1}]) is True
    assert should_render_table([]) is False
