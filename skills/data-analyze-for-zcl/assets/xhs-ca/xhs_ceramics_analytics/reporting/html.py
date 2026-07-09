import re
from html import escape, unescape

from jinja2 import Environment, PackageLoader

from xhs_ceramics_analytics.analysis.methodology import combined_methodology
from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.reporting import confidence as _confidence
from xhs_ceramics_analytics.reporting.confidence import reader_confidence
from xhs_ceramics_analytics.reporting.domains import (
    APPENDIX_DOMAIN_INTRO,
    APPENDIX_DOMAIN_TITLE,
    DOMAINS,
    group_by_domain,
)
from xhs_ceramics_analytics.reporting.markdown import render_markdown
from xhs_ceramics_analytics.reporting.priority import build_priority_table
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS
from xhs_ceramics_analytics.reporting.chart_style import CHART_STYLE
from xhs_ceramics_analytics.reporting.confidence_pill import CONFIDENCE_PILL_STYLE
from xhs_ceramics_analytics.reporting.table_labels import TABLE_LABELS as _TABLE_LABELS
from xhs_ceramics_analytics.reporting.toc import TOC_STYLE, build_toc_nav
from xhs_ceramics_analytics.reporting.formatting import (
    field_help as _field_help,
    field_label as _field_label,
    format_scalar as _format_scalar,
    is_timeseries_table as _is_timeseries_table,
    should_render_table as _should_render_table,
)
from xhs_ceramics_analytics.reporting import charts


# Raw-HTML passthrough markers. The narrative renderer wraps DETERMINISTIC curated
# table/chart HTML (built by reporting.curated_view, whose cells are already
# stdlib-escaped) in these sentinels so _markdown_document_body emits the block
# verbatim instead of escaping its angle brackets — otherwise a <table>/<svg> would
# ship as visible source. Host-neutral HTML comments, invisible in any markdown viewer.
#
# SECURITY INVARIANT: these are in-band text sentinels, so they are trustworthy ONLY
# because their sole producer — narrative_render._raw_html_block — is the sole path
# that emits them, and narrative_render._strip_raw_html_markers neutralizes the tokens
# in EVERY agent-authored string before assembly. A forged standalone marker in agent
# prose would otherwise flip this converter into unescaped passthrough (XSS bypass +
# numeric-trust breach). Do not emit agent-derived text into this converter without
# that neutralization.
RAW_HTML_OPEN = "<!--raw-html-->"
RAW_HTML_CLOSE = "<!--/raw-html-->"

_MAX_TABLE_ROWS = 20

# Tables with fewer than this many rows open by default — short enough to read at
# a glance, so the collapsed shell just adds a needless click. Distinct from
# _MAX_TABLE_ROWS (the row-truncation cap): a table can be fully shown yet still
# stay collapsed if it is long.
_MAX_OPEN_TABLE_ROWS = 10

# Neutral default for the follow-up-questions section. The original hardcoded a
# specific assistant brand into reader-facing copy; the name is now a single
# configurable value (CLI --assistant) so the deliverable never ships a vendor
# name the reader didn't choose.
_DEFAULT_ASSISTANT_NAME = "分析助手"

# 经营导读的高亮大卡候选。重拍/重发是弱证据假设(#2)——它属于「流量与内容」域里的一条
# 可选线索,不该被抬成导读大卡,故不在此列。
_BUSINESS_HIGHLIGHT_TASKS = (
    "product_opportunity_matrix",
    "copy_angle_effect",
    "content_portfolio_optimization",
    "comment_demand_mining",
    "weekly_experiment_matrix",
)

# 业务主题域(域标题/导语/归属 task)与域内优先级排序统一由 reporting.domains 定义,
# md / html 两个 compositor 共用同一份分组,不再各自手写(见 domains.group_by_domain)。

# Data-quality sections close the report as an appendix — see reporting.section_order.
# Title/intro live in reporting.domains so md 与 html 用同一份文案。
_APPENDIX_GROUP = {
    "title": APPENDIX_DOMAIN_TITLE,
    "description": APPENDIX_DOMAIN_INTRO,
}

