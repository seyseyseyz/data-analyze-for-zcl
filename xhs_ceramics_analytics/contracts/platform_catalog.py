from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CatalogScope(StrEnum):
    CURRENT = "current"
    DEFERRED = "deferred"


class MetricReviewStatus(StrEnum):
    BOUND = "bound"
    NEW_CONTRACT = "new_contract"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class BindingStatus(StrEnum):
    ACCEPTED = "accepted"
    PROPOSED = "proposed"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class BindingMatchBasis(StrEnum):
    EXACT_EXISTING_ALIAS = "exact_existing_alias"
    REVIEWED_SEMANTIC = "reviewed_semantic"


class BindingConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"


class BindingGrain(StrEnum):
    SHOP_DAY = "shop_day"
    SKU_WINDOW = "sku_window"
    NOTE_WINDOW = "note_window"
    SEARCH_CARRIER_DAY = "search_carrier_day"
    SEARCH_TERM_WINDOW = "search_term_window"
    SHOP_AUDIENCE_CYCLE_DAY = "shop_audience_cycle_day"
    SHOP_AUDIENCE_CYCLE_SOURCE_DAY = "shop_audience_cycle_source_day"
    ACCOUNT_CHANNEL_NOTE_TYPE_WINDOW = "account_channel_note_type_window"
    ACCOUNT_CARRIER_WINDOW = "account_carrier_window"


class BindingValueEncoding(StrEnum):
    DECIMAL = "decimal"
    INTEGER = "integer"
    RATIO_0_1 = "ratio_0_1"
    PERCENT_0_100 = "percent_0_100"
    DURATION_SECONDS = "duration_seconds"
    DURATION_MINUTES = "duration_minutes"


class BindingAggregation(StrEnum):
    DIRECT = "direct"
    SUM = "sum"
    AVERAGE = "average"
    DISTINCT_COUNT = "distinct_count"
    RECOMPUTE_RATIO = "recompute_ratio"


class SourceBindingRuntimeMode(StrEnum):
    DISABLED = "disabled"
    OBSERVE = "observe"


class SourceBindingRuntimeScope(StrEnum):
    AGENT_CONTEXT = "agent_context"


class BusinessDomain(StrEnum):
    OVERVIEW = "overview"
    TRANSACTION = "transaction"
    PRODUCT = "product"
    TRAFFIC = "traffic"
    NOTES = "notes"
    SEARCH = "search"
    REFUND = "refund"
    SHOP_PAGE = "shop_page"
    CUSTOMER_SERVICE = "customer_service"
    LOGISTICS = "logistics"
    LIVE = "live"
    GROUP_CHAT = "group_chat"
    REVIEWS = "reviews"
    AFTER_SALES = "after_sales"
    BUYER = "buyer"
    UNKNOWN = "unknown"


class MeasureKind(StrEnum):
    AMOUNT_TOTAL = "amount_total"
    AVERAGE_AMOUNT = "average_amount"
    NET_AMOUNT = "net_amount"
    RATIO = "ratio"
    SHARE = "share"
    DURATION_AVERAGE = "duration_average"
    DISTINCT_COUNT = "distinct_count"
    EVENT_COUNT = "event_count"
    COUNT = "count"


class MetricUnit(StrEnum):
    CNY = "cny"
    PERCENT = "percent"
    COUNT = "count"
    SECONDS = "seconds"
    MINUTES = "minutes"
    UNKNOWN = "unknown"


class MetricCaliber(StrEnum):
    AMOUNT = "amount"
    USER_COUNT = "user_count"
    ORDER_COUNT = "order_count"
    ITEM_COUNT = "item_count"
    EVENT_COUNT = "event_count"
    PACKAGE_COUNT = "package_count"
    NOTE_COUNT = "note_count"
    SESSION_COUNT = "session_count"
    DURATION = "duration"
    DIMENSIONLESS = "dimensionless"
    UNKNOWN = "unknown"


