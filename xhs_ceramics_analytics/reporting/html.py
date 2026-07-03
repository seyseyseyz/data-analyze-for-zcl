import re
from html import escape

from jinja2 import Environment, PackageLoader

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding, Subsection
from xhs_ceramics_analytics.reporting.markdown import render_markdown
from xhs_ceramics_analytics.reporting.section_order import APPENDIX_TASKS
from xhs_ceramics_analytics.reporting.formatting import (
    field_help as _field_help,
    field_label as _field_label,
    format_scalar as _format_scalar,
    should_render_table as _should_render_table,
)
from xhs_ceramics_analytics.reporting import charts


_EVIDENCE_LABELS = {
    "strong": "高",
    "medium": "中",
    "weak": "低",
    "not_judgable": "不可判断",
}

_EVIDENCE_HELP = {
    "strong": "数据较充分，可以直接作为经营依据。",
    "medium": "可以用于本周决策，但建议继续观察。",
    "weak": "适合作为实验方向，暂不适合直接下定论。",
    "not_judgable": "当前数据不足，需要先补齐导入或埋点。",
}

_MAX_TABLE_ROWS = 20

_BUSINESS_HIGHLIGHT_TASKS = (
    "product_opportunity_matrix",
    "copy_angle_effect",
    "content_portfolio_optimization",
    "comment_demand_mining",
    "reshoot_repost_candidates",
    "weekly_experiment_matrix",
)

_ANALYSIS_GROUPS = (
    {
        "title": "经营诊断：生意怎么样",
        "description": (
            "先看整体经营结构、搜索承接效率、人群结构和退款结构，"
            "锁定这一阶段最该动的环节，再往下看内容和商品细节。"
        ),
        "tasks": (
            "core_business_diagnosis",
            "search_efficiency_diagnosis",
            "channel_structure_diagnosis",
            "audience_structure_diagnosis",
            "refund_structure_diagnosis",
            "refund_root_cause_diagnosis",
        ),
    },
    {
        "title": "商品：卖什么",
        "description": "先看 SKU 的 GMV/退款结构与销售反馈，哪些商品还需要继续补内容或补销售数据。",
        "tasks": (
            "sku_structure_diagnosis",
            "product_opportunity_matrix",
            "sku_counterfactual_lift",
            "content_response_curve",
        ),
    },
    {
        "title": "内容：发什么",
        "description": "先看笔记的商业效能（GMV/转化/引流/退款），再把封面、文案角度和内容组合拆开看，避免只凭单篇爆款做判断。",
        "tasks": (
            "note_commercial_diagnosis",
            "cover_style_effect",
            "copy_angle_effect",
            "product_content_interaction",
            "content_portfolio_optimization",
        ),
    },
    {
        "title": "用户需求：用户在问什么",
        "description": "从评论里提炼价格、容量、购买入口和送礼等真实疑问，反推内容和详情页要补什么。",
        "tasks": ("comment_demand_mining",),
    },
    {
        "title": "实验：下周怎么验证",
        "description": "把当前结论转成可以执行的一周计划，并标出适合重拍或重发的候选笔记。",
        "tasks": (
            "weekly_experiment_matrix",
            "reshoot_repost_candidates",
            "hypothesis_knowledge_base",
        ),
    },
    {
        "title": "基础参考：账号与漏斗",
        "description": "账号基线、笔记漏斗和周复盘作为背景参照，帮助判断哪些结论能直接用、哪些只能当实验线索。",
        "tasks": (
            "account_baseline",
            "note_funnel",
            "weekly_business_review",
        ),
    },
)

# Data-quality sections close the report as an appendix — see reporting.section_order.
_APPENDIX_GROUP = {
    "title": "附录：数据质量与口径说明",
    "description": "数据导入、口径与完整度说明，为上面所有结论标注可信度；阻断性问题在建库阶段已处置，这里只作透明留证。",
}

