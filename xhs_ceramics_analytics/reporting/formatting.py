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
    format_cn_date,
    format_money,
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
# ``gmv_ci_low`` etc. so it stays money. ``diff`` earns its place the same way:
# both producers (audience_structure, search_efficiency) use it for a
# conversion/effectiveness gap, so it is a rate everywhere. ``delta`` is
# deliberately absent: it is polymorphic (GMV yuan in core_business, rate-points
# in the refund/search trends), so each trend renames its column to a
# unit-bearing name (``gmv_delta`` = money,
# ``refund_rate_delta``/``avg_pay_conversion_delta`` = rate-points) rather than
# overloading one ambiguous key.
PERCENT_FIELDS = {
    "audience_diff",
    "avg_pay_conversion",
    "avg_pay_conversion_delta",
    "baseline_conversion",
    "baseline_effectiveness",
    "card_conversion",
    "channel_diff",
    "cart_to_pay",
    "ci_band",
    "ci_high",
    "ci_low",
    "click_baseline",
    "confidence_weight",
    "conv_diff",
    "conversion",
    "conversion_baseline",
    "conversion_gap",
    "ctr_calc",
    "diff",
    "effectiveness",
    "effectiveness_high",
    "effectiveness_low",
    "net_margin",  # 加购转化率 − 退款率 (percentage-point diff), NOT money
    "new_customer_dependence",
    "note_conversion",
    "overall_cart_to_pay",
    "overall_conversion",
    "pay_conversion",
    "pct",
    "rate",
    "read_gap_to_max",
    "refund_diff",
    "refund_rate_delta",
    "relative_lift",
    "repeat_conversion_premium",
    "second_conversion",
    "share",
    "sweet_net_margin",  # 甜点带 net_margin (same ratio caliber)
    "top_conversion",
    "wishlist_to_cart_ratio",
    "wilson_high",
    "wilson_low",
}

# ``_rate`` covers refund/read/like/etc. rates; ``_share`` covers every mix/gmv/
# visitor/order proportion; ``_pct`` covers period-over-period change fractions
# (e.g. ``wow_last_pct``); ``_rate_pay`` covers refund rates that carry the
# 支付时间 caliber marker (e.g. ``post_ship_refund_rate_pay``) whose trailing
# ``_pay`` would otherwise hide the ``_rate`` from the suffix test. All denote
# 0-1 fractions rendered as percents.
PERCENT_SUFFIXES = ("_rate", "_share", "_pct", "_rate_pay", "_mde")

# Money amounts render as whole yuan (matching analysis.prose.money) so a summed
# GMV/spend/refund reads ``1,302,239`` not ``1,302,239.01`` — the trailing cents are
# export noise, not signal, and the prose path already drops them. Kept as an explicit
# allow-list like PERCENT_FIELDS, NOT a fuzzy money-token match: an omission only leaves
# a money field at the old 2-decimal display (harmless), whereas a false positive would
# round a ratio/index (``gmv_gini`` 0.42, ``marginal_roas`` 4.4) to a meaningless integer.
# Percent detection runs first, so ``gmv_share``/``amount_share`` never reach here.
MONEY_FIELDS = {
    "gmv",
    "aov",
    "aov_low",  # AOV/price-band boundaries (yuan)
    "aov_high",
    "spend",
    "price",
    "gmv_delta",
    "gmv_total",
    "gmv_optional",
    "net_gmv_pay",
    "refund_amount_pay",
    "contribution",  # LMDI GMV-bridge factor contribution (yuan)
    "contrib_traffic",
    "contrib_conversion",
}
# ``_gmv`` (note/card/net/total/... gmv), ``_amount`` (refund/paid amounts), ``_spend``
# (total/avg/break-even spend), ``_aov`` (note/card/median/contrib aov). ``_margin`` is
# deliberately NOT here: the only ``*_margin`` fields (net_margin / sweet_net_margin) are
# 加购转化率−退款率 ratios and live in PERCENT_FIELDS — treating them as money rounded a
# real 0.45 to "0". None of these suffixes reach a ratio/index — ``gmv_gini`` ends
# ``_gini``, ``marginal_roas`` ends ``_roas``, ``gmv_universe`` ends ``_universe``.
MONEY_SUFFIXES = ("_gmv", "_amount", "_spend", "_aov")

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


def is_money_field(field_name: str) -> bool:
    return field_name in MONEY_FIELDS or field_name.endswith(MONEY_SUFFIXES)


def is_date_field(field_name: str) -> bool:
    return field_name in DATE_FIELDS or field_name.endswith("_date")


def is_timeseries_table(table_name: str, columns: list[str]) -> bool:
    """Whether a table is a per-period time series best shown as a chart, not a grid.

    A wide trend table read row-by-row is noise — the reader wants the line, not the
    numbers. Two cheap signals: a ``_trend`` table name, or a leading date column
    (reusing :func:`is_date_field`). Callers force such tables collapsed regardless of
    row count so the chart leads. Pure and never-raise.
    """
    if table_name.endswith("_trend"):
        return True
    return bool(columns) and is_date_field(columns[0])


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
    a label like 上新日). Delegates to the shared normalizer so the table path and
    the prose path (analysis.prose.cn_date) hyphenate dates identically."""
    return format_cn_date(value)


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
        if field_name == "relative_lift" or field_name.endswith("_rel_lift"):
            if numeric > 0:
                return f"提升 {format_percent(numeric)}"
            if numeric < 0:
                return f"下降 {format_percent(abs(numeric))}"
            return "持平 0%"
        if is_percent_field(field_name):
            return format_percent(numeric)
        # Money to whole yuan (shared format_money primitive) — checked after percent
        # so *_share/*_amount_share concentrations stay percents.
        if is_money_field(field_name):
            return format_money(numeric)
        return format_number(numeric)
    return str(value)


def should_render_table(rows: list[dict] | None) -> bool:
    """Whether a table has rows worth rendering. Empty tables become no-ops in
    both renderers instead of hollow 0-row shells."""
    return bool(rows)
