"""Deterministic executor for a curated view-spec (the numeric-trust boundary).

A curation agent emits only a declarative :mod:`view_spec` (template + column/row
selection + prose captions, with **no numeric values** except structural ints).
:func:`render_view` is the deterministic half of the contract: it validates the
spec, selects/sorts/TopN/highlights the REAL rows of ``result.tables`` and fills
every displayed number *verbatim* from the source — it never fabricates, rounds,
or re-aggregates a value. Chart templates additionally reuse the byte-deterministic
SVG primitives via :func:`charts.render_chart_template`.

Every function tolerates malformed input and degrades: an invalid spec, a missing
table, or a missing column yields a DEGRADED :class:`CuratedView` (no html + a
reason) rather than an exception, so a single bad view drops without blocking the
report. The agent decides *what it looks like*; this engine decides *what the
numbers are*.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from html import escape

from xhs_ceramics_analytics.reporting import charts
from xhs_ceramics_analytics.reporting.formatting import (
    field_label,
    format_scalar,
    is_timeseries_table,
)
from xhs_ceramics_analytics.reporting.view_spec import (
    CHART_TEMPLATES,
    ViewSpec,
    derive_confidence,
    validate_view_spec,
)

logger = logging.getLogger(__name__)

# Highlight marker class on a <tr>; styled by the report's stylesheet. Kept as a
# class (not an inline style) so highlighting stays a presentation concern.
_HIGHLIGHT_CLASS = "ca-row-highlight"

# The narrative shows only the most-valuable rows of a table (user-set cap): a
# per-period wall-of-dates is suppressed entirely (chart-only), and any other long
# table is truncated to its top rows with a caption + native <details> fold.
DEFAULT_MAX_ROWS = 8


@dataclass(frozen=True)
class CuratedView:
    """Rendered result of one curated view (immutable).

    ``table_html`` / ``chart_svg`` are ``None`` when absent (a table template has
    no chart; a degraded view has neither). ``confidence`` (强/中/弱) and
    ``provenance`` are derived deterministically, never authored by the agent. A
    degraded view sets ``degraded=True`` and carries a human-readable ``reason``.
    """

    table_html: str | None = None
    chart_svg: str | None = None
    title: str = ""
    how_to_read: str = ""
    why_it_matters: str = ""
    confidence: str = "弱"
    provenance: str = ""
    degraded: bool = False
    reason: str | None = None


def render_view(
    spec: object, result_tables: object, *, finding: object = None
) -> CuratedView:
    """Render one curated view-spec to a :class:`CuratedView`. Never raises.

    Validates ``spec`` against the real ``result_tables`` (the numeric-trust
    boundary); an invalid spec returns a DEGRADED result with ``reason`` and no
    html. A valid spec selects ``spec.columns`` and applies ``rows`` (sort / order
    / top_n / highlight) over the source table, filling every cell verbatim, and —
    for chart templates — also renders the matching inline SVG.
    """
    try:
        return _render(spec, result_tables, finding)
    except Exception:  # never-raise: an unexpected fault drops the view, not the report
        logger.exception("render_view failed")
        return CuratedView(
            degraded=True,
            reason="视图渲染发生内部错误",
            confidence=_safe_confidence(finding),
        )


def _render(spec: object, result_tables: object, finding: object) -> CuratedView:
    view = ViewSpec.from_dict(spec)
    confidence = derive_confidence(finding)
    provenance = _provenance(view, confidence)

    errors = validate_view_spec(spec, result_tables)
    if errors:
        return CuratedView(
            table_html=None,
            chart_svg=None,
            title=view.title,
            how_to_read=view.how_to_read,
            why_it_matters=view.why_it_matters,
            confidence=confidence,
            provenance=provenance,
            degraded=True,
            reason="; ".join(errors),
        )

    tables = result_tables if isinstance(result_tables, dict) else {}
    source = view.source if isinstance(view.source, dict) else {}
    table_name = str(source.get("table") or "")
    source_rows = tables.get(source.get("table"))
    is_chart = view.template in CHART_TEMPLATES

    # Form guard: a per-period (timeseries) source is never a table. A table-template
    # over it degrades (the trend belongs in a chart, not a wall-of-dates grid); a
    # chart-template keeps its chart but drops the per-day companion table.
    if is_timeseries_table(table_name, _source_columns(source_rows)):
        if not is_chart:
            return CuratedView(
                table_html=None,
                chart_svg=None,
                title=view.title,
                how_to_read=view.how_to_read,
                why_it_matters=view.why_it_matters,
                confidence=confidence,
                provenance=provenance,
                degraded=True,
                reason="逐期时间序列不作为表格呈现,请改用趋势图",
            )
        display_rows, _ = _select_rows(source_rows, view.rows)
        table_html = None
    else:
        display_rows, highlight_flags = _select_rows(source_rows, view.rows)
        table_html = _build_table_html(view, display_rows, highlight_flags)

    chart_svg: str | None = None
    if is_chart:
        rendered = str(
            charts.render_chart_template(
                view.template, display_rows, view.chart, confidence=confidence
            )
        )
        chart_svg = rendered or None

    return CuratedView(
        table_html=table_html,
        chart_svg=chart_svg,
        title=view.title,
        how_to_read=view.how_to_read,
        why_it_matters=view.why_it_matters,
        confidence=confidence,
        provenance=provenance,
        degraded=False,
        reason=None,
    )


# ---- row selection (select / sort / TopN / highlight — NO aggregation) ----


def _select_rows(
    source_rows: object, rows_spec: object
) -> tuple[list[dict], list[bool]]:
    """Apply the spec's ``rows`` operations to the REAL source rows.

    Only select / sort / TopN / highlight — never a sum, average, or numeric
    filter. Returns the ordered rows to display and a parallel list of highlight
    flags. Deterministic (stable sort) and never raises on garbage rows.
    """
    rows = [r for r in source_rows if isinstance(r, dict)] if isinstance(
        source_rows, (list, tuple)
    ) else []
    if not isinstance(rows_spec, dict):
        rows_spec = {}

    sort_by = rows_spec.get("sort_by")
    if sort_by:
        reverse = rows_spec.get("order") == "desc"
        rows = sorted(rows, key=lambda row: _sort_key(row.get(sort_by)), reverse=reverse)

    top_n = rows_spec.get("top_n")
    if isinstance(top_n, int) and not isinstance(top_n, bool) and top_n > 0:
        rows = rows[:top_n]

    highlight = rows_spec.get("highlight")
    highlight = highlight if isinstance(highlight, dict) else {}
    flags = [_is_highlighted(row, highlight) for row in rows]
    return rows, flags


def _sort_key(value: object) -> tuple[int, float, str]:
    """A total-order sort key that never raises on mixed/None/garbage cells.

    Numbers (and numeric strings) sort by magnitude; other strings sort lexically
    after all numbers; ``None`` sorts last. Ties preserve input order (stable
    sort), so the result is fully deterministic.
    """
    if value is None:
        return (2, 0.0, "")
    if isinstance(value, bool):  # a bool is a category here, not 1/0
        return (1, 0.0, str(value))
    if isinstance(value, (int, float)):
        num = float(value)
        if num == num and num not in (float("inf"), float("-inf")):
            return (0, num, "")
        return (1, 0.0, str(value))
    try:
        return (0, float(value), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(value))


def _is_highlighted(row: dict, highlight: dict) -> bool:
    """True if the row matches any {column: existing-category-value} pair."""
    for column, value in highlight.items():
        if str(row.get(column)) == str(value):
            return True
    return False


# ---- table HTML (reuses the deterministic renderer's .table-wrap markup) --


def _build_table_html(
    view: ViewSpec, rows: list[dict], highlight_flags: list[bool]
) -> str | None:
    """Build the curated table HTML — capped to the most-valuable rows, foldable.

    Mirrors the deterministic renderer's ``.table-wrap`` markup and stdlib HTML
    escaping (see ``reporting.html``): a ``<div class="table-wrap"><table>`` with a
    ``<thead>`` of ``column_labels`` (falling back to the shared human field label,
    never the raw snake_case column) and a ``<tbody>`` whose cells are formatted from
    the source via :func:`format_scalar` (thousands separators / percents / 是否 /
    暂无数据) — the number is still filled from the source row; only its presentation
    is normalized. Only the first :data:`DEFAULT_MAX_ROWS` rows are shown; a longer
    table is truncated with a caption and wrapped in a native ``<details>`` fold.
    Returns ``None`` when the spec carries no columns.
    """
    columns = list(view.columns)
    if not columns:
        return None
    labels = view.column_labels if isinstance(view.column_labels, dict) else {}

    total = len(rows)
    shown_rows = rows[:DEFAULT_MAX_ROWS]
    shown_flags = highlight_flags[:DEFAULT_MAX_ROWS]

    header = "".join(
        f"<th>{escape(str(labels.get(col) or field_label(col)))}</th>"
        for col in columns
    )
    body_rows: list[str] = []
    for row, highlighted in zip(shown_rows, shown_flags):
        cells = "".join(f"<td>{_cell_html(col, row.get(col))}</td>" for col in columns)
        tr_open = f'<tr class="{_HIGHLIGHT_CLASS}">' if highlighted else "<tr>"
        body_rows.append(f"{tr_open}{cells}</tr>")

    table = (
        '<div class="table-wrap"><table>'
        f"<thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )

    if total > len(shown_rows):
        caption = f"共 {total} 行 · 仅展示最有价值的前 {len(shown_rows)} 行"
        return (
            '<details class="ca-table-fold" open>'
            f"<summary>{escape(caption)}</summary>{table}</details>"
        )
    return table


def _cell_html(field_name: str, value: object) -> str:
    """Render a source cell via the shared fact-layer formatter, HTML-escaped.

    The number is still filled verbatim from the source row; :func:`format_scalar`
    only normalizes *presentation* (thousands separators, percents, 是/否, 暂无数据),
    so the narrative matches the fact layer and the value-match boundary holds (the
    gate formats the source identically). Emoji is real content, never stripped by
    :func:`html.escape`.
    """
    return escape(format_scalar(field_name, value))


def _source_columns(source_rows: object) -> list[str]:
    """Column names of the source table (keys of its first dict row), for the
    timeseries form check. Empty when the table is missing/empty/garbage."""
    if isinstance(source_rows, (list, tuple)):
        for row in source_rows:
            if isinstance(row, dict):
                return list(row.keys())
    return []


# ---- provenance + helpers -------------------------------------------------


def _provenance(view: ViewSpec, confidence: str) -> str:
    """The light audit stamp ``来源:{task_id} · {table} · 证据:{confidence}``."""
    source = view.source if isinstance(view.source, dict) else {}
    task_id = str(source.get("task_id") or "")
    table = str(source.get("table") or "")
    return f"来源:{task_id} · {table} · 证据:{confidence}"


def _safe_confidence(finding: object) -> str:
    try:
        return derive_confidence(finding)
    except Exception:  # derive_confidence never raises, but stay defensive
        return "弱"
