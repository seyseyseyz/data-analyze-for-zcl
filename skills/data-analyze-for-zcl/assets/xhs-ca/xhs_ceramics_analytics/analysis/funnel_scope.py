"""Shared ``shop_page_funnel`` scope normalization.

``shop_page_funnel`` carries a platform ``全部`` rollup row (= 新客 + 老客) and
cumulative first-purchase windows (180天 ⊂ 365天). Naively summing every row
double-counts visitors, and treating ``全部`` as a peer segment turns a
two-proportion test into a subset-vs-superset comparison. Both ``core_business``
and ``audience_structure`` consume this single normalization so the store-funnel
caliber is defined in exactly one place.
"""

ROLLUP = "全部"


def canonical_cycle(cycles) -> str | None:
    """Pick a single cumulative first-purchase window to avoid double-counting.

    Numeric windows are nested (180天 ⊂ 365天); summing both counts the same
    visitors twice, so we keep the widest window present (largest embedded
    number). Returns ``None`` when no label carries a number — non-numeric cycle
    labels are treated as ordinary buckets and left un-deduplicated.
    """
    numbered = []
    for c in cycles:
        digits = "".join(ch for ch in str(c) if ch.isdigit())
        if digits:
            numbered.append((int(digits), c))
    if numbered:
        return max(numbered, key=lambda t: t[0])[1]
    return None


def normalize_funnel_rows(
    rows: list[dict], has_audience: bool, has_cycle: bool
) -> tuple[list[dict], list[dict], str | None]:
    """Split rollup rows out and collapse cumulative windows to one canonical window.

    Returns ``(segment_rows, rollup_rows, canonical_cycle)``:
    - ``segment_rows``: real audience segments (rollup removed) restricted to the
      widest first-purchase window so 180天/365天 never double-count.
    - ``rollup_rows``: the ``全部`` rows, kept separately for a true store-wide total.
    - ``canonical_cycle``: the window kept, or ``None`` when no numeric window exists.
    """
    rollup_rows = [r for r in rows if has_audience and r.get("audience_type") == ROLLUP]
    segment_rows = [
        r for r in rows if not (has_audience and r.get("audience_type") == ROLLUP)
    ]
    canonical: str | None = None
    if has_cycle:
        cycle_vals = [
            r.get("first_purchase_cycle")
            for r in segment_rows
            if r.get("first_purchase_cycle") not in (None, ROLLUP)
        ]
        canonical = canonical_cycle(cycle_vals)
        if canonical is not None:
            segment_rows = [
                r for r in segment_rows if r.get("first_purchase_cycle") == canonical
            ]
    return segment_rows, rollup_rows, canonical
