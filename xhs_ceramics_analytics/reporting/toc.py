"""Shared persistent (常驻) pure-CSS table of contents for both HTML reports.

Both single-file reports — the Jinja fact layer (``report.html.j2``) and the
hand-rolled narrative document (``render_markdown_document_html``) — mount the
SAME TOC: a sticky rail that renders as a left column on wide viewports and a
sticky top strip on narrow ones (honouring the reader's "顶部或者左侧都可以"), with
in-page anchor links and ``scroll-behavior: smooth`` for the anchored scroll.

Why CSS-only: the single-file HTML contract forbids ``<script>`` (enforced by
``tests/test_report_rendering.py::test_html_report_has_no_script_or_external_refs``),
so there is no scroll-spy / active-section highlight — that needs JavaScript.
Persistence + click-to-anchor-scroll is fully achievable with ``position: sticky``
plus anchor links, which is what this module ships.

``build_toc_nav`` is pure and never raises: any malformed entry list degrades to
``""`` (no rail) rather than breaking a report render — the same never-raise /
graceful-degradation contract every reporting module honours. ``TOC_STYLE`` uses
ONLY the six design tokens common to both renderers
(``--canvas --surface --ink --ink-strong --muted --line``) so a single CSS string
is safe to inject into either ``<style>`` block.
"""
from __future__ import annotations

from html import escape

# The fixed left-rail width on wide viewports. Exposed so callers can reason about
# the content column, though the value is baked into TOC_STYLE below.
TOC_RAIL_WIDTH = "232px"

# Viewport at/above which the rail moves from a top strip to a left column. Kept in
# one place so both the grid switch and any caller stay in sync.
TOC_WIDE_BREAKPOINT = "1200px"


def build_toc_nav(
    entries: object, *, title: str = "目录", aria_label: str = "报告目录"
) -> str:
    """Render an ordered entry list into the shared ``<nav class="toc-rail">``.

    ``entries`` is an ordered iterable of ``{"level": 2|3, "anchor": str,
    "label": str}`` dicts. Level-3 entries nest under the most recent level-2 as
    ``<ul class="toc-sub">`` sub-items; a level-3 with no preceding level-2 is
    promoted to a top-level item so it is never silently dropped.

    Returns ``""`` when there is nothing valid to show. Never raises — a garbage
    argument degrades to an empty string.
    """
    try:
        return _build_toc_nav(entries, title=title, aria_label=aria_label)
    except Exception:
        return ""


def _build_toc_nav(entries: object, *, title: str, aria_label: str) -> str:
    items = _normalize_entries(entries)
    if not items:
        return ""

    # Group into top-level items, each owning the run of level-3 entries that
    # follow it. An orphan level-3 (no open group yet) opens its own top group.
    groups: list[dict[str, object]] = []
    for entry in items:
        if entry["level"] <= 2 or not groups:
            groups.append({"top": entry, "subs": []})
        else:
            subs = groups[-1]["subs"]
            assert isinstance(subs, list)
            subs.append(entry)

    rendered: list[str] = []
    for group in groups:
        top = group["top"]
        assert isinstance(top, dict)
        parts = [
            f'<li class="toc-item">{_link(top, "toc-link--top")}'
        ]
        subs = group["subs"]
        assert isinstance(subs, list)
        if subs:
            parts.append('<ul class="toc-sub">')
            for sub in subs:
                parts.append(f'<li class="toc-subitem">{_link(sub, "toc-link--sub")}</li>')
            parts.append("</ul>")
        parts.append("</li>")
        rendered.append("".join(parts))

    return (
        f'<nav class="toc-rail" aria-label="{escape(aria_label, quote=True)}">'
        f'<p class="toc-rail__title">{escape(title)}</p>'
        f'<ul class="toc-list">{"".join(rendered)}</ul>'
        f"</nav>"
    )


def _link(entry: dict[str, object], variant: str) -> str:
    anchor = escape(str(entry["anchor"]), quote=True)
    label = escape(str(entry["label"]))
    return f'<a class="toc-link {variant}" href="#{anchor}">{label}</a>'


