"""Shared numeric-coercion gate — the single finiteness/cast check for analytics.

Every analytics primitive owes the same contract: degrade, never raise, on dirty
input. Dirty means ``None``, ``bool``, ``NaN``/``inf``, and would-be-numeric strings
that ``read_csv_auto`` leaves as text — thousands separators (``"1,234"``), a leading
currency mark (``"¥1200"``), a trailing percent (``"12%"``), or sentinels (``"—"``,
``"N/A"``, ``""``). Historically each module reimplemented its own check and they
drifted: some rejected strings, others let them reach ``float()`` and crash. This
module is the one correct implementation every primitive and wiring helper defers to.
Pure stdlib.
"""
import math

# Marks stripped before parsing a numeric string. The percent sign is removed but
# NOT rescaled — the /100 rate convention belongs to the caller (see ``bounded_rate``).
_STRIP_MARKS = (",", "，", "¥", "￥", "$", "%", " ", "\t")


def is_finite_number(value) -> bool:
    """True only for a real, finite number (rejects None, bool, str, NaN, inf)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(value)


def to_finite_float(value, default: float | None = None) -> float | None:
    """Coerce ``value`` to a finite float, or return ``default`` — never raises.

    Accepts real finite numbers and numeric strings, tolerating thousands
    separators, a leading currency mark, surrounding whitespace, and a trailing
    percent sign (stripped, not rescaled). ``None``, booleans, non-finite floats,
    and non-numeric strings/sentinels return ``default``.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else default
    if isinstance(value, str):
        text = value.strip()
        for mark in _STRIP_MARKS:
            text = text.replace(mark, "")
        if not text:
            return default
        try:
            num = float(text)
        except ValueError:
            return default
        return num if math.isfinite(num) else default
    return default
