"""Deterministic reader-facing field definitions for report tooltips.

Only confirmed sources are eligible: the maintained field vocabulary, a validated
report metric binding, or an accepted platform source binding in the exact table
context. Review candidates and unknown fields deliberately return ``None``.
"""

from __future__ import annotations

import re
from hashlib import sha256
from dataclasses import dataclass
from functools import lru_cache
from html import escape

from xhs_ceramics_analytics.contracts.metrics import (
    MetricAggregation,
    MetricSpec,
    load_metric_registry,
)
from xhs_ceramics_analytics.contracts.platform_catalog import (
    PlatformMetric,
    PlatformMetricBinding,
    load_platform_metric_catalog,
    load_source_binding_registry,
    validate_catalog_bundle,
)
from xhs_ceramics_analytics.reporting.field_labels import FIELD_LABELS


@dataclass(frozen=True)
class TooltipDetail:
    label: str
    value: str


@dataclass(frozen=True)
class FieldTooltipDefinition:
    summary: str
    details: tuple[TooltipDetail, ...] = ()


FIELD_TOOLTIP_STYLE = """
    .field-tooltip {
      position: relative;
      display: inline-flex;
      align-items: baseline;
      margin: 0;
      padding: 0;
      border: 0;
      background: transparent;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: inherit;
      outline: none;
    }
    .field-tooltip-label {
      color: inherit;
      border-bottom: 1px dashed #8F9697;
    }
    .field-tooltip-content {
      position: fixed;
      z-index: 80;
      left: 50%;
      bottom: 24px;
      width: min(360px, calc(100vw - 32px));
      max-width: calc(100vw - 32px);
      padding: 9px 11px;
      border: 1px solid #D9D9D4;
      border-radius: 8px;
      background: #242424;
      color: #FFFFFF;
      font-family: 'SF Pro Display', 'Geist Sans', 'Helvetica Neue', sans-serif;
      font-size: 12px;
      line-height: 1.5;
      font-weight: 400;
      white-space: normal;
      text-align: left;
      box-shadow: 0 8px 24px rgba(17, 17, 17, 0.16);
      visibility: hidden;
      opacity: 0;
      pointer-events: none;
      transform: translate(-50%, 5px);
      transition: opacity 120ms ease, transform 120ms ease, visibility 120ms ease;
    }
    .field-tooltip-summary,
    .field-tooltip-detail { display: block; }
    .field-tooltip-detail {
      display: grid;
      grid-template-columns: 64px minmax(0, 1fr);
      gap: 8px;
      margin-top: 7px;
      padding-top: 7px;
      border-top: 1px solid rgba(255, 255, 255, 0.14);
    }
    .field-tooltip-key { color: #BFC5C7; white-space: nowrap; }
    .field-tooltip:hover .field-tooltip-content,
    .field-tooltip:focus-visible .field-tooltip-content {
      visibility: visible;
      opacity: 1;
      transform: translate(-50%, 0);
    }
    .field-tooltip:focus-visible {
      border-radius: 3px;
      box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px #7A7A75;
    }
    @media (min-width: 701px) {
      .field-tooltip--anchored .field-tooltip-content {
        width: max-content;
        max-width: min(320px, calc(100vw - 24px));
        bottom: auto;
        transform: translateY(var(--field-tooltip-enter-y, 4px));
      }
      .field-tooltip--anchored:hover .field-tooltip-content,
      .field-tooltip--anchored:focus-visible .field-tooltip-content {
        transform: translateY(0);
      }
    }
    @media print {
      .field-tooltip-content { display: none !important; }
    }
"""