class TimeAnchor(StrEnum):
    PAYMENT_TIME = "payment_time"
    REFUND_COMPLETION_TIME = "refund_completion_time"
    ANALYSIS_WINDOW = "analysis_window"
    EVENT_TIME = "event_time"
    LIFETIME_SINCE_PUBLISH = "lifetime_since_publish"
    UNKNOWN = "unknown"


class Additivity(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class Boundedness(StrEnum):
    BOUNDED_0_1 = "bounded_0_1"
    MAY_EXCEED_1 = "may_exceed_1"
    UNKNOWN = "unknown"


class RefundInclusion(StrEnum):
    GROSS_INCLUDES_REFUNDS = "gross_includes_refunds"
    NET_AFTER_REFUND = "net_after_refund"
    REFUND_POOL = "refund_pool"
    UNKNOWN = "unknown"


class ClassificationConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CandidateBindingStatus(StrEnum):
    CLASSIFIED_UNMAPPED = "classified_unmapped"
    PROPOSED_EXACT = "proposed_exact"
    REVIEW_REQUIRED = "review_required"
    APPROVED = "approved"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PlatformMetric(StrictModel):
    platform_metric_id: int = Field(gt=0)
    display_name: NonBlankStr
    description: NonBlankStr
    modules: list[NonBlankStr] = Field(min_length=1)
    online: bool | None = None
    scope_status: CatalogScope
    review_status: MetricReviewStatus
    business_domains: list[BusinessDomain] = Field(min_length=1)
    measure_kind: MeasureKind
    unit: MetricUnit
    caliber: MetricCaliber
    time_anchor: TimeAnchor
    cross_period_additive: Additivity
    boundedness: Boundedness
    refund_inclusion: RefundInclusion
    division_formula_explicit: bool
    classification_confidence: ClassificationConfidence
    candidate_binding_status: CandidateBindingStatus
    review_required: bool
    review_reasons: list[NonBlankStr]
    classifier_version: NonBlankStr
    endpoint_path: NonBlankStr
    definition_sha256: Sha256

    @field_validator("modules")
    @classmethod
    def validate_modules(cls, modules: list[str]) -> list[str]:
        if len(modules) != len(set(modules)):
            raise ValueError("modules must be unique")
        return modules

    @field_validator("business_domains")
    @classmethod
    def validate_business_domains(cls, domains: list[BusinessDomain]) -> list[BusinessDomain]:
        if len(domains) != len(set(domains)):
            raise ValueError("business_domains must be unique")
        return domains

    @field_validator("endpoint_path")
    @classmethod
    def validate_endpoint_path(cls, endpoint_path: str) -> str:
        paths = endpoint_path.split("; ")
        for path in paths:
            if path == "/unknown":
                continue
            if not path.startswith("/api/"):
                raise ValueError("endpoint_path must be /unknown or an /api/ path")
            if any(token in path for token in ("://", "?", "#", "@", "\\")):
                raise ValueError(
                    "endpoint_path must not contain host, query, fragment, user info, or backslash"
                )
            if ".." in path.split("/") or ".har" in path.casefold():
                raise ValueError("endpoint_path must not contain local path or HAR markers")
        return endpoint_path

    @field_validator("review_reasons")
    @classmethod
    def validate_review_reasons(cls, reasons: list[str]) -> list[str]:
        if len(reasons) != len(set(reasons)):
            raise ValueError("review_reasons must be unique")
        return reasons


class CatalogSummary(StrictModel):
    metric_count: int = Field(ge=0)
    current_count: int = Field(ge=0)
    deferred_count: int = Field(ge=0)
    bound_count: int = Field(ge=0)
    new_contract_count: int = Field(ge=0)
    rejected_count: int = Field(ge=0)


class PlatformMetricCatalog(StrictModel):
    version: Literal[1]
    platform: Literal["xiaohongshu_qianfan"]
    source_snapshot_sha256: Sha256
    summary: CatalogSummary
    metrics: list[PlatformMetric] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> PlatformMetricCatalog:
        metric_ids = [metric.platform_metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("platform_metric_id must be unique")
        if metric_ids != sorted(metric_ids):
            raise ValueError("metrics must be sorted by platform_metric_id")

        expected_summary = CatalogSummary(
            metric_count=len(self.metrics),
            current_count=sum(
                metric.scope_status == CatalogScope.CURRENT for metric in self.metrics
            ),
            deferred_count=sum(
                metric.scope_status == CatalogScope.DEFERRED for metric in self.metrics
            ),
            bound_count=sum(
                metric.review_status == MetricReviewStatus.BOUND for metric in self.metrics
            ),
            new_contract_count=sum(
                metric.review_status == MetricReviewStatus.NEW_CONTRACT for metric in self.metrics
            ),
            rejected_count=sum(
                metric.review_status == MetricReviewStatus.REJECTED for metric in self.metrics
            ),
        )
        if self.summary != expected_summary:
            raise ValueError("summary does not match metric records")
        for metric in self.metrics:
            unknown_modules = set(metric.modules) - (
                CURRENT_PLATFORM_MODULES | DEFERRED_PLATFORM_MODULES
            )
            if unknown_modules:
                raise ValueError(
                    f"unknown platform modules for metric {metric.platform_metric_id}: "
                    f"{sorted(unknown_modules)}"
                )
            expected_definition_sha256 = metric_definition_sha256(
                metric,
            )
            if metric.definition_sha256 != expected_definition_sha256:
                raise ValueError(
                    f"definition hash mismatch for platform_metric_id={metric.platform_metric_id}"
                )
            _validate_metric_review_state(metric)
        expected_snapshot_sha256 = source_snapshot_sha256(self.metrics)
        if self.source_snapshot_sha256 != expected_snapshot_sha256:
            raise ValueError("source snapshot hash does not match metric records")
        return self


class PlatformMetricBinding(StrictModel):
    platform_metric_id: int = Field(gt=0)
    module: NonBlankStr
    canonical_table: NonBlankStr
    canonical_field: NonBlankStr
    status: BindingStatus
    match_basis: BindingMatchBasis
    confidence: BindingConfidence
    grain: BindingGrain
    time_basis: TimeAnchor
    unit: MetricUnit
    value_encoding: BindingValueEncoding
    aggregation: BindingAggregation
    approved_definition_sha256: Sha256


class PromotionDecision(StrEnum):
    PROPOSED = "proposed"
    DEFERRED = "deferred"
    REJECTED = "rejected"


class PromotionReview(StrictModel):
    promotion_id: NonBlankStr
    platform_metric_id: int = Field(gt=0)
    module: NonBlankStr
    canonical_table: NonBlankStr | None = None
    canonical_field: NonBlankStr | None = None
    decision: PromotionDecision
    match_basis: BindingMatchBasis | None = None
    confidence: BindingConfidence | None = None
    definition_sha256: Sha256
    reason: NonBlankStr

    @model_validator(mode="after")
    def validate_target(self) -> PromotionReview:
        target_values = (self.canonical_table, self.canonical_field)
        if self.decision == PromotionDecision.PROPOSED and any(
            value is None for value in target_values
        ):
            raise ValueError("proposed promotion reviews require a canonical target")
        if self.decision != PromotionDecision.PROPOSED and any(
            value is not None for value in target_values
        ):
            raise ValueError("non-proposed promotion reviews must not declare a target")
        if self.decision == PromotionDecision.PROPOSED and (
            self.match_basis is None or self.confidence is None
        ):
            raise ValueError("proposed promotion reviews require match basis and confidence")
        return self


class SourceBindingRegistry(StrictModel):
    version: Literal[1]
    platform: Literal["xiaohongshu_qianfan"]
    runtime_consumed: bool = False
    runtime_mode: SourceBindingRuntimeMode = SourceBindingRuntimeMode.DISABLED
    runtime_scopes: list[SourceBindingRuntimeScope] = Field(default_factory=list)
    bindings: list[PlatformMetricBinding]

    @model_validator(mode="after")
    def validate_bindings(self) -> SourceBindingRegistry:
        if self.runtime_consumed:
            if self.runtime_mode != SourceBindingRuntimeMode.OBSERVE:
                raise ValueError("runtime-consumed source bindings require observe mode")
            if self.runtime_scopes != [SourceBindingRuntimeScope.AGENT_CONTEXT]:
                raise ValueError(
                    "runtime-consumed source bindings are limited to agent_context"
                )
        elif self.runtime_mode != SourceBindingRuntimeMode.DISABLED or self.runtime_scopes:
            raise ValueError(
                "runtime_consumed=false requires disabled mode and no scopes"
            )
        if any(binding.status != BindingStatus.ACCEPTED for binding in self.bindings):
            raise ValueError("formal source bindings may only contain accepted entries")
        keys = [
            (
                binding.platform_metric_id,
                binding.module,
                binding.canonical_table,
                binding.canonical_field,
            )
            for binding in self.bindings
        ]
        if len(keys) != len(set(keys)):
            raise ValueError("source bindings must be unique")
        return self


def reference_root() -> Path:
    return Path(__file__).resolve().parents[2] / "references"


def load_platform_metric_catalog(path: Path | None = None) -> PlatformMetricCatalog:
    resolved_path = path or reference_root() / "platform" / "xhs_metric_catalog.yaml"
    return PlatformMetricCatalog.model_validate(_load_yaml(resolved_path))


def load_source_binding_registry(path: Path | None = None) -> SourceBindingRegistry:
    resolved_path = path or reference_root() / "source_bindings" / "xhs_platform_metrics.yaml"
    return SourceBindingRegistry.model_validate(_load_yaml(resolved_path))


def build_platform_semantic_context(
    catalog_path: Path | None = None,
    registry_path: Path | None = None,
) -> dict[str, object]:
    """Build a read-only platform-definition snapshot for narrative agents."""
    try:
        catalog = load_platform_metric_catalog(catalog_path)
        registry = load_source_binding_registry(registry_path)
        validate_catalog_bundle(catalog, registry)
    except Exception as exc:
        return {
            "status": "unavailable",
            "runtime_scopes": [],
            "effects": _advisory_effects(),
            "catalog_reference": {
                "path": "references/platform/xhs_metric_catalog.yaml",
            },
            "accepted_references": [],
            "reference_only_candidates": [],
            "error": str(exc),
        }

    metrics_by_id = {metric.platform_metric_id: metric for metric in catalog.metrics}
    grouped: dict[tuple[object, ...], dict[str, object]] = {}
    for binding in sorted(
        registry.bindings,
        key=lambda item: (
            item.platform_metric_id,
            item.canonical_table,
            item.canonical_field,
            item.module,
        ),
    ):
        metric = metrics_by_id[binding.platform_metric_id]
        key = (
            binding.platform_metric_id,
            binding.canonical_table,
            binding.canonical_field,
        )
        reference = grouped.setdefault(
            key,
            {
                "platform_metric_id": metric.platform_metric_id,
                "display_name": metric.display_name,
                "description": metric.description,
                "modules": [],
                "canonical_table": binding.canonical_table,
                "canonical_field": binding.canonical_field,
                "status": str(binding.status),
                "confidence": str(binding.confidence),
                "unit": str(metric.unit),
                "caliber": str(metric.caliber),
                "time_anchor": str(metric.time_anchor),
                "refund_inclusion": str(metric.refund_inclusion),
                "cross_period_additive": str(metric.cross_period_additive),
                "grain": str(binding.grain),
                "aggregation": str(binding.aggregation),
            },
        )
        reference["modules"].append(binding.module)

    accepted_targets = {
        (
            binding.platform_metric_id,
            binding.canonical_table,
            binding.canonical_field,
        )
        for binding in registry.bindings
    }
    reference_only_candidates: list[dict[str, object]] = []
    from xhs_ceramics_analytics.importing.mapping import FIELD_ALIASES

    for metric in catalog.metrics:
        if metric.scope_status != CatalogScope.CURRENT:
            continue
        possible_targets = {
            (table, field)
            for module in metric.modules
            for table in PLATFORM_MODULE_TABLES.get(module, ())
            for field in FIELD_ALIASES.get(table, {})
            if target_matches_display_name(metric.display_name, table, field)
            and (metric.platform_metric_id, table, field) not in accepted_targets
        }
        if not possible_targets:
            continue
        reference_only_candidates.append(
            {
                "platform_metric_id": metric.platform_metric_id,
                "display_name": metric.display_name,
                "description": metric.description,
                "modules": list(metric.modules),
                "possible_targets": [
                    {"canonical_table": table, "canonical_field": field}
                    for table, field in sorted(possible_targets)
                ],
                "unit": str(metric.unit),
                "caliber": str(metric.caliber),
                "time_anchor": str(metric.time_anchor),
                "refund_inclusion": str(metric.refund_inclusion),
                "review_reasons": list(metric.review_reasons),
                "mapping_permission": "none",
            }
        )

    return {
        "status": str(registry.runtime_mode),
        "runtime_scopes": [str(scope) for scope in registry.runtime_scopes],
        "effects": _advisory_effects(),
        "catalog_reference": {
            "path": "references/platform/xhs_metric_catalog.yaml",
            "source_snapshot_sha256": catalog.source_snapshot_sha256,
            "metric_count": catalog.summary.metric_count,
            "current_metric_count": catalog.summary.current_count,
            "review_required_count": sum(metric.review_required for metric in catalog.metrics),
            "unaccepted_policy": "reference_only_never_map",
        },
        "accepted_references": list(grouped.values()),
        "reference_only_candidates": reference_only_candidates,
        "error": None,
    }


def _advisory_effects() -> dict[str, str]:
    return {
        "automatic_header_mapping": "validation_gate",
        "agent_decision_support": "enabled",
        "coverage": "none",
        "raw_values": "none",
        "calculations": "none",
    }


def load_promotion_reviews(path: Path | None = None) -> list[PromotionReview]:
    import csv

    resolved_path = path or reference_root() / "platform" / "xhs_metric_promotion_review.csv"
    try:
        with resolved_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except (OSError, csv.Error) as exc:
        raise ValueError(f"failed to load promotion review file {resolved_path}: {exc}") from exc
    if not rows:
        raise ValueError(f"promotion review file is empty: {resolved_path}")

    reviews = [PromotionReview.model_validate(_normalize_review_row(row)) for row in rows]
    promotion_ids = [review.promotion_id for review in reviews]
    if len(promotion_ids) != len(set(promotion_ids)):
        raise ValueError("promotion_id must be unique")
    return reviews


def validate_catalog_bundle(
    catalog: PlatformMetricCatalog,
    registry: SourceBindingRegistry,
    reviews: list[PromotionReview] | None = None,
) -> None:
    from xhs_ceramics_analytics.importing.mapping import FIELD_ALIASES

    metrics_by_id = {metric.platform_metric_id: metric for metric in catalog.metrics}
    accepted_contexts: set[tuple[int, str]] = set()

    for binding in registry.bindings:
        metric = metrics_by_id.get(binding.platform_metric_id)
        if metric is None:
            raise ValueError(
                f"binding references unknown platform_metric_id={binding.platform_metric_id}"
            )
        if binding.module not in metric.modules:
            raise ValueError(
                f"binding module {binding.module!r} is not declared for "
                f"platform_metric_id={binding.platform_metric_id}"
            )
        if binding.module not in CURRENT_PLATFORM_MODULES:
            raise ValueError("formal bindings may only target current-scope modules")
        table_aliases = FIELD_ALIASES.get(binding.canonical_table)
        if table_aliases is None or binding.canonical_field not in table_aliases:
            raise ValueError(
                f"binding target {binding.canonical_table}.{binding.canonical_field} does not exist"
            )
        if binding.canonical_table not in PLATFORM_MODULE_TABLES[binding.module]:
            raise ValueError(
                f"binding table {binding.canonical_table!r} is outside module "
                f"{binding.module!r} scope"
            )
        if binding.status == BindingStatus.ACCEPTED:
            context = (binding.platform_metric_id, binding.module)
            if context in accepted_contexts:
                raise ValueError(
                    "accepted bindings must have one target per platform metric and module"
                )
            accepted_contexts.add(context)
            if binding.approved_definition_sha256 != metric.definition_sha256:
                raise ValueError(
                    f"accepted binding is stale for platform_metric_id={binding.platform_metric_id}"
                )
            _validate_binding_semantics(metric, binding)
        if (
            binding.match_basis == BindingMatchBasis.EXACT_EXISTING_ALIAS
            and not target_matches_display_name(
                metric.display_name,
                binding.canonical_table,
                binding.canonical_field,
            )
        ):
            raise ValueError(
                f"exact alias binding does not match {metric.display_name!r} to "
                f"{binding.canonical_table}.{binding.canonical_field}"
            )

    for metric in catalog.metrics:
        current_contexts = {
            (metric.platform_metric_id, module)
            for module in metric.modules
            if module in CURRENT_PLATFORM_MODULES
        }
        accepted_for_metric = {
            context for context in accepted_contexts if context[0] == metric.platform_metric_id
        }
        is_fully_bound = bool(current_contexts) and current_contexts <= accepted_for_metric
        if metric.review_status == MetricReviewStatus.BOUND and not is_fully_bound:
            raise ValueError(
                f"bound metric {metric.platform_metric_id} does not cover every current module"
            )
        if metric.review_status != MetricReviewStatus.BOUND and is_fully_bound:
            raise ValueError(
                f"metric {metric.platform_metric_id} is fully bound but not marked bound"
            )

    if reviews is not None:
        for review in reviews:
            metric = metrics_by_id.get(review.platform_metric_id)
            if metric is None:
                raise ValueError(
                    f"promotion review references unknown platform_metric_id="
                    f"{review.platform_metric_id}"
                )
            if review.module not in metric.modules:
                raise ValueError(
                    f"promotion review module {review.module!r} is not declared for "
                    f"platform_metric_id={review.platform_metric_id}"
                )
            if review.definition_sha256 != metric.definition_sha256:
                raise ValueError(
                    f"promotion review is stale for platform_metric_id={review.platform_metric_id}"
                )
            if review.decision != PromotionDecision.PROPOSED:
                continue
            table_aliases = FIELD_ALIASES.get(review.canonical_table or "")
            if table_aliases is None or (review.canonical_field or "") not in table_aliases:
                raise ValueError(
                    f"promotion target {review.canonical_table}.{review.canonical_field} "
                    "does not exist"
                )
            if (review.canonical_table or "") not in PLATFORM_MODULE_TABLES[review.module]:
                raise ValueError(
                    f"promotion table {review.canonical_table!r} is outside module "
                    f"{review.module!r} scope"
                )
            if (
                review.match_basis == BindingMatchBasis.EXACT_EXISTING_ALIAS
                and not target_matches_display_name(
                    metric.display_name,
                    review.canonical_table or "",
                    review.canonical_field or "",
                )
            ):
                raise ValueError(
                    f"exact promotion review does not match {metric.display_name!r} to "
                    f"{review.canonical_table}.{review.canonical_field}"
                )


def _load_yaml(path: Path) -> object:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"failed to load catalog file {path}: {exc}") from exc
    if payload is None:
        raise ValueError(f"catalog file is empty: {path}")
    return payload


def _normalize_review_row(row: dict[str, str | None]) -> dict[str, object]:
    normalized: dict[str, object] = {}
    for key, value in row.items():
        if key is None:
            continue
        stripped = value.strip() if isinstance(value, str) else value
        normalized[key] = stripped or None
    return normalized


DEFERRED_PLATFORM_MODULES = {
    "店铺数据/群聊数据",
    "服务数据/客服数据",
    "服务数据/物流数据",
    "直播数据/直播总览",
    "服务数据/评价数据",
    "服务数据/售后数据",
    "交易数据/买手分析",
}
CURRENT_PLATFORM_MODULES = {
    "数据总览",
    "交易数据/成交分析",
    "商品数据",
    "流量数据",
    "笔记数据/商品笔记",
    "笔记数据/普通笔记",
    "笔记数据/带货笔记",
    "搜索数据",
    "交易数据/退款分析",
    "店铺数据/店铺主页",
}
PLATFORM_MODULE_TABLES = {
    "数据总览": frozenset({"business_overview_daily"}),
    "交易数据/成交分析": frozenset({"business_overview_daily"}),
    "商品数据": frozenset({"sku_performance"}),
    "流量数据": frozenset({"traffic_source"}),
    "笔记数据/商品笔记": frozenset({"notes"}),
    "笔记数据/普通笔记": frozenset({"notes"}),
    "笔记数据/带货笔记": frozenset({"notes"}),
    "搜索数据": frozenset({"search_overview", "search_terms"}),
    "交易数据/退款分析": frozenset({"refund_overview"}),
    "店铺数据/店铺主页": frozenset({"shop_page_funnel", "shop_page_source"}),
    **{module: frozenset() for module in DEFERRED_PLATFORM_MODULES},
}

CANONICAL_TABLE_GRAINS = {
    "business_overview_daily": BindingGrain.SHOP_DAY,
    "sku_performance": BindingGrain.SKU_WINDOW,
    "traffic_source": BindingGrain.ACCOUNT_CHANNEL_NOTE_TYPE_WINDOW,
    "notes": BindingGrain.NOTE_WINDOW,
    "search_overview": BindingGrain.SEARCH_CARRIER_DAY,
    "search_terms": BindingGrain.SEARCH_TERM_WINDOW,
    "refund_overview": BindingGrain.ACCOUNT_CARRIER_WINDOW,
    "shop_page_funnel": BindingGrain.SHOP_AUDIENCE_CYCLE_DAY,
    "shop_page_source": BindingGrain.SHOP_AUDIENCE_CYCLE_SOURCE_DAY,
}
VALUE_ENCODINGS_BY_UNIT = {
    MetricUnit.CNY: {BindingValueEncoding.DECIMAL},
    MetricUnit.PERCENT: {
        BindingValueEncoding.RATIO_0_1,
        BindingValueEncoding.PERCENT_0_100,
    },
    MetricUnit.COUNT: {BindingValueEncoding.INTEGER, BindingValueEncoding.DECIMAL},
    MetricUnit.SECONDS: {BindingValueEncoding.DURATION_SECONDS},
    MetricUnit.MINUTES: {BindingValueEncoding.DURATION_MINUTES},
}
AGGREGATIONS_BY_MEASURE_KIND = {
    MeasureKind.AMOUNT_TOTAL: {BindingAggregation.DIRECT, BindingAggregation.SUM},
    MeasureKind.NET_AMOUNT: {BindingAggregation.DIRECT, BindingAggregation.SUM},
    MeasureKind.EVENT_COUNT: {BindingAggregation.DIRECT, BindingAggregation.SUM},
    MeasureKind.COUNT: {BindingAggregation.DIRECT, BindingAggregation.SUM},
    MeasureKind.AVERAGE_AMOUNT: {
        BindingAggregation.DIRECT,
        BindingAggregation.AVERAGE,
    },
    MeasureKind.DURATION_AVERAGE: {
        BindingAggregation.DIRECT,
        BindingAggregation.AVERAGE,
    },
    MeasureKind.DISTINCT_COUNT: {
        BindingAggregation.DIRECT,
        BindingAggregation.DISTINCT_COUNT,
    },
    MeasureKind.RATIO: {
        BindingAggregation.DIRECT,
        BindingAggregation.RECOMPUTE_RATIO,
    },
    MeasureKind.SHARE: {
        BindingAggregation.DIRECT,
        BindingAggregation.RECOMPUTE_RATIO,
    },
}


METRIC_DEFINITION_FIELDS = (
    "platform_metric_id",
    "display_name",
    "description",
    "modules",
    "measure_kind",
    "unit",
    "caliber",
    "time_anchor",
    "cross_period_additive",
    "boundedness",
    "refund_inclusion",
    "division_formula_explicit",
    "classifier_version",
)


def metric_definition_sha256(definition: PlatformMetric | Mapping[str, object]) -> str:
    if isinstance(definition, PlatformMetric):
        payload = definition.model_dump(mode="json")
    else:
        payload = dict(definition)
    missing = set(METRIC_DEFINITION_FIELDS) - payload.keys()
    if missing:
        raise ValueError(f"metric definition is missing fields: {sorted(missing)}")
    return _sha256({field: payload[field] for field in METRIC_DEFINITION_FIELDS})


def source_snapshot_sha256(metrics: list[PlatformMetric]) -> str:
    return _sha256(
        [
            {
                "platform_metric_id": metric.platform_metric_id,
                "display_name": metric.display_name,
                "description": metric.description,
                "modules": metric.modules,
                "online": metric.online,
                "endpoint_path": metric.endpoint_path,
            }
            for metric in metrics
        ]
    )


def target_matches_display_name(
    display_name: str,
    canonical_table: str,
    canonical_field: str,
) -> bool:
    from xhs_ceramics_analytics.importing.mapping import (
        FIELD_ALIASES,
        _normalize_column_name,
    )

    aliases = FIELD_ALIASES.get(canonical_table, {}).get(canonical_field)
    if aliases is None:
        return False
    normalized_label = _normalize_column_name(display_name)
    normalized_aliases = {
        _normalize_column_name(canonical_field),
        *(_normalize_column_name(alias) for alias in aliases),
    }
    return normalized_label in normalized_aliases


def _validate_binding_semantics(
    metric: PlatformMetric,
    binding: PlatformMetricBinding,
) -> None:
    expected_grain = CANONICAL_TABLE_GRAINS.get(binding.canonical_table)
    if expected_grain is None or binding.grain != expected_grain:
        raise ValueError(
            f"binding grain {binding.grain!s} is incompatible with "
            f"canonical table {binding.canonical_table}"
        )
    if metric.time_anchor == TimeAnchor.UNKNOWN or binding.time_basis != metric.time_anchor:
        raise ValueError(
            f"binding time_basis {binding.time_basis!s} is incompatible with "
            f"platform metric time_anchor {metric.time_anchor!s}"
        )
    if metric.unit == MetricUnit.UNKNOWN or binding.unit != metric.unit:
        raise ValueError(
            f"binding unit {binding.unit!s} is incompatible with platform metric unit "
            f"{metric.unit!s}"
        )
    if binding.value_encoding not in VALUE_ENCODINGS_BY_UNIT.get(metric.unit, set()):
        raise ValueError(
            f"binding value_encoding {binding.value_encoding!s} is incompatible with "
            f"platform metric unit {metric.unit!s}"
        )
    if binding.aggregation not in AGGREGATIONS_BY_MEASURE_KIND[metric.measure_kind]:
        raise ValueError(
            f"binding aggregation {binding.aggregation!s} is incompatible with "
            f"platform metric measure_kind {metric.measure_kind!s}"
        )


def _validate_metric_review_state(metric: PlatformMetric) -> None:
    if metric.review_status == MetricReviewStatus.BOUND:
        expected = (CatalogScope.CURRENT, CandidateBindingStatus.APPROVED, False)
    elif metric.review_status == MetricReviewStatus.NEW_CONTRACT:
        if metric.candidate_binding_status in {
            CandidateBindingStatus.APPROVED,
            CandidateBindingStatus.DEFERRED,
            CandidateBindingStatus.REJECTED,
        }:
            raise ValueError("new_contract metric has an incompatible candidate binding status")
        expected = (CatalogScope.CURRENT, metric.candidate_binding_status, True)
    elif metric.review_status == MetricReviewStatus.DEFERRED:
        expected = (CatalogScope.DEFERRED, CandidateBindingStatus.DEFERRED, False)
    else:
        expected = (metric.scope_status, CandidateBindingStatus.REJECTED, False)

    actual = (metric.scope_status, metric.candidate_binding_status, metric.review_required)
    if actual != expected:
        raise ValueError(
            f"incoherent review state for platform_metric_id={metric.platform_metric_id}"
        )


def _sha256(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