def _normalize_entries(entries: object) -> list[dict[str, object]]:
    if not isinstance(entries, (list, tuple)):
        return []
    result: list[dict[str, object]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        anchor = raw.get("anchor")
        label = raw.get("label")
        if not isinstance(anchor, str) or not isinstance(label, str):
            continue
        anchor = anchor.strip()
        label = label.strip()
        if not anchor or not label:
            continue
        result.append({"level": _coerce_level(raw.get("level", 2)), "anchor": anchor, "label": label})
    return result


def _coerce_level(value: object) -> int:
    try:
        level = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 2
    if level <= 2:
        return 2
    return 3


# The one shared stylesheet fragment (no ``<style>`` wrapper — the caller injects it
# into its own block). Uses only the six tokens both renderers define. Mobile-first:
# the rail defaults to a sticky top strip; at the wide breakpoint it becomes a fixed
# left column. Widths are driven by ``--toc-*`` custom properties so each renderer can
# tune them without forking this string.
TOC_STYLE = """
    html { scroll-behavior: smooth; }

    .page-grid {
      --toc-rail-w: 232px;
      --toc-gap: 44px;
      /* Mobile-first gutter; the wide breakpoint below bumps it to 40px. Renderers
         override only the --toc-content widths, never --toc-pad, so this responsive
         value is never shadowed by a later unconditional rule. */
      --toc-pad: 24px;
      --toc-content: 1100px;
      --toc-content-wide: 1320px;
      position: relative;
      z-index: 1;
      width: min(var(--toc-content), calc(100% - var(--toc-pad)));
      margin: 0 auto;
    }

    /* Anchor targets clear the sticky top strip when jumped to. The extra headroom
       (92px, not the strip's ~72px overlay height) absorbs a classic horizontal
       scrollbar that can appear on the nowrap strip on Windows/Linux. */
    :where(h1, h2, h3, h4, section, article)[id] { scroll-margin-top: 92px; }

    .toc-rail {
      position: sticky;
      top: 0;
      z-index: 30;
      background: var(--canvas);
      border-bottom: 1px solid var(--line);
      padding: 10px 0;
      margin: 0 0 10px;
    }

    .toc-rail__title {
      margin: 0 0 6px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
    }

    .toc-list {
      list-style: none;
      margin: 0;
      padding: 0;
      display: flex;
      flex-wrap: nowrap;
      gap: 4px 18px;
      overflow-x: auto;
    }

    .toc-item { flex: 0 0 auto; }

    /* Nested sub-entries stay hidden on the narrow top strip (top-level only). */
    .toc-sub { display: none; }

    .toc-link {
      display: inline-block;
      padding: 4px 0;
      color: var(--muted);
      text-decoration: none;
      font-size: 13px;
      line-height: 1.45;
      white-space: nowrap;
      border: 0;
      transition: color 160ms ease;
    }

    .toc-link:hover { color: var(--ink-strong); }

    .toc-link--top { color: var(--ink); font-weight: 600; }

    @media (min-width: 1200px) {
      .page-grid {
        display: grid;
        grid-template-columns: var(--toc-rail-w) minmax(0, 1fr);
        column-gap: var(--toc-gap);
        align-items: start;
        --toc-pad: 40px;
        width: min(var(--toc-content-wide), calc(100% - var(--toc-pad)));
      }

      /* The content cell fills its column; width/centering now belongs to .page-grid. */
      .page-grid > .report-shell,
      .page-grid > main { width: auto; margin: 0; }

      .toc-rail {
        top: 0;
        max-height: 100vh;
        overflow-y: auto;
        background: transparent;
        border-bottom: 0;
        padding: 44px 0;
        margin: 0;
      }

      :where(h1, h2, h3, h4, section, article)[id] { scroll-margin-top: 28px; }

      .toc-list {
        flex-direction: column;
        flex-wrap: nowrap;
        gap: 2px;
        overflow-x: visible;
      }

      .toc-item { flex: none; }

      .toc-sub {
        display: block;
        list-style: none;
        margin: 2px 0 10px;
        padding: 0 0 0 12px;
        border-left: 1px solid var(--line);
      }

      .toc-link { white-space: normal; }

      .toc-link--sub { font-size: 12px; padding: 3px 0; }
    }

    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
    }
"""