_USER_TABLE_COLUMNS = {
    "table_row_counts": ("table", "rows"),
    "business_self_benchmark": (
        "metric",
        "latest_period",
        "value",
        "percentile_label",
        "periods",
    ),
    "event_activity_lift": (
        "metric",
        "event_value",
        "baseline_value",
        "lift_pct",
        "significance",
    ),
    "audience_gmv_contribution": ("audience_type", "gmv", "gmv_share"),
    "daily_posts": ("date", "posts", "reads", "collects", "comments"),
    "posting_windows": (
        "publish_window",
        "posts",
        "avg_reads",
        "avg_engagement",
        "avg_note_gmv",
        "perf_lift",
    ),
    "note_funnel": (
        "note_title",
        "reads",
        "read_rate",
        "like_rate",
        "collect_rate",
        "comment_rate",
    ),
    "cover_effects": ("composition_type", "notes", "avg_reads", "avg_collects"),
    "copy_effects": ("copy_angle", "notes", "avg_reads", "avg_collects"),
    "product_opportunities": ("sku_name", "units", "gmv", "opportunity_type"),
    "sku_lift": (
        "sku_name",
        "window",
        "pre_units",
        "post_units",
        "absolute_lift",
        "relative_lift",
    ),
    "response_windows": (
        "note_title",
        "sku_name",
        "window",
        "pre_units",
        "post_units",
        "relative_lift",
    ),
    "product_interactions": (
        "composition_type",
        "copy_angle",
        "notes",
        "avg_reads",
        "avg_collects",
    ),
    "portfolio_mix": (
        "copy_angle",
        "notes",
        "mix_share",
        "avg_reads",
        "avg_collect_rate",
    ),
    "comment_demands": (
        "demand_group",
        "comments",
        "comment_share",
        "example_comments",
    ),
    "comment_emergent_themes": (
        "term",
        "comments",
        "polarity",
        "trend",
        "content_hook",
    ),
    "experiment_plan": (
        "date",
        "slot_time",
        "sku_name",
        "copy_angle",
        "success_metric",
    ),
    "reshoot_candidates": (
        "rank",
        "title",
        "reads",
        "collects",
        "collect_rate",
        "reason",
    ),
    "hypotheses": (
        "theme",
        "hypothesis",
        "evidence_summary",
        "next_test",
        "status",
    ),
    "weekly_sections": ("section", "status", "metric", "value", "summary"),
    "ad_data_quality": (
        "rows",
        "first_date",
        "last_date",
        "total_spend",
        "detected_grain",
        "has_click_metrics",
        "has_gmv_metrics",
    ),
    "paid_traffic_efficiency": (
        "campaign_name_optional",
        "creative_name_optional",
        "spend",
        "impressions",
        "clicks",
        "ctr_calc",
        "cpc_calc",
        "gmv_optional",
        "roas_calc",
        "budget_action",
    ),
    "paid_spend_response": (
        "spend_band",
        "objects",
        "avg_spend",
        "avg_roas",
        "marginal_roas",
        "is_saturation",
    ),
    "note_referral_attribution": (
        "note_title",
        "referral_orders",
        "referral_gmv",
        "note_gmv",
    ),
    "high_refund_notes": (
        "title",
        "note_refund_rate",
        "n",
        "composition_type",
        "scene_hint",
        "copy_angle",
    ),
    "sku_category_l2_mix": (
        "category_l2",
        "gmv",
        "gmv_share",
        "refund_rate",
    ),
    "sku_price_band_distribution": (
        "band",
        "sku_count",
        "sku_share",
        "gmv_share",
    ),
    "sku_price_sweet_spot": (
        "band",
        "sku_count",
        "cart_to_pay",
        "refund_rate_pay",
        "net_margin",
        "is_sweet_spot",
    ),
    "demand_funnel_trend": (
        "date",
        "add_to_cart_users",
        "paid_buyers",
        "cart_to_pay",
    ),
    "wishlist_demand_trend": (
        "date",
        "new_wishlist_users",
    ),
    "gmv_bridge": (
        "factor_zh",
        "contribution",
        "share",
        "is_dominant",
    ),
    "business_trend": (
        "date",
        "gmv",
        "pct",
        "direction",
        "is_changepoint",
        "is_anomaly",
    ),
}



_DEFAULT_REPORT_TITLE = "小红书账号分析报告"


def render_html(
    results: list[AnalysisResult],
    title: str | None = None,
    assistant: str | None = None,
) -> str:
    report_title = title or _DEFAULT_REPORT_TITLE
    env = Environment(
        loader=PackageLoader("xhs_ceramics_analytics.reporting", "templates"),
        autoescape=True,
    )
    env.filters["field_label"] = _field_label
    env.filters["field_help"] = _field_help
    env.filters["display_value"] = _display_value
    env.filters["display_cell"] = _display_cell_filter
    template = env.get_template("report.html.j2")
    return template.render(
        markdown_report=render_markdown(results, title=report_title),
        report=_build_report_context(results, assistant=assistant),
        results=results,
        report_title=report_title,
    )