_TABLE_LABELS = {
    "table_row_counts": "导入数据检查",
    "daily_posts": "账号日发布与互动",
    "note_funnel": "笔记漏斗明细",
    "cover_effects": "封面效果对比",
    "copy_effects": "文案角度对比",
    "product_opportunities": "商品机会明细",
    "sku_lift": "SKU 销量响应",
    "response_windows": "内容响应窗口",
    "product_interactions": "商品与内容组合",
    "portfolio_mix": "内容组合占比",
    "comment_demands": "评论需求分组",
    "experiment_plan": "下周实验排期",
    "reshoot_candidates": "重拍候选笔记",
    "hypotheses": "经营假设库",
    "weekly_sections": "周复盘模块",
    "ad_data_quality": "投放数据可用性",
    "paid_traffic_efficiency": "投放效率明细",
    # --- 经营/搜索/人群/退款/渠道 深度诊断模块 ---
    "business_snapshot": "整体经营快照",
    "business_trend": "GMV 趋势与结构性变化",
    "carrier_structure": "载体 GMV 结构",
    "traffic_channel_structure": "流量渠道结构",
    "carrier_search_efficiency": "载体搜索效率",
    "search_conversion_trend": "搜索转化趋势",
    "search_term_opportunities": "高机会/高流失搜索词",
    "audience_composition": "人群构成",
    "audience_conversion": "人群转化",
    "audience_conversion_comparison": "新老客转化对比",
    "first_purchase_cycle_funnel": "首购周期漏斗",
    "sku_gmv_pareto": "SKU GMV 帕累托",
    "sku_category_mix": "SKU 类目结构",
    "sku_refund_outliers": "高退款 SKU",
    "sku_conversion_and_aov": "SKU 加购转化与客单价",
    "note_gmv_pareto": "笔记 GMV 帕累托",
    "note_conversion_outliers": "高流量低转化笔记",
    "note_refund_outliers": "高退款笔记",
    "high_refund_notes": "高退款笔记",
    "refund_layer_breakdown": "退款分层拆解",
    "refund_trend": "退款趋势",
    "carrier_refund_comparison": "载体退款对比",
    "shop_source_structure": "店铺来源结构",
    "product_refund_concentration": "商品退款集中度",
    "channel_scale": "渠道规模结构",
    "channel_conversion": "渠道转化对比",
    "channel_refund": "渠道退款对比",
    "refund_by_category": "分品类退款",
    "refund_by_price_band": "分价格带退款",
    "refund_by_ship_stage": "分发货环节退款",
}

