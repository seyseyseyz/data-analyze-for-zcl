"""Shared chart + curated-view CSS for the narrative HTML report.

The narrative document (``reporting.html.render_markdown_document_html``) injects
auto-charts and curated tables that carry the same class contract as the Jinja
fact report — ``<svg class="chart-svg">`` (from ``charts.render_chart_template``),
the top-N ``<details class="ca-table-fold">`` fold, and ``<tr class="ca-row-highlight">``
rows (from ``reporting.curated_view``). But the narrative ``<style>`` never styled
any of them, so axis/grid strokes rendered invisible (SVG ``stroke`` defaults to
none), category/number ``<text>`` was unsized default-black, and the fold + row
carried no visual treatment. ``CHART_STYLE`` is the one string that fixes all of
that, ported from ``templates/report.html.j2`` so a narrative chart reads
identically to a fact-report chart.

Why a shared constant (mirrors ``reporting.toc.TOC_STYLE``): the single-file HTML
contract forbids ``<script>`` and external refs, so the CSS must be inlined into
the ``<style>`` block. ``CHART_STYLE`` references ONLY the design tokens the
narrative ``:root`` already defines (``--ink --ink-strong --muted --line --surface
--yellow-bg``) so it is safe to inject without adding a single new token — the
semantic tier colours (green/red/neutral) belong to the confidence pill, which is
a separate concern. Pure data (a module-level string); nothing here can raise.
"""
from __future__ import annotations

# Inlined into the narrative <style>. Every selector here is a class the narrative
# render path actually emits (verified against curated_view.py / charts.py), so
# there is no dead CSS. Fonts use the narrative's literal stacks (it defines no
# --font-* tokens) rather than the fact report's var(--font-sans/mono).
CHART_STYLE = """
    /* --- charts (charts.render_chart_template → <svg class="chart-svg">) ---
       Mirrors the fact report: hairline axes/grids, muted category labels,
       tabular-lining numerics. Without these rules the narrative's SVG axes were
       invisible (stroke defaults to none) and the text rendered unstyled. */
    .chart-svg {
      width: 100%;
      height: auto;
      display: block;
      overflow: visible;
      margin: 10px 0 4px;
    }
    .chart-svg text {
      font-family: 'SF Pro Display', 'Geist Sans', 'Helvetica Neue', sans-serif;
      fill: var(--ink);
    }
    .chart-svg .ca-title,
    .chart-svg .ca-cat { fill: var(--muted); font-size: 12px; }
    .chart-svg .ca-num {
      fill: var(--ink-strong);
      font-size: 12px;
      font-variant-numeric: tabular-nums;
    }
    .chart-svg .ca-empty { fill: var(--muted); font-size: 14px; }
    .chart-svg .ca-axis,
    .chart-svg .ca-grid { stroke: var(--line); stroke-width: 1; }

    /* --- top-N fold (curated_view → <details class="ca-table-fold" open>) ---
       A native, JS-free disclosure. The summary is the "共 N 行 · 仅展示…前 M 行"
       caption; a quiet ▸/▾ marker replaces the default triangle. */
    .ca-table-fold { margin: 12px 0 18px; }
    .ca-table-fold > summary {
      cursor: pointer;
      list-style: none;
      padding: 6px 0;
      color: var(--muted);
      font-size: 13px;
      user-select: none;
    }
    .ca-table-fold > summary::-webkit-details-marker { display: none; }
    .ca-table-fold > summary::before { content: "\\25B8  "; color: var(--muted); }
    .ca-table-fold[open] > summary::before { content: "\\25BE  "; }
    .ca-table-fold[open] > summary { margin-bottom: 8px; }

    /* --- highlighted row (curated_view → <tr class="ca-row-highlight">) ---
       The single most-valuable row gets a soft warm wash + heavier ink — a calm
       emphasis, never a loud fill. */
    .ca-row-highlight { background: var(--yellow-bg); }
    .ca-row-highlight td { color: var(--ink-strong); font-weight: 600; }
"""