FIELD_TOOLTIP_SCRIPT = r"""<script id="field-tooltip-position">
(() => {
  const SELECTOR = ".field-tooltip";
  const MOBILE_QUERY = "(max-width: 700px)";
  const EDGE = 12;
  const GAP = 8;
  const triggers = Array.from(document.querySelectorAll(SELECTOR));

  const reset = (trigger) => {
    const tooltip = trigger.querySelector(".field-tooltip-content");
    trigger.classList.remove("field-tooltip--anchored");
    delete trigger.dataset.tooltipPlacement;
    if (!tooltip) return;
    for (const property of ["left", "top", "bottom", "--field-tooltip-enter-y"]) {
      tooltip.style.removeProperty(property);
    }
  };

  const position = (trigger) => {
    const tooltip = trigger.querySelector(".field-tooltip-content");
    if (!tooltip) return;
    if (window.matchMedia("(max-width: 700px)").matches) {
      reset(trigger);
      return;
    }

    trigger.classList.add("field-tooltip--anchored");
    tooltip.style.left = "0px";
    tooltip.style.top = "0px";
    tooltip.style.bottom = "auto";

    const triggerRect = trigger.getBoundingClientRect();
    const tooltipRect = tooltip.getBoundingClientRect();
    const centeredLeft = triggerRect.left + triggerRect.width / 2 - tooltipRect.width / 2;
    const maxLeft = Math.max(EDGE, window.innerWidth - tooltipRect.width - EDGE);
    const left = Math.min(Math.max(EDGE, centeredLeft), maxLeft);
    const above = triggerRect.top - tooltipRect.height - GAP;
    const below = triggerRect.bottom + GAP;
    const belowFits = below + tooltipRect.height <= window.innerHeight - EDGE;
    let top;
    let placement;

    if (above >= EDGE) {
      top = above;
      placement = "top";
    } else if (belowFits) {
      top = below;
      placement = "bottom";
    } else if (triggerRect.top >= window.innerHeight - triggerRect.bottom) {
      top = Math.max(EDGE, above);
      placement = "top";
    } else {
      top = Math.min(
        below,
        Math.max(EDGE, window.innerHeight - tooltipRect.height - EDGE)
      );
      placement = "bottom";
    }

    tooltip.style.left = `${Math.round(left)}px`;
    tooltip.style.top = `${Math.round(top)}px`;
    tooltip.style.setProperty(
      "--field-tooltip-enter-y",
      placement === "top" ? "4px" : "-4px"
    );
    trigger.dataset.tooltipPlacement = placement;
  };

  for (const trigger of triggers) {
    trigger.addEventListener("pointerenter", () => position(trigger));
    trigger.addEventListener("focus", () => position(trigger));
  }

  const refresh = () => {
    for (const trigger of triggers) {
      if (trigger.matches(":hover") || document.activeElement === trigger) {
        position(trigger);
      } else if (window.matchMedia(MOBILE_QUERY).matches) {
        reset(trigger);
      }
    }
  };
  window.addEventListener("resize", refresh);
  document.addEventListener("scroll", refresh, true);
})();
</script>"""


_AGGREGATION_LABELS = {
    MetricAggregation.SUM_AS_PERSON_DAYS: "逐日去重后按人次相加",
    MetricAggregation.MEAN_DAILY: "按有效日期计算日均",
    MetricAggregation.MEAN_OF_DAILY_RATIOS: "先计算每日比率，再对有效日期求平均",
}

_GRAIN_LABELS = {
    "shop_day": "店铺 × 日期",
    "shop_day_sum": "店铺 × 观察期汇总",
    "shop_month": "店铺 × 月",
    "shop_window": "店铺 × 观察期",
    "carrier": "成交来源",
    "sku": "SKU",
    "note": "笔记",
    "search_term": "搜索词",
    "audience": "人群",
    "price_band": "价格带",
    "category_l2": "二级品类",
}

_TIME_LABELS = {
    "payment_time": "订单支付时间",
    "refund_completion_time": "退款完成时间",
    "analysis_window": "报告观察期",
    "event_time": "行为发生时间",
    "lifetime_since_publish": "自发布以来",
}


@lru_cache(maxsize=1)
def _metric_by_id() -> dict[str, MetricSpec]:
    try:
        return {metric.metric_id: metric for metric in load_metric_registry().metrics}
    except ValueError:
        return {}


@lru_cache(maxsize=1)
def _accepted_platform_definitions() -> dict[
    tuple[str, str], tuple[PlatformMetricBinding, PlatformMetric]
]:
    try:
        catalog = load_platform_metric_catalog()
        bindings = load_source_binding_registry()
        validate_catalog_bundle(catalog, bindings)
    except ValueError:
        return {}

    metrics = {metric.platform_metric_id: metric for metric in catalog.metrics}
    definitions: dict[tuple[str, str], tuple[PlatformMetricBinding, PlatformMetric]] = {}
    ambiguous: set[tuple[str, str]] = set()
    for binding in bindings.bindings:
        key = (binding.canonical_table, binding.canonical_field)
        metric = metrics.get(binding.platform_metric_id)
        if metric is None:
            continue
        existing = definitions.get(key)
        if existing is not None and (
            existing[1].definition_sha256 != metric.definition_sha256
            or existing[0].time_basis != binding.time_basis
            or existing[0].grain != binding.grain
        ):
            ambiguous.add(key)
            continue
        definitions[key] = (binding, metric)
    return {key: value for key, value in definitions.items() if key not in ambiguous}


