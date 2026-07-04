"""Reader-facing number/date formatting for analysis *prose* (conclusion sentences).

Tables already route every cell through ``reporting.formatting.format_scalar``.
The conclusion sentence that leads each finding used to build its numbers with
bare ``round()`` / f-strings, so the same value read one way in the headline
(``1302239``, ``20260628``, ``diff=-0.8pct``) and another in the table
(``1,302,239``, ``2026-06-28``, ``-0.77%``). These helpers make prose share the
SAME primitives as the table path (``reporting.labels``), so a number reads
identically wherever it appears.
"""
from __future__ import annotations

from xhs_ceramics_analytics.reporting.labels import format_cn_date, format_number


def money(value: float | None) -> str:
    """Grouped yuan amount, rounded to whole yuan: ``1302239.01`` -> ``1,302,239``."""
    return format_number(float(round(value or 0)))


def qty(value: float | None) -> str:
    """Grouped count: ``1272`` -> ``1,272``; small counts pass through unchanged."""
    return format_number(float(round(value or 0)))


def pp(value: float | None) -> str:
    """Percentage-point difference in plain language: ``-0.008`` -> ``-0.8 个百分点``.

    Replaces the machine tokens ``pp`` / ``diff=…pct`` that used to leak into
    reader prose. Keeps the sign so the direction of the gap is preserved.
    """
    points = (value or 0) * 100
    text = f"{points:.1f}".rstrip("0").rstrip(".")
    return f"{text} 个百分点"


def cn_date(value: object) -> str:
    """ISO date for prose; unparseable values fall back to their string form."""
    iso = format_cn_date(value)
    return iso if iso is not None else str(value)
