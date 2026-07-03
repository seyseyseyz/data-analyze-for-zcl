"""Month-period bucketing for 千帆 exports.

Two time representations exist in the real data: int ``YYYYMMDD`` (daily report
tables) and local timestamp strings (``笔记创建时间``). Both bucket to a naive
``YYYY-MM`` string with no timezone math.
"""
import calendar


def to_period_month(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        text = str(value)
    else:
        text = str(value).strip()
    if not text:
        return None
    if text.isdigit() and len(text) == 8:
        return f"{text[:4]}-{text[4:6]}"
    normalized = text.replace("/", "-")
    parts = normalized.split("-")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1][:2].isdigit():
        year = int(parts[0])
        month = int(parts[1][:2])
        if 1 <= month <= 12 and year > 0:
            return f"{year:04d}-{month:02d}"
    return None


def month_bounds(period: str) -> tuple[int, int]:
    year, month = (int(part) for part in period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    start = year * 10000 + month * 100 + 1
    end = year * 10000 + month * 100 + last_day
    return (start, end)


def period_month_expr(column: str) -> str:
    """SQL that buckets a date column to a ``'YYYY-MM'`` string.

    Handles both representations in the export: int ``YYYYMMDD`` (daily report
    tables, no separators) and ISO date/timestamp columns (``2026-04-01`` /
    ``2026-04-01 21:11:20``). Detection is by the presence of a ``-`` separator
    in the text form: ISO forms take the first 7 chars; int forms splice.
    """
    text = f"CAST({column} AS VARCHAR)"
    return (
        f"CASE WHEN strpos({text}, '-') > 0 THEN substr({text}, 1, 7) "
        f"ELSE substr({text}, 1, 4) || '-' || substr({text}, 5, 2) END"
    )
