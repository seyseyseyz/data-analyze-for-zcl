"""Unified reader-facing value formatting shared by both report renderers.

The markdown and HTML renderers used to format independently — HTML had a rich
cell formatter while markdown dumped raw ``str(value)``. That divergence let the
same value read differently across the two deliverables, and it mangled the
integer ``YYYYMMDD`` dates real exports carry (a money formatter turned
``20260401`` into ``"20,260,401"``). This module is the single source of truth:
one scalar formatter, one field vocabulary, one empty-table gate.
"""
from __future__ import annotations

from numbers import Number

from xhs_ceramics_analytics.reporting.field_labels import FIELD_LABELS
from xhs_ceramics_analytics.reporting.labels import (
    VALUE_LABELS,
    format_number,
    format_percent,
)

# Proportions/rates that are 0-1 fractions but whose names don't carry the
# ``_rate``/``_share`` suffix the predicate keys off. Kept explicit (not a
# blanket ``conversion`` substring) so look-alike counts/text — conversion_source
# (enum), conversion_universe/gmv_universe (SKU counts) — are never mis-scaled.
#
# The contract this set relies on: a column name maps to exactly one unit across
# the whole codebase. ``ci_low``/``ci_high`` are here because every producer uses
# them to bound a *rate* — a future CI over money/counts must be named
# ``gmv_ci_low`` etc. so it stays money. ``delta`` is deliberately absent: it is
# polymorphic (GMV yuan in core_business, rate-points in the refund/search
# trends), so each trend renames its column to a unit-bearing name
# (``gmv_delta`` = money, ``refund_rate_delta``/``avg_pay_conversion_delta`` =
# rate-points) rather than overloading one ambiguous key.
PERCENT_FIELDS = {
    "avg_pay_conversion",
    "avg_pay_conversion_delta",
    "baseline_conversion",
    "baseline_effectiveness",
    "card_conversion",
    "cart_to_pay",
    "ci_high",
    "ci_low",
    "click_baseline",
    "confidence_weight",
    "conv_diff",
    "conversion",
    "conversion_baseline",
    "ctr_calc",
    "effectiveness",
    "effectiveness_high",
    "effectiveness_low",
    "new_customer_dependence",
    "note_conversion",
    "overall_cart_to_pay",
    "pay_conversion",
    "pct",
    "rate",
    "read_gap_to_max",
    "refund_diff",
    "refund_rate_delta",
    "relative_lift",
    "repeat_conversion_premium",
    "share",
    "wilson_high",
    "wilson_low",
}

# ``_rate`` covers refund/read/like/etc. rates; ``_share`` covers every mix/gmv/
# visitor/order proportion; ``_pct`` covers period-over-period change fractions
# (e.g. ``wow_last_pct``); ``_rate_pay`` covers refund rates that carry the
# 支付时间 caliber marker (e.g. ``post_ship_refund_rate_pay``) whose trailing
# ``_pay`` would otherwise hide the ``_rate`` from the suffix test. All denote
# 0-1 fractions rendered as percents.
PERCENT_SUFFIXES = ("_rate", "_share", "_pct", "_rate_pay")

# Fields whose values denote a calendar day. Real exports carry these as integer
# YYYYMMDD, ISO strings, or datetime — the date branch normalizes all to ISO.
DATE_FIELDS = {
    "date",
    "day",
    "period",
    "week_start",
    "week_end",
    "start_period",
    "end_period",
}


def is_percent_field(field_name: str) -> bool:
    return field_name in PERCENT_FIELDS or field_name.endswith(PERCENT_SUFFIXES)


def is_date_field(field_name: str) -> bool:
    return field_name in DATE_FIELDS or field_name.endswith("_date")


def field_label(field_name: str) -> str:
    label = FIELD_LABELS.get(field_name)
    if label is not None:
        return label[0]
    return field_name.replace("_", " ")


def field_help(field_name: str) -> str:
    label = FIELD_LABELS.get(field_name)
    if label is not None:
        return label[1]
    return "原始数据字段，保留用于查数和追溯。"


def _format_date(value: object) -> str | None:
    """Best-effort ISO date; returns None when ``value`` is not a date so the
    caller can fall back to normal formatting (a date-named field may still carry
    a label like 上新日)."""
    text = str(value).strip()
    if "-" in text or "/" in text:
        return text[:10].replace("/", "-")
    digits = text.split(".", maxsplit=1)[0]  # 20260401.0 -> 20260401
    if len(digits) == 8 and digits.isdigit():
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return None


def format_scalar(field_name: str, value: object) -> str:
    """Render one value the way a business reader should see it.

    Percent fields → ``4.17%``; ``relative_lift`` → signed 提升/下降; date fields →
    ISO; booleans → 是/否; known enum strings → their Chinese label; everything
    numeric → grouped number. Lists/tuples join with the Chinese comma. Never
    raises — unknown shapes degrade to ``str(value)``.
    """
    if isinstance(value, (list, tuple)):
        return "、".join(format_scalar(field_name, item) for item in value)
    if value is None:
        return "暂无数据"
    if isinstance(value, bool):
        return "是" if value else "否"
    if is_date_field(field_name) and not isinstance(value, bool):
        iso = _format_date(value)
        if iso is not None:
            return iso
        # A date-named field carrying a bare numeric (year 2026, month 202604)
        # must not be money-grouped into "2,026"; show the plain digits.
        if isinstance(value, Number):
            numeric = float(value)
            return str(int(numeric)) if numeric.is_integer() else str(value)
    if isinstance(value, str):
        return VALUE_LABELS.get(value, value)
    if isinstance(value, Number):
        numeric = float(value)
        if field_name == "relative_lift":
            if numeric > 0:
                return f"提升 {format_percent(numeric)}"
            if numeric < 0:
                return f"下降 {format_percent(abs(numeric))}"
            return "持平 0%"
        if is_percent_field(field_name):
            return format_percent(numeric)
        return format_number(numeric)
    return str(value)


def should_render_table(rows: list[dict] | None) -> bool:
    """Whether a table has rows worth rendering. Empty tables become no-ops in
    both renderers instead of hollow 0-row shells."""
    return bool(rows)