def tooltip_definition(
    field_name: str,
    *,
    table_name: str | None = None,
    metric_id: str | None = None,
) -> FieldTooltipDefinition | None:
    """Resolve one confirmed definition, preferring the most specific source."""
    if table_name is not None:
        platform = _accepted_platform_definitions().get((table_name, field_name))
        if platform is not None:
            return _platform_definition(*platform)

    metric = _metric_by_id().get(metric_id) if metric_id else None
    maintained = FIELD_LABELS.get(field_name)
    if metric is not None:
        return _metric_definition(metric, maintained[1] if maintained else None)
    if maintained is not None:
        return FieldTooltipDefinition(summary=maintained[1])
    return None


def field_tooltip_id(scope: str, field_name: str) -> str:
    """Return a deterministic, document-safe tooltip id."""
    digest = sha256(f"{scope}:{field_name}".encode("utf-8")).hexdigest()[:12]
    return f"field-tip-{digest}"


def field_tooltip_markup(
    field_name: str,
    label: str,
    *,
    scope: str,
    table_name: str | None = None,
    metric_id: str | None = None,
) -> str:
    """Render escaped hover/focus markup only when a confirmed definition exists."""
    definition = tooltip_definition(
        field_name,
        table_name=table_name,
        metric_id=metric_id,
    )
    escaped_label = escape(str(label))
    if definition is None:
        return escaped_label

    tooltip_id = field_tooltip_id(scope, field_name)
    details = "".join(
        '<span class="field-tooltip-detail">'
        f'<span class="field-tooltip-key">{escape(detail.label)}</span>'
        f'<span>{escape(detail.value)}</span></span>'
        for detail in definition.details
    )
    return (
        '<button type="button" class="field-tooltip" tabindex="0" '
        f'aria-describedby="{tooltip_id}">'
        f'<strong class="field-tooltip-label">{escaped_label}</strong>'
        f'<span id="{tooltip_id}" class="field-tooltip-content" role="tooltip">'
        f'<span class="field-tooltip-summary">{escape(definition.summary)}</span>'
        f"{details}</span></button>"
    )


def _metric_definition(metric: MetricSpec, maintained_help: str | None) -> FieldTooltipDefinition:
    aggregation = _AGGREGATION_LABELS.get(metric.aggregation)
    complex_metric = bool(
        metric.notes
        or aggregation
        or metric.distinct_scope
        or metric.numerator
        or metric.proxy
    )
    summary = maintained_help or f"{metric.display_name}。"
    if metric.aggregation == MetricAggregation.SUM_AS_PERSON_DAYS:
        summary = "逐日去重人数之和，只能称人次；不是观察期唯一人数。"
    elif metric.notes and _merchant_readable(metric.notes):
        summary = metric.notes

    details: list[TooltipDetail] = []
    if complex_metric and aggregation:
        details.append(TooltipDetail("统计方式", aggregation))
    if complex_metric:
        grain = _GRAIN_LABELS.get(str(metric.grain))
        if grain:
            details.append(TooltipDetail("数据粒度", grain))
    if metric.proxy and metric.proxy_label:
        details.append(TooltipDetail("指标性质", metric.proxy_label))
    return FieldTooltipDefinition(summary=summary, details=tuple(details))


def _merchant_readable(notes: str) -> bool:
    machine_tokens = ("_", "action_license", "composition/", "mechanism_")
    return not any(token in notes for token in machine_tokens)


def _platform_definition(
    binding: PlatformMetricBinding,
    metric: PlatformMetric,
) -> FieldTooltipDefinition:
    details: list[TooltipDetail] = []
    time_basis = _TIME_LABELS.get(str(binding.time_basis))
    if time_basis:
        details.append(TooltipDetail("时间口径", time_basis))
    grain = _GRAIN_LABELS.get(str(binding.grain))
    if grain:
        details.append(TooltipDetail("数据粒度", grain))
    return FieldTooltipDefinition(
        summary=_concise_platform_description(metric.description),
        details=tuple(details),
    )


def _concise_platform_description(description: str) -> str:
    """Keep the definition and first decisive rule, not the full platform manual."""
    for marker in ("；统计逻辑：", "；说明："):
        if marker not in description:
            continue
        lead, remainder = description.split(marker, 1)
        first_rule = re.split(r"[；。]", re.sub(r"^（?1）", "", remainder), maxsplit=1)[0]
        return f"{lead}；{first_rule}。"
    return description
