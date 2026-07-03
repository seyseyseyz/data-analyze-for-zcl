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


def test_field_label_known_and_unknown():
    assert field_label("gmv") == "销售额"
    assert field_label("totally_unknown_col") == "totally unknown col"


def test_field_help_unknown_has_generic_note():
    assert "追溯" in field_help("totally_unknown_col")


def test_should_render_table_skips_empty():
    assert should_render_table([{"a": 1}]) is True
    assert should_render_table([]) is False
