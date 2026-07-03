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

PERCENT_FIELDS = {
    "avg_collect_rate",
    "avg_comment_rate",
    "avg_like_rate",
    "avg_read_rate",
    "collect_rate",
    "comment_rate",
    "comment_share",
    "confidence_weight",
    "ctr_calc",
    "like_rate",
    "mix_share",
    "pct",
    "read_gap_to_max",
    "read_rate",
    "relative_lift",
}

MONEY_FIELDS = {
    "cost_per_order_calc",
    "cpc_calc",
    "cpm_calc",
    "gmv",
    "gmv_optional",
    "paid_amount",
    "price",
    "spend",
    "total_spend",
}

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
    return field_name in PERCENT_FIELDS or field_name.endswith("_rate")


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
