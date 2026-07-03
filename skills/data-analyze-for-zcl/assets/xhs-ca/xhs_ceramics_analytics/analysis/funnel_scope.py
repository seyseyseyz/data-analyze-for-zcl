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
    - ``segment_rows``: real audience segments (rollup removed), each collapsed to
      *its own* widest first-purchase window so 180天/365天 never double-count.
      Collapsing per-segment (not to one global window) means a segment that only
      reports a narrower window is kept, never silently dropped — otherwise the
      audience comparison this layer exists to enable would lose a group.
    - ``rollup_rows``: the ``全部`` rows, kept separately for a true store-wide total.
    - ``canonical_cycle``: the widest window kept across segments, or ``None`` when
      no numeric window exists (used only for the reader-facing caveat).
    """
    rollup_rows = [r for r in rows if has_audience and r.get("audience_type") == ROLLUP]
    segment_rows = [
        r for r in rows if not (has_audience and r.get("audience_type") == ROLLUP)
    ]
    canonical: str | None = None
    if has_cycle:
        segments: dict[object, list[dict]] = {}
        for r in segment_rows:
            key = r.get("audience_type") if has_audience else None
            segments.setdefault(key, []).append(r)

        kept: list[dict] = []
        kept_cycles: list[str] = []
        for seg_rows in segments.values():
            seg_cycles = [
                r.get("first_purchase_cycle")
                for r in seg_rows
                if r.get("first_purchase_cycle") not in (None, ROLLUP)
            ]
            seg_canonical = canonical_cycle(seg_cycles)
            if seg_canonical is None:
                # No numeric window for this segment — leave its rows untouched.
                kept.extend(seg_rows)
            else:
                kept.extend(
                    r for r in seg_rows if r.get("first_purchase_cycle") == seg_canonical
                )
                kept_cycles.append(seg_canonical)
        segment_rows = kept
        canonical = canonical_cycle(kept_cycles) if kept_cycles else None
    return segment_rows, rollup_rows, canonical