_USER_TABLE_COLUMNS = {
    "table_row_counts": ("table", "rows"),
    "daily_posts": ("date", "posts", "reads", "collects", "comments"),
    "note_funnel": (
        "note_id",
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
        "note_id",
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
}



def render_html(results: list[AnalysisResult]) -> str:
    env = Environment(
        loader=PackageLoader("xhs_ceramics_analytics.reporting", "templates"),
        autoescape=True,
    )
    env.filters["evidence_label"] = _evidence_label
    env.filters["field_label"] = _field_label
    env.filters["field_help"] = _field_help
    env.filters["display_value"] = _display_value
    env.filters["display_cell"] = _display_cell_filter
    template = env.get_template("report.html.j2")
    return template.render(
        markdown_report=render_markdown(results),
        report=_build_report_context(results),
        results=results,
    )


def render_markdown_document_html(markdown_text: str, title: str | None = None) -> str:
    report_title = title or _extract_markdown_title(markdown_text) or "小红书账号分析报告"
    body_html = _markdown_document_body(markdown_text)
    escaped_title = escape(report_title)
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
    .report-shell {{
      width: min(960px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 72px;
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
      .report-shell {{ width: min(100% - 24px, 960px); }}
      .report-card {{ border-radius: 8px; }}
      h2 {{ font-size: 26px; }}
    }}
  </style>
</head>
<body>
  <main class="report-shell">
    <header class="topbar">
      <div class="brand">小红书经营分析</div>
      <div>Single-file HTML</div>
    </header>
    <article class="report-card">
      <span class="eyebrow">Integrated Report</span>
{body_html}
    </article>
  </main>
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


def _markdown_document_body(markdown_text: str) -> str:
    lines = markdown_text.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
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

    return "\n".join(f"      {block}" for block in blocks)


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


def _build_report_context(results: list[AnalysisResult]) -> dict[str, object]:
    findings = [finding for result in results for finding in result.findings]
    total_table_rows = sum(len(rows) for result in results for rows in result.tables.values())
    result_views = [_result_view(result) for result in results]
    return {
        "task_count": len(results),
        "finding_count": len(findings),
        "table_count": sum(len(result.tables) for result in results),
        "total_table_rows": total_table_rows,
        "highlights": _business_highlights(results),
        "actions": _business_actions(results, findings),
        "analysis_groups": _analysis_groups(result_views),
        "evidence_counts": _evidence_counts(findings),
        "evidence_chart_svg": charts.evidence_distribution(_evidence_counts(findings)),
        "codex_questions": _codex_questions(results),
        "glossary": [
            {
                "term": "可信度",
                "definition": "说明这条结论能被多大程度用于经营决策，不代表结论有没有价值。",
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
        "caveats": finding.caveats,
        "recommended_action": finding.recommended_action,
        "evidence_reason": finding.evidence_reason,
        "confounders": finding.confounders,
        "next_test": finding.next_test,
        "appendix": finding.appendix,
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

    showing_count = min(len(rows), _MAX_TABLE_ROWS)
    display_text = f"共 {len(rows)} 行，当前展示 {showing_count} 行"
    if len(rows) > _MAX_TABLE_ROWS:
        display_text = f"共 {len(rows)} 行，当前展示前 {showing_count} 行"

    return {
        "name": table_name,
        "label": _TABLE_LABELS.get(table_name, table_name.replace("_", " ")),
        "row_count": len(rows),
        "showing_count": showing_count,
        "display_text": display_text,
        "user_columns": [_column_view(column) for column in user_columns],
        "technical_columns": [_column_view(column) for column in all_columns],
        "user_rows": [_row_cells(row, user_columns) for row in rows[:_MAX_TABLE_ROWS]],
        "technical_rows": [_row_cells(row, all_columns) for row in rows[:_MAX_TABLE_ROWS]],
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


def _analysis_groups(result_views: list[dict[str, object]]) -> list[dict[str, object]]:
    views_by_task = {str(view["task_id"]): view for view in result_views}
    grouped: list[dict[str, object]] = []
    used: set[str] = set()
    for group in _ANALYSIS_GROUPS:
        views = [views_by_task[task_id] for task_id in group["tasks"] if task_id in views_by_task]
        if not views:
            continue
        used.update(str(view["task_id"]) for view in views)
        grouped.append(
            {
                "title": group["title"],
                "description": group["description"],
                "results": views,
            }
        )

    appendix_views = [
        views_by_task[task_id] for task_id in APPENDIX_TASKS if task_id in views_by_task
    ]
    used.update(str(view["task_id"]) for view in appendix_views)

    remaining = [view for view in result_views if str(view["task_id"]) not in used]
    if remaining:
        grouped.append(
            {
                "title": "其他分析",
                "description": "这些模块暂时没有归入固定经营问题，但仍保留结论和明细，方便继续扩展。",
                "results": remaining,
            }
        )

    # Appendix always closes the report, after 其他分析.
    if appendix_views:
        grouped.append(
            {
                "title": _APPENDIX_GROUP["title"],
                "description": _APPENDIX_GROUP["description"],
                "results": appendix_views,
            }
        )
    return grouped


def _highlights(findings: list[Finding]) -> list[dict[str, str]]:
    highlighted = findings[:3]
    if not highlighted:
        return [
            {
                "title": "暂无可读结论",
                "body": "当前数据还不足以生成经营判断，请先完成数据导入。",
                "evidence": "不可判断",
                "evidence_class": "not_judgable",
                "help": _EVIDENCE_HELP["not_judgable"],
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

    if result.task_id == "reshoot_repost_candidates":
        row = _first_row(result, "reshoot_candidates")
        if row:
            title = str(row.get("title") or row.get("note_id") or "队首候选")
            return _highlight(
                result,
                f"重拍机会：先复用「{title}」",
                (
                    f"这篇笔记收藏率 {_display_cell('collect_rate', row.get('collect_rate'))}，"
                    f"入选原因是{_display_cell('reason', row.get('reason'))}。"
                    "建议保留核心商品和角度，只改开场画面或封面做对照。"
                ),
            )
        return _highlight_from_primary_finding(result, "重拍机会")

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
    evidence_value = _primary_evidence_value(result)
    return {
        "title": title,
        "body": body,
        "evidence": _EVIDENCE_LABELS.get(evidence_value, evidence_value),
        "evidence_class": evidence_value,
        "help": _EVIDENCE_HELP.get(evidence_value, "请结合数据限制一起阅读。"),
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
            "evidence": _EVIDENCE_LABELS.get(
                finding.evidence_strength.value, finding.evidence_strength.value
            ),
            "evidence_class": finding.evidence_strength.value,
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
            "evidence": "不可判断",
            "evidence_class": "not_judgable",
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
        title = str(reshoot_row.get("title") or reshoot_row.get("note_id") or "队首候选")
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
            "evidence": action["evidence"],
            "evidence_class": action.get("evidence_class", "not_judgable"),
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
    evidence_value = _primary_evidence_value(result) if result else "not_judgable"
    return {
        "task": task,
        "target": target,
        "why": why,
        "how": how,
        "metric": metric,
        "stop_rule": stop_rule,
        "evidence": _EVIDENCE_LABELS.get(evidence_value, evidence_value),
        "evidence_class": evidence_value,
    }


def _evidence_counts(findings: list[Finding]) -> list[dict[str, object]]:
    counts = {key: 0 for key in _EVIDENCE_LABELS}
    for finding in findings:
        counts[finding.evidence_strength.value] = counts.get(finding.evidence_strength.value, 0) + 1
    return [
        {
            "value": value,
            "label": _EVIDENCE_LABELS[value],
            "count": counts[value],
            "help": _EVIDENCE_HELP[value],
        }
        for value in ("strong", "medium", "weak", "not_judgable")
    ]


def _finding_summary(finding: Finding) -> dict[str, str]:
    evidence_value = finding.evidence_strength.value
    return {
        "title": finding.title,
        "body": finding.conclusion,
        "evidence": _EVIDENCE_LABELS.get(evidence_value, evidence_value),
        "evidence_class": evidence_value,
        "help": _EVIDENCE_HELP.get(evidence_value, "请结合数据限制一起阅读。"),
    }


def _evidence_label(value: str) -> str:
    return _EVIDENCE_LABELS.get(value, value)


def _display_cell(field_name: str, value: object) -> str:
    return _format_scalar(field_name, value)


def _display_value(value: object) -> str:
    return _format_scalar("", value)


def _display_cell_filter(value: object, field_name: str) -> str:
    return _format_scalar(field_name, value)


def _primary_evidence_value(result: AnalysisResult | None) -> str:
    if result is None or not result.findings:
        return "not_judgable"
    return result.findings[0].evidence_strength.value


def _first_row(result: AnalysisResult | None, table_name: str) -> dict[str, object] | None:
    if result is None:
        return None
    rows = result.tables.get(table_name, [])
    return rows[0] if rows else None


def _result_label(task_id: str, title: str) -> str:
    for group in _ANALYSIS_GROUPS:
        if task_id in group["tasks"]:
            return str(group["title"]).split("：", maxsplit=1)[0]
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
