"""Self-referential benchmark primitives — anchor a metric to its own history.

This shop has no external industry baseline, so "2% conversion" means nothing on
its own. What is checkable is where a value sits inside the account's *own* recent
distribution: a P90 week is a good week for this shop regardless of what the
category does. These pure-stdlib helpers turn a raw value + history into a
percentile anchor. Degenerate input (empty history, NaN, None) degrades to None
rather than raising.
"""
from xhs_ceramics_analytics.analytics.numeric import is_finite_number as _is_finite


def self_percentile(value: float | None, history: list[float | None]) -> float | None:
    """Midrank percentile of ``value`` within ``history``, in ``[0, 1]``.

    Uses the midrank ("mean") convention: percentile =
    ``(#below + 0.5 * #equal) / n``. This places a value that ties every point at
    exactly ``0.5`` (it is neither high nor low for this account) and is stable
    under duplicate history — the plain "#≤ / n" rule would score a typical value
    as a top performer. ``None``/non-finite entries in ``history`` are dropped
    before ranking. Returns ``None`` when ``value`` is missing/non-finite or the
    cleaned history is empty. Never raises.
    """
    if not _is_finite(value):
        return None
    clean = [float(v) for v in history if _is_finite(v)]
    n = len(clean)
    if n == 0:
        return None
    below = sum(1 for v in clean if v < value)
    equal = sum(1 for v in clean if v == value)
    return (below + 0.5 * equal) / n


def percentile_label(percentile: float | None) -> str | None:
    """Reader-facing ``P__`` tag for a ``self_percentile`` result (e.g. ``P90``).

    Rounds to the nearest whole percentile so a 0.904 reads as ``P90``. Returns
    ``None`` when the percentile is missing. Never raises.
    """
    if percentile is None or not _is_finite(percentile):
        return None
    pct = max(0, min(100, round(percentile * 100)))
    return f"P{pct}"