def render_markdown_document_html(markdown_text: str, title: str | None = None) -> str:
    report_title = title or _extract_markdown_title(markdown_text) or "小红书账号分析报告"
    body_html, toc_entries = _markdown_document_body(markdown_text)
    toc_nav_html = build_toc_nav(toc_entries)
    escaped_title = escape(report_title)
    # Narrative reading measure (960px); the wide envelope (960 + 232 rail + 44 gap
    # = 1236, rounded to 1240) seats the rail beside the full 960px body. --toc-pad
    # is left to TOC_STYLE's responsive value so it is not shadowed here.
    narrative_toc_css = TOC_STYLE + (
        "\n    .page-grid { --toc-content: 960px; --toc-content-wide: 1240px; }\n"
    )

    main_html = f"""<main class="report-shell">
      <header class="topbar">
        <div class="brand">小红书经营分析</div>
        <div>Single-file HTML</div>
      </header>
      <article class="report-card">
        <span class="eyebrow">Integrated Report</span>
{body_html}
      </article>
    </main>"""

    # Wrap in the sticky-TOC grid only when there is something to index; a doc with
    # no sub-headings renders the bare shell (no empty rail column). The 960px reading
    # measure and 32px gutter carry over via the narrative --toc-* overrides.
    if toc_nav_html:
        content_html = f"""<div class="page-grid">
    {toc_nav_html}
    {main_html}
  </div>"""
    else:
        content_html = main_html

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escaped_title}</title>
  <style>
    :root {{
      --canvas: #F7F6F3;
      --surface: #FFFFFF;
      --ink: #2F3437;
      --ink-strong: #111111;
      --muted: #787774;
      --line: #EAEAEA;
      --yellow-bg: #FBF3DB;
      --yellow-text: #956400;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--canvas);
      color: var(--ink);
      font-family: 'SF Pro Display', 'Geist Sans', 'Helvetica Neue', sans-serif;
      line-height: 1.68;
    }}
    /* Width/centering belongs to .page-grid when the TOC rail is present; a
       rail-less document (only an h1, no sub-headings) renders .report-shell as a
       direct child of <body>, so it self-centers via the body> rule below. */
    .report-shell {{
      padding: 32px 0 72px;
    }}
    body > .report-shell {{
      width: min(960px, calc(100% - 24px));
      margin: 0 auto;
    }}
    .topbar {{
      display: flex;
      justify-content: space-between;
      gap: 20px;
      padding: 14px 0 28px;
      color: var(--muted);
      font-size: 13px;
    }}
    .brand {{
      color: var(--ink-strong);
      font-weight: 700;
    }}
    .report-card {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 12px;
      padding: clamp(24px, 5vw, 56px);
    }}
    .eyebrow {{
      display: inline-flex;
      width: fit-content;
      border-radius: 9999px;
      padding: 5px 10px;
      background: var(--yellow-bg);
      color: var(--yellow-text);
      font-family: 'Geist Mono', 'SF Mono', monospace;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    h1, h2, h3, h4, h5, h6 {{
      color: var(--ink-strong);
      letter-spacing: 0;
      line-height: 1.18;
    }}
    h1 {{
      margin: 22px 0 28px;
      font-family: 'Lyon Text', 'Newsreader', 'Playfair Display', serif;
      font-size: clamp(40px, 7vw, 68px);
    }}
    h2 {{ margin: 42px 0 14px; font-size: 30px; }}
    h3 {{ margin: 30px 0 12px; font-size: 22px; }}
    p {{ margin: 12px 0; }}
    ul, ol {{ padding-left: 24px; }}
    li + li {{ margin-top: 6px; }}
    code {{
      border: 1px solid var(--line);
      border-radius: 4px;
      padding: 2px 5px;
      background: var(--canvas);
      font-family: 'Geist Mono', 'SF Mono', monospace;
      font-size: 0.92em;
    }}
    pre {{
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 16px;
      background: var(--canvas);
    }}
    pre code {{ border: 0; padding: 0; background: transparent; }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
      margin: 18px 0;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 560px;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      color: var(--muted);
      background: #F9F9F8;
      font-family: 'Geist Mono', 'SF Mono', monospace;
      font-weight: 700;
    }}
    blockquote {{
      margin: 18px 0;
      padding: 2px 0 2px 16px;
      border-left: 3px solid var(--line);
      color: var(--muted);
    }}
    hr {{
      border: 0;
      border-top: 1px solid var(--line);
      margin: 32px 0;
    }}
    @media (max-width: 700px) {{
      .report-card {{ border-radius: 8px; }}
      h2 {{ font-size: 26px; }}
    }}
{CHART_STYLE}
{CONFIDENCE_PILL_STYLE}
{narrative_toc_css}
  </style>
</head>
<body>
  {content_html}
</body>
</html>
"""


def _extract_markdown_title(markdown_text: str) -> str | None:
    for line in markdown_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip()
            return title or None
    return None


def _markdown_document_body(
    markdown_text: str,
) -> tuple[str, list[dict[str, object]]]:
    """Convert markdown to the report body HTML AND collect its TOC entries.

    Every level-2/level-3 heading gets a stable sequential id (``sec-N``) so the
    persistent rail can anchor-scroll to it; the returned entry list (in document
    order, carrying each heading's level, anchor id, and cleaned label) is handed
    to :func:`reporting.toc.build_toc_nav`. The h1 title is intentionally excluded
    — it is the document header, not a navigable section.
    """
    lines = markdown_text.splitlines()
    blocks: list[str] = []
    toc_entries: list[dict[str, object]] = []
    heading_counter = 0
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        if stripped == RAW_HTML_OPEN:
            # Deterministic curated HTML/SVG block — emit verbatim (NOT escaped) up to
            # the closing marker. A missing close marker just consumes to EOF (never
            # loops), so a malformed block degrades instead of raising.
            raw_lines: list[str] = []
            index += 1
            while index < len(lines) and lines[index].strip() != RAW_HTML_CLOSE:
                raw_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1  # consume the closing marker
            blocks.append("\n".join(raw_lines))
            continue

        if stripped.startswith("```"):
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            blocks.append(f"<pre><code>{escape(chr(10).join(code_lines))}</code></pre>")
            continue

        if stripped == "---":
            blocks.append("<hr>")
            index += 1
            continue

        heading_level = _heading_level(stripped)
        if heading_level is not None:
            text = stripped[heading_level + 1 :].strip()
            if heading_level in (2, 3):
                heading_counter += 1
                anchor = f"sec-{heading_counter}"
                toc_entries.append(
                    {"level": heading_level, "anchor": anchor, "label": _toc_label(text)}
                )
                blocks.append(
                    f'<h{heading_level} id="{anchor}">'
                    f"{_inline_markdown(text)}</h{heading_level}>"
                )
            else:
                blocks.append(f"<h{heading_level}>{_inline_markdown(text)}</h{heading_level}>")
            index += 1
            continue

        if _is_table_start(lines, index):
            table_html, index = _render_markdown_table(lines, index)
            blocks.append(table_html)
            continue

        if _is_unordered_item(stripped):
            items: list[str] = []
            while index < len(lines) and _is_unordered_item(lines[index].strip()):
                items.append(lines[index].strip()[2:].strip())
                index += 1
            blocks.append(
                "<ul>"
                + "".join(f"<li>{_inline_markdown(item)}</li>" for item in items)
                + "</ul>"
            )
            continue

        if _is_ordered_item(stripped):
            items = []
            while index < len(lines) and _is_ordered_item(lines[index].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[index].strip()).strip())
                index += 1
            blocks.append(
                "<ol>"
                + "".join(f"<li>{_inline_markdown(item)}</li>" for item in items)
                + "</ol>"
            )
            continue

        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            blocks.append(f"<blockquote>{_inline_markdown(' '.join(quote_lines))}</blockquote>")
            continue

        paragraph_lines = [stripped]
        index += 1
        while index < len(lines) and _is_paragraph_continuation(lines, index):
            paragraph_lines.append(lines[index].strip())
            index += 1
        blocks.append(f"<p>{_inline_markdown(' '.join(paragraph_lines))}</p>")

    return "\n".join(f"      {block}" for block in blocks), toc_entries


def _toc_label(text: str) -> str:
    """Plain-text rail label matching the heading's *rendered* text.

    Runs the same inline-markdown pass the heading body uses, then drops the
    only tags it can emit (``<strong>``/``<code>``) and unescapes. This removes
    *paired* emphasis/code markers (``**bold**`` → ``bold``, `` `code` `` →
    ``code``) exactly as the body shows them, while a lone ``*``/`` ` `` that is
    genuine content (``3*2``, a footnote asterisk) — and every emoji — is
    preserved verbatim rather than globally deleted.
    """
    rendered = re.sub(r"</?(?:strong|code)>", "", _inline_markdown(text))
    label = unescape(rendered).strip()
    return label or text.strip()


def _heading_level(stripped: str) -> int | None:
    match = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if match is None:
        return None
    return len(match.group(1))


def _is_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return "|" in lines[index] and _is_table_separator(lines[index + 1])


def _is_table_separator(line: str) -> bool:
    cells = _split_table_row(line)
    if not cells:
        return False
    return all(re.match(r"^:?-{3,}:?$", cell.strip()) for cell in cells)


def _render_markdown_table(lines: list[str], index: int) -> tuple[str, int]:
    headers = _split_table_row(lines[index])
    index += 2
    rows: list[list[str]] = []
    while index < len(lines) and "|" in lines[index].strip():
        rows.append(_split_table_row(lines[index]))
        index += 1

    header_html = "".join(f"<th>{_inline_markdown(cell)}</th>" for cell in headers)
    row_html = []
    for row in rows:
        padded = row + [""] * max(0, len(headers) - len(row))
        cells = "".join(f"<td>{_inline_markdown(cell)}</td>" for cell in padded[: len(headers)])
        row_html.append(f"<tr>{cells}</tr>")
    return (
        "<div class=\"table-wrap\"><table>"
        f"<thead><tr>{header_html}</tr></thead>"
        f"<tbody>{''.join(row_html)}</tbody>"
        "</table></div>",
        index,
    )


def _split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _is_unordered_item(stripped: str) -> bool:
    return stripped.startswith("- ") or stripped.startswith("* ")


def _is_ordered_item(stripped: str) -> bool:
    return re.match(r"^\d+\.\s+", stripped) is not None


def _is_paragraph_continuation(lines: list[str], index: int) -> bool:
    stripped = lines[index].strip()
    if not stripped:
        return False
    return not (
        stripped.startswith("```")
        or stripped == "---"
        or _heading_level(stripped) is not None
        or _is_table_start(lines, index)
        or _is_unordered_item(stripped)
        or _is_ordered_item(stripped)
        or stripped.startswith(">")
    )


def _inline_markdown(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    rendered: list[str] = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) >= 2:
            rendered.append(f"<code>{escape(part[1:-1])}</code>")
            continue
        escaped = escape(part)
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        rendered.append(escaped)
    return "".join(rendered)


# Fact-layer TOC widths: keep the historical 1180px shell. The wide envelope must
# seat the full 1180px content column BESIDE the 232px rail + 44px gap, so it is
# sized 1180 + 232 + 44 = 1456px — otherwise the content column would stay narrower
# on wide screens than it was just below the breakpoint. Only --toc-content* is
# overridden; --toc-pad stays responsive inside TOC_STYLE.
_FACT_TOC_STYLE = TOC_STYLE + (
    "\n    .page-grid { --toc-content: 1180px; --toc-content-wide: 1456px; }\n"
)


def _fact_toc_entries(
    analysis_groups: list[dict[str, object]],
    has_priority: bool,
    assistant_name: str,
) -> list[dict[str, object]]:
    """Ordered TOC entries mirroring the fact-layer section order.

    The static top-level sections always render (so they are always listed); the
    priority section is conditional; each analysis domain becomes a level-3
    sub-entry under 详细分析, anchored to its ``.section-panel`` id.
    """
    entries: list[dict[str, object]] = [
        {"level": 2, "anchor": "how-to-read", "label": "怎么读"},
        {"level": 2, "anchor": "guide", "label": "经营导读"},
    ]
    if has_priority:
        entries.append({"level": 2, "anchor": "priority", "label": "先动顺序"})
    entries.append({"level": 2, "anchor": "actions", "label": "行动计划"})
    entries.append({"level": 2, "anchor": "analysis", "label": "详细分析"})
    for group in analysis_groups:
        anchor = group.get("anchor_id")
        label = group.get("title")
        if isinstance(anchor, str) and isinstance(label, str):
            entries.append({"level": 3, "anchor": anchor, "label": label})
    entries.append({"level": 2, "anchor": "appendix", "label": "数据附录"})
    entries.append({"level": 2, "anchor": "assistant", "label": f"{assistant_name} 追问"})
    return entries


def _build_report_context(
    results: list[AnalysisResult], assistant: str | None = None
) -> dict[str, object]:
    findings = [finding for result in results for finding in result.findings]
    total_table_rows = sum(len(rows) for result in results for rows in result.tables.values())
    result_views = [_result_view(result) for result in results]
    assistant_name = (assistant or _DEFAULT_ASSISTANT_NAME).strip() or _DEFAULT_ASSISTANT_NAME
    priority_table = _priority_table_view(results)
    analysis_groups = _analysis_groups(results, result_views)
    toc_entries = _fact_toc_entries(analysis_groups, bool(priority_table), assistant_name)
    return {
        "task_count": len(results),
        "finding_count": len(findings),
        "table_count": sum(len(result.tables) for result in results),
        "total_table_rows": total_table_rows,
        "assistant_name": assistant_name,
        "highlights": _business_highlights(results),
        "priority_table": priority_table,
        "actions": _business_actions(results, findings),
        "analysis_groups": analysis_groups,
        "toc_nav_html": build_toc_nav(toc_entries),
        "toc_style": _FACT_TOC_STYLE,
        "evidence_counts": _evidence_counts(findings),
        "evidence_chart_svg": charts.evidence_distribution(_evidence_counts(findings)),
        "assistant_questions": _codex_questions(results),
        "glossary": [
            {
                "term": "置信度",
                "definition": "说明这条结论能被多大程度用于经营决策，主要看样本量和口径是否清晰；不代表结论有没有价值。",
            },
            {
                "term": "弱归因",
                "definition": "数据能提供方向，但还不能证明某条笔记直接带来了某个订单。",
            },
            {
                "term": "受控实验",
                "definition": "一次只改变一个变量，例如只换文案角度，其他 SKU、发布时间和封面尽量保持一致。",
            },
            {
                "term": "SKU",
                "definition": "具体商品规格，例如单只杯子、礼盒装、不同颜色或容量。",
            },
            {
                "term": "新客",
                "definition": "沿用平台导出的「人群类型」字段；报告做人群对比时固定取首购周期 365 天窗口，避免 180/365 天累计窗口重复计数，不独立重算买家的首购时间。",
            },
            {
                "term": "老客",
                "definition": "沿用平台导出的「人群类型」字段；报告将其作为平台已划分的复购/回访人群使用，不用订单明细反推出首次成交日期。",
            },
            {
                "term": "多重比较校正 (BH-FDR)",
                "definition": "同时检查很多项时，光靠运气也会冒出几个「异常」。这个方法把这类假警报控制在很低的比例，留下的更可能是真的。",
            },
            {
                "term": "置信区间 (Wilson)",
                "definition": "样本少时，单看一个比率不稳。用一个区间表示真实值大概落在哪个范围，样本越少区间越宽。",
            },
        ],
    }


def _result_view(result: AnalysisResult) -> dict[str, object]:
    return {
        "task_id": result.task_id,
        "title": result.title,
        "label": _result_label(result.task_id, result.title),
        "findings": [_finding_view(finding) for finding in result.findings],
        "chart_svg": charts.for_result(result),
        "table_views": [
            _table_view(table_name, rows)
            for table_name, rows in result.tables.items()
            if _should_render_table(rows)
        ],
        "limitations": result.limitations,
        "subsections": [_subsection_view(subsection) for subsection in result.subsections],
        "named_examples": result.named_examples,
    }


def _finding_view(finding: Finding) -> dict[str, object]:
    summary = _finding_summary(finding)
    return {
        **summary,
        "key_numbers": [
            {
                "label": _field_label(key),
                "help": _field_help(key),
                "value": _display_cell(key, value),
            }
            for key, value in finding.key_numbers.items()
        ],
        "caveats": _caveats_with_causal(finding),
        "recommended_action": finding.recommended_action,
        "confounders": finding.confounders,
        "next_test": finding.next_test,
        "appendix": combined_methodology(finding),
    }


def _subsection_view(subsection: Subsection) -> dict[str, object]:
    return {
        "title": subsection.title,
        "body": subsection.body,
        "table_name": subsection.table_name,
        "findings": [_finding_view(finding) for finding in subsection.findings],
    }


def _table_view(table_name: str, rows: list[dict[str, object]]) -> dict[str, object]:
    all_columns = list(rows[0].keys()) if rows else []
    preferred_columns = _USER_TABLE_COLUMNS.get(table_name, tuple(all_columns[:6]))
    user_columns = [column for column in preferred_columns if column in all_columns]
    if not user_columns:
        user_columns = all_columns[:6]

    # Drop a user column that is entirely 暂无数据 across every shown row — a
    # blank column only widens the grid and tells the reader nothing. Guard the
    # edge where that would empty the table: an all-blank grid keeps its columns,
    # since a column-less table reads worse than a sparse one.
    shown = rows[:_MAX_TABLE_ROWS]
    non_empty = [c for c in user_columns if any(r.get(c) is not None for r in shown)]
    user_columns = non_empty or user_columns

    showing_count = min(len(rows), _MAX_TABLE_ROWS)
    display_text = f"共 {len(rows)} 行，当前展示 {showing_count} 行"
    if len(rows) > _MAX_TABLE_ROWS:
        display_text = f"共 {len(rows)} 行，当前展示前 {showing_count} 行"

    return {
        "name": table_name,
        "label": _TABLE_LABELS.get(table_name, table_name.replace("_", " ")),
        "row_count": len(rows),
        "showing_count": showing_count,
        # Short tables (< 10 rows) open by default — readable at a glance, so the
        # collapsed shell just adds a needless click. Longer tables stay collapsed
        # to keep the page scannable. Time-series trend tables (#17) are the one
        # exception: their chart carries the story, so the raw per-period grid stays
        # folded regardless of length instead of pushing the chart below the fold.
        "open": len(rows) < _MAX_OPEN_TABLE_ROWS
        and not _is_timeseries_table(table_name, all_columns),
        "display_text": display_text,
        # 只保留用户视图；原始机器列名在 markdown 表格预览(附录)里留证，HTML 不再
        # 叠一层「技术追溯」制造工程噪音(#12)。
        "user_columns": [_column_view(column) for column in user_columns],
        "user_rows": [_row_cells(row, user_columns) for row in rows[:_MAX_TABLE_ROWS]],
    }


def _column_view(column: str) -> dict[str, str]:
    return {
        "name": column,
        "label": _field_label(column),
        "help": _field_help(column),
    }


def _row_cells(row: dict[str, object], columns: list[str]) -> list[dict[str, str]]:
    return [
        {
            "name": column,
            "value": _display_cell(column, row.get(column)),
        }
        for column in columns
    ]


def _domain_group_view(
    title: str, intro: str, views: list[dict[str, object]], anchor_id: str
) -> dict[str, object]:
    """Two-level shape: one headline result (rendered as a big card) + the rest folded.

    The domain's results arrive already priority-sorted (from ``group_by_domain`` or
    ``APPENDIX_TASKS`` order), so the first is the one the reader should act on first;
    the rest fold into a ``<details>`` so the domain reads as "here's the lever, expand
    for the supporting modules" rather than an undifferentiated pile (#2/#19).

    ``anchor_id`` is the stable in-page id the persistent TOC rail links to (the
    template stamps it on the domain's ``.section-panel``).
    """
    return {
        "title": title,
        "intro": intro,
        "anchor_id": anchor_id,
        "headline_result": views[0] if views else None,
        "secondary_results": views[1:],
    }


def _analysis_groups(
    results: list[AnalysisResult], result_views: list[dict[str, object]]
) -> list[dict[str, object]]:
    """Domain-driven two-level structure for the deep-dive section.

    Domain assignment and within-domain priority ordering are owned by
    :func:`reporting.domains.group_by_domain` (shared with the markdown compositor);
    here we only map its ``AnalysisResult`` groups back to their rendered views and
    split each into headline + folded secondaries. The data-quality appendix is
    appended last, outside the business domains.
    """
    views_by_task = {str(view["task_id"]): view for view in result_views}
    grouped: list[dict[str, object]] = []

    for domain in group_by_domain(results):
        views = [
            views_by_task[result.task_id]
            for result in domain.results
            if result.task_id in views_by_task
        ]
        if not views:
            continue
        grouped.append(
            _domain_group_view(
                domain.title, domain.intro, views, f"analysis-{len(grouped) + 1}"
            )
        )

    appendix_views = [
        views_by_task[task_id] for task_id in APPENDIX_TASKS if task_id in views_by_task
    ]
    if appendix_views:
        grouped.append(
            _domain_group_view(
                str(_APPENDIX_GROUP["title"]),
                str(_APPENDIX_GROUP["description"]),
                appendix_views,
                f"analysis-{len(grouped) + 1}",
            )
        )
    return grouped


def _priority_table_view(results: list[AnalysisResult]) -> list[dict[str, object]]:
    """Reader-facing rows for the cross-module priority table, in 4 plain columns.

    The pure :func:`build_priority_table` primitive still orders rows by 预期影响 ×
    可行性 internally, but the reader only meets 先动顺序 / 哪个环节 / 具体先做什么 /
    置信度. The 4th column is the folded 置信度 rating (label + level class) as one
    colored tag — a genuine per-row rating, not a band-composed "为什么值得先做" reason
    (which read verbatim-identical down every row on real data).
    """
    rows = build_priority_table(results)
    views: list[dict[str, object]] = []
    for index, row in enumerate(rows, start=1):
        views.append(
            {
                "rank": index,
                "weak_link": row.get("weak_link"),
                "lever": row.get("lever"),
                "confidence": row.get("confidence_label"),
                "confidence_class": row.get("confidence_class"),
            }
        )
    return views


def _highlights(findings: list[Finding]) -> list[dict[str, str]]:
    highlighted = findings[:3]
    if not highlighted:
        return [
            {
                "title": "暂无可读结论",
                "body": "当前数据还不足以生成经营判断，请先完成数据导入。",
                **_confidence_chip(_confidence.NOT_JUDGABLE),
            }
        ]
    return [_finding_summary(finding) for finding in highlighted]


def _business_highlights(results: list[AnalysisResult]) -> list[dict[str, str]]:
    results_by_task = {result.task_id: result for result in results}
    highlights: list[dict[str, str]] = []
    for task_id in _BUSINESS_HIGHLIGHT_TASKS:
        result = results_by_task.get(task_id)
        if result is None:
            continue
        highlight = _highlight_for_result(result)
        if highlight is not None:
            highlights.append(highlight)

    if highlights:
        return highlights[:4]

    findings = [
        finding
        for result in results
        if result.task_id != "data_quality_check"
        for finding in result.findings
    ]
    if not findings:
        findings = [finding for result in results for finding in result.findings]
    return _highlights(findings)


def _highlight_for_result(result: AnalysisResult) -> dict[str, str] | None:
    if result.task_id == "product_opportunity_matrix":
        row = _first_row(result, "product_opportunities")
        if row:
            sku = str(row.get("sku_name") or "头部 SKU")
            return _highlight(
                result,
                f"商品机会：优先测试{sku}",
                (
                    f"当前销售件数 {_display_cell('units', row.get('units'))}，"
                    f"销售额 {_display_cell('gmv', row.get('gmv'))}，"
                    f"系统判断为{_display_cell('opportunity_type', row.get('opportunity_type'))}。"
                    "下周适合围绕这个商品做受控内容实验。"
                ),
            )
        return _highlight_from_primary_finding(result, "商品机会")

    if result.task_id in {"copy_angle_effect", "content_portfolio_optimization"}:
        table_name = "copy_effects" if result.task_id == "copy_angle_effect" else "portfolio_mix"
        row = _first_row(result, table_name)
        if row:
            angle = _display_cell("copy_angle", row.get("copy_angle"))
            reads = _display_cell("avg_reads", row.get("avg_reads"))
            collects = _display_cell("avg_collects", row.get("avg_collects"))
            return _highlight(
                result,
                f"内容角度：{angle}值得继续验证",
                (
                    f"这个角度已有 {_display_cell('notes', row.get('notes'))} 篇样本，"
                    f"平均阅读数 {reads}，平均收藏数 {collects}。"
                    "它适合进入下周实验，而不是直接当作长期定论。"
                ),
            )
        return _highlight_from_primary_finding(result, "内容角度")

    if result.task_id == "comment_demand_mining":
        row = _first_row(result, "comment_demands")
        if row:
            group = _display_cell("demand_group", row.get("demand_group"))
            return _highlight(
                result,
                f"用户需求：优先回应{group}",
                (
                    f"该需求出现 {_display_cell('comments', row.get('comments'))} 次，"
                    f"占评论 {_display_cell('comment_share', row.get('comment_share'))}。"
                    "可以把它写进标题、正文、评论区回复和商品详情。"
                ),
            )
        return _highlight_from_primary_finding(result, "用户需求")

    if result.task_id == "weekly_experiment_matrix":
        row_count = len(result.tables.get("experiment_plan", []))
        return _highlight(
            result,
            "实验计划：用一周排期验证结论",
            (
                f"报告已生成 {_display_cell('planned_rows', row_count)} 个发布档期。"
                "执行时一次只改一个变量，才看得出是商品、封面还是文案在起作用。"
            ),
        )

    return _highlight_from_primary_finding(result, result.title)


def _highlight(result: AnalysisResult, title: str, body: str) -> dict[str, str]:
    return {
        "title": title,
        "body": body,
        **_confidence_chip(_primary_confidence(result)),
    }


def _highlight_from_primary_finding(result: AnalysisResult, prefix: str) -> dict[str, str] | None:
    if not result.findings:
        return None
    summary = _finding_summary(result.findings[0])
    return {
        **summary,
        "title": f"{prefix}：{summary['title']}",
    }


def _recommended_actions(findings: list[Finding]) -> list[dict[str, str]]:
    actions = [
        {
            "title": finding.title,
            "body": finding.recommended_action,
            **_confidence_chip(reader_confidence(finding)),
        }
        for finding in findings
        if finding.recommended_action
    ]
    if actions:
        return actions[:5]
    return [
        {
            "title": "先补齐关键数据",
            "body": "当前报告没有足够的建议动作。优先补齐笔记、SKU、订单和评论数据后再重新生成。",
            **_confidence_chip(_confidence.NOT_JUDGABLE),
        }
    ]


def _business_actions(
    results: list[AnalysisResult], findings: list[Finding]
) -> list[dict[str, str]]:
    results_by_task = {result.task_id: result for result in results}
    actions: list[dict[str, str]] = []

    product = results_by_task.get("product_opportunity_matrix")
    product_row = _first_row(product, "product_opportunities") if product else None
    if product_row:
        sku = str(product_row.get("sku_name") or "头部 SKU")
        actions.append(
            _action(
                product,
                "商品实验",
                sku,
                (
                    f"它当前销售件数 {_display_cell('units', product_row.get('units'))}，"
                    f"销售额 {_display_cell('gmv', product_row.get('gmv'))}，"
                    f"机会类型是{_display_cell('opportunity_type', product_row.get('opportunity_type'))}。"
                ),
                "围绕同一个 SKU 连续发 2 到 3 条内容，只改变文案角度或封面构图中的一个变量。",
                "收藏率、阅读率、评论里的购买意向，以及后续 SKU 销量。",
                "如果连续 3 条内容收藏率都低于账号平均值，暂停放量，先换卖点或封面。",
            )
        )

    copy_result = results_by_task.get("copy_angle_effect") or results_by_task.get(
        "content_portfolio_optimization"
    )
    copy_row = None
    if copy_result is not None:
        copy_row = _first_row(copy_result, "copy_effects") or _first_row(
            copy_result, "portfolio_mix"
        )
    if copy_row:
        angle = _display_cell("copy_angle", copy_row.get("copy_angle"))
        actions.append(
            _action(
                copy_result,
                "内容角度",
                str(angle),
                (
                    f"该角度已有 {_display_cell('notes', copy_row.get('notes'))} 篇样本，"
                    f"平均阅读数 {_display_cell('avg_reads', copy_row.get('avg_reads'))}。"
                ),
                "选择同一 SKU、相近发布时间，分别测试这个角度和一个对照角度。",
                "收藏率、评论问题类型、阅读到收藏的转化。",
                "如果阅读不错但收藏弱，保留角度，重写首段和购买理由。",
            )
        )

    demand = results_by_task.get("comment_demand_mining")
    demand_row = _first_row(demand, "comment_demands") if demand else None
    if demand_row:
        group = _display_cell("demand_group", demand_row.get("demand_group"))
        actions.append(
            _action(
                demand,
                "用户需求",
                str(group),
                (
                    f"这个需求占评论 {_display_cell('comment_share', demand_row.get('comment_share'))}，"
                    f"代表问题包括：{_display_cell('example_comments', demand_row.get('example_comments'))}。"
                ),
                "把这个问题写进标题、正文 FAQ、置顶评论回复和商品详情页说明。",
                "同类问题是否减少、购买入口评论是否增加、收藏率是否改善。",
                "如果问题重复出现，说明内容没有解释清楚，需要把答案提前到封面或标题。",
            )
        )

    reshoot = results_by_task.get("reshoot_repost_candidates")
    reshoot_row = _first_row(reshoot, "reshoot_candidates") if reshoot else None
    if reshoot_row:
        title = str(reshoot_row.get("title") or "队首候选")
        actions.append(
            _action(
                reshoot,
                "重拍重发",
                title,
                (
                    f"这篇笔记收藏率 {_display_cell('collect_rate', reshoot_row.get('collect_rate'))}，"
                    f"但仍有 {_display_cell('read_gap_to_max', reshoot_row.get('read_gap_to_max'))} 的阅读差距。"
                ),
                "保留原主题和商品，重新拍一个更清晰的开场画面，并把标题卖点前置。",
                "阅读率、3 秒内停留表现、收藏率是否同时提升。",
                "如果阅读提升但收藏下降，说明新封面吸引了泛流量，需要收窄卖点。",
            )
        )

    experiment = results_by_task.get("weekly_experiment_matrix")
    experiment_rows = experiment.tables.get("experiment_plan", []) if experiment else []
    if experiment_rows:
        first = experiment_rows[0]
        actions.append(
            _action(
                experiment,
                "发布排期",
                "执行 7 天实验矩阵",
                (
                    f"第一条建议在 {_display_cell('date', first.get('date'))} "
                    f"{_display_cell('slot_time', first.get('slot_time'))} 发布，"
                    f"测试 {_display_cell('sku_name', first.get('sku_name'))} 和"
                    f"{_display_cell('copy_angle', first.get('copy_angle'))}。"
                ),
                "按矩阵发布，记录每条的 SKU、封面、文案角度和发布时间，不要临时混改多个变量。",
                "每条内容的收藏率、阅读率、评论需求和对应 SKU 销量。",
                "如果中途爆款出现，仍保留至少一个对照档期，避免只看单条内容。",
            )
        )

    if actions:
        return actions[:5]

    fallback = _recommended_actions(findings)
    return [
        {
            "task": "先补数据",
            "target": action["title"],
            "why": action["body"],
            "how": "补齐笔记、SKU、订单、内容特征和评论后重新生成报告。",
            "metric": "下一次报告中可判断的模块数量。",
            "stop_rule": "如果核心表仍为空，先不要解读趋势。",
            "confidence": action["confidence"],
            "confidence_class": action.get("confidence_class", "not_judgable"),
            "confidence_help": action.get("confidence_help", ""),
        }
        for action in fallback
    ]


def _action(
    result: AnalysisResult | None,
    task: str,
    target: str,
    why: str,
    how: str,
    metric: str,
    stop_rule: str,
) -> dict[str, str]:
    return {
        "task": task,
        "target": target,
        "why": why,
        "how": how,
        "metric": metric,
        "stop_rule": stop_rule,
        **_confidence_chip(_primary_confidence(result)),
    }


def _evidence_counts(findings: list[Finding]) -> list[dict[str, object]]:
    # Distribution over the single reader-facing 置信度 level, not causal strength —
    # so the summary reads 高/中/低/暂不下定论, matching every chip in the report.
    counts = {level: 0 for level in _confidence.LEVELS}
    for finding in findings:
        level = reader_confidence(finding).level
        counts[level] = counts.get(level, 0) + 1
    return [
        {
            "value": level,
            "label": _confidence.LEVEL_LABELS[level],
            "count": counts[level],
            "help": _confidence.LEVEL_HELP[level],
        }
        for level in _confidence.LEVELS
    ]


def _finding_summary(finding: Finding) -> dict[str, str]:
    # Single reader-facing 置信度 (see reporting.confidence): 描述可靠性 drives it,
    # causal strength is a caveat, so a large-sample observational fact no longer
    # reads as "低". The two-chip (证据/可靠性) layout is gone.
    rc = reader_confidence(finding)
    return {
        "title": finding.title,
        "body": finding.conclusion,
        "confidence": rc.label,
        "confidence_class": rc.level,
        "confidence_help": rc.help,
    }


def _confidence_chip(rc) -> dict[str, str]:
    """Reader-facing confidence fields for a highlight/action/priority chip."""
    return {
        "confidence": rc.label,
        "confidence_class": rc.level,
        "confidence_help": rc.help,
    }


def _primary_confidence(result: AnalysisResult | None):
    if result is None or not result.findings:
        return _confidence.NOT_JUDGABLE
    return reader_confidence(result.findings[0])


def _caveats_with_causal(finding: Finding) -> list[str]:
    """Finding caveats plus the one-line causal footnote (was a separate chip)."""
    rc = reader_confidence(finding)
    caveats = list(finding.caveats)
    if rc.causal_caveat and rc.causal_caveat not in caveats:
        caveats.append(rc.causal_caveat)
    return caveats


def _display_cell(field_name: str, value: object) -> str:
    return _format_scalar(field_name, value)


def _display_value(value: object) -> str:
    return _format_scalar("", value)


def _display_cell_filter(value: object, field_name: str) -> str:
    return _format_scalar(field_name, value)


def _first_row(result: AnalysisResult | None, table_name: str) -> dict[str, object] | None:
    if result is None:
        return None
    rows = result.tables.get(table_name, [])
    return rows[0] if rows else None


def _result_label(task_id: str, title: str) -> str:
    """The business-domain label shown as the small tag above each result block.

    Sourced from the shared :data:`domains.DOMAINS` registry so the tag always
    matches the domain header the block renders under; falls back to the module
    title for any task not yet assigned to a domain.
    """
    for domain_title, _intro, tasks in DOMAINS:
        if task_id in tasks:
            return domain_title
    return title


def _codex_questions(results: list[AnalysisResult]) -> list[str]:
    questions: list[str] = []
    sku = _top_cell(results, "product_opportunity_matrix", "product_opportunities", "sku_name")
    if sku:
        questions.append(f"为什么「{sku}」应该优先测试？")

    angle = _top_cell(results, "copy_angle_effect", "copy_effects", "copy_angle")
    if angle is None:
        angle = _top_cell(
            results,
            "content_portfolio_optimization",
            "portfolio_mix",
            "copy_angle",
        )
    if angle:
        questions.append(f"「{_display_cell('copy_angle', angle)}」文案角度下周应该怎么测？")

    candidate = _top_cell(results, "reshoot_repost_candidates", "reshoot_candidates", "title")
    if candidate:
        questions.append(f"为什么「{candidate}」适合重拍，而不是直接重发？")

    questions.extend(
        [
            "这份报告里最应该先执行哪三件事？",
            "哪些结论只是实验线索，还不能直接当成因果？",
            "为了让下次报告更准，我需要补哪些数据？",
        ]
    )
    return _dedupe(questions)[:6]


def _top_cell(
    results: list[AnalysisResult],
    task_id: str,
    table_name: str,
    field_name: str,
) -> object | None:
    for result in results:
        if result.task_id != task_id:
            continue
        row = _first_row(result, table_name)
        if row is None:
            return None
        return row.get(field_name)
    return None


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
