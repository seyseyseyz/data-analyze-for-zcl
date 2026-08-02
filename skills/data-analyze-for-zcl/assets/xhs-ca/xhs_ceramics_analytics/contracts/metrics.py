from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Mapping

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode
from yaml.resolver import BaseResolver


NonBlankStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
MetricId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$",
    ),
]


class MetricUnit(StrEnum):
    PERCENT = "percent"
    CNY = "cny"
    COUNT = "count"
    PERSON_DAY = "person_day"
    INDEX = "index"
    PP = "pp"
    TEXT = "text"


class MetricGrain(StrEnum):
    SHOP_DAY = "shop_day"
    SHOP_DAY_SUM = "shop_day_sum"
    SHOP_MONTH = "shop_month"
    SHOP_WINDOW = "shop_window"
    CARRIER = "carrier"
    SKU = "sku"
    NOTE = "note"
    SEARCH_TERM = "search_term"
    AUDIENCE = "audience"
    PRICE_BAND = "price_band"
    CATEGORY_L2 = "category_l2"


class WindowRole(StrEnum):
    ANALYSIS = "analysis"
    COMPARISON = "comparison"
    BASELINE = "baseline"
    TRAILING = "trailing"


class MetricCaliber(StrEnum):
    AMOUNT = "amount"
    ORDER_COUNT = "order_count"
    USER_COUNT = "user_count"
    IMPRESSION = "impression"
    COMPOSITE_PROXY = "composite_proxy"
    DIMENSIONLESS = "dimensionless"
    COUNT = "count"


class SourceGrain(StrEnum):
    SHOP_DAY = "shop_day"


class MetricAggregation(StrEnum):
    DIRECT = "direct"
    SUM_AS_PERSON_DAYS = "sum_as_person_days"
    MEAN_DAILY = "mean_daily"
    MEAN_OF_DAILY_RATIOS = "mean_of_daily_ratios"


class DistinctScope(StrEnum):
    DAY = "day"


class MetricRuntimeMode(StrEnum):
    DISABLED = "disabled"
    OBSERVE = "observe"


class MetricRuntimeScope(StrEnum):
    FACT_ANNOTATION = "fact_annotation"


# These outputs select a dimension member at runtime (for example, whichever carrier
# currently has the largest GMV share). Binding the unscoped legacy key to one fixed
# registry metric silently changes its meaning as the winning member changes. Fact
# scoping does not make that dimension explicit, so scoped variants are also rejected.
# Until a producer emits the selected dimension explicitly, such keys must remain
# unmapped.
DYNAMIC_DIMENSION_LEGACY_KEYS = frozenset(
    {
        "channel_structure_diagnosis.dominant_gmv_share",
        "refund_structure_diagnosis.dominant_share",
        "audience_structure_diagnosis.top_gmv_share",
        "note_commercial_diagnosis.baseline_refund_rate",
    }
)
_DYNAMIC_DIMENSION_SIGNATURES = frozenset(
    (legacy_key.partition(".")[0], legacy_key.rpartition(".")[2])
    for legacy_key in DYNAMIC_DIMENSION_LEGACY_KEYS
)


def _is_dynamic_dimension_legacy_key(legacy_key: str) -> bool:
    return (
        legacy_key.partition(".")[0],
        legacy_key.rpartition(".")[2],
    ) in _DYNAMIC_DIMENSION_SIGNATURES


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _UniqueKeySafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[object, object]:
    loader.flatten_mapping(node)
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate YAML key: {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeySafeLoader.add_constructor(
    BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class RegistryEnums(StrictModel):
    unit: list[MetricUnit] = Field(min_length=1)
    grain: list[MetricGrain] = Field(min_length=1)
    window_role: list[WindowRole] = Field(min_length=1)
    caliber: list[MetricCaliber] = Field(min_length=1)
    source_grain: list[SourceGrain] = Field(min_length=1)
    aggregation: list[MetricAggregation] = Field(min_length=1)
    distinct_scope: list[DistinctScope] = Field(min_length=1)

    @field_validator("unit", "grain", "window_role", "caliber", "source_grain", "aggregation", "distinct_scope")
    @classmethod
    def validate_unique_values(cls, values: list[StrEnum]) -> list[StrEnum]:
        if len(values) != len(set(values)):
            raise ValueError("registry enum values must be unique")
        return values


class MetricSpec(StrictModel):
    metric_id: MetricId
    display_name: NonBlankStr
    forbidden_aliases: list[NonBlankStr] = Field(default_factory=list)
    unit: MetricUnit
    formula: NonBlankStr
    source_grain: SourceGrain | None = None
    grain: MetricGrain
    aggregation: MetricAggregation | None = None
    distinct_scope: DistinctScope | None = None
    period_unique: bool | None = None
    window_role: WindowRole
    numerator: NonBlankStr | None = None
    denominator: NonBlankStr | None = None
    caliber: MetricCaliber
    additive: bool
    proxy: bool
    proxy_label: NonBlankStr | None = None
    non_additive_group: NonBlankStr | None = None
    owners_modules: list[NonBlankStr] = Field(min_length=1)
    legacy_keys: list[NonBlankStr] = Field(default_factory=list)
    notes: NonBlankStr | None = None

    @field_validator("forbidden_aliases", "owners_modules", "legacy_keys")
    @classmethod
    def validate_unique_lists(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("metric list values must be unique")
        return values

    @model_validator(mode="after")
    def validate_semantics(self) -> MetricSpec:
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("numerator and denominator must be declared together")
        if self.proxy and self.proxy_label is None:
            raise ValueError("proxy metrics require proxy_label")
        if not self.proxy and self.proxy_label is not None:
            raise ValueError("non-proxy metrics cannot declare proxy_label")
        if self.display_name in self.forbidden_aliases:
            raise ValueError("display_name cannot also be a forbidden_alias")

        if (self.source_grain is None) != (self.aggregation is None):
            raise ValueError("source_grain and aggregation must be declared together")
        if (self.distinct_scope is None) != (self.period_unique is None):
            raise ValueError("distinct_scope and period_unique must be declared together")
        if self.distinct_scope is not None and self.source_grain is None:
            raise ValueError("daily-distinct metrics require source_grain and aggregation")

        if self.aggregation == MetricAggregation.SUM_AS_PERSON_DAYS and (
            self.distinct_scope != DistinctScope.DAY or self.period_unique is not False
        ):
            raise ValueError(
                "sum_as_person_days metrics require distinct_scope=day "
                "and period_unique=false"
            )

        if self.distinct_scope == DistinctScope.DAY:
            if self.source_grain != SourceGrain.SHOP_DAY:
                raise ValueError("day-distinct metrics require source_grain=shop_day")
            if self.period_unique is not False:
                raise ValueError("day-distinct metrics cannot claim period-unique users")
            if self.additive:
                raise ValueError("day-distinct metrics cannot be generally additive")

        if self.aggregation == MetricAggregation.DIRECT and self.distinct_scope is not None:
            if self.grain != MetricGrain.SHOP_DAY:
                raise ValueError("direct day-distinct metrics must stay at shop_day grain")
        elif self.aggregation == MetricAggregation.SUM_AS_PERSON_DAYS:
            if self.unit != MetricUnit.PERSON_DAY:
                raise ValueError("sum_as_person_days metrics require unit=person_day")
            if self.grain != MetricGrain.SHOP_WINDOW:
                raise ValueError("sum_as_person_days metrics require shop_window grain")
            if self.caliber != MetricCaliber.USER_COUNT:
                raise ValueError("sum_as_person_days metrics require user_count caliber")
            if "人次" not in self.display_name:
                raise ValueError("person-day metrics must be labeled as 人次")
        elif self.aggregation == MetricAggregation.MEAN_DAILY:
            if self.grain != MetricGrain.SHOP_WINDOW:
                raise ValueError("mean_daily metrics require shop_window grain")
            if self.additive:
                raise ValueError("mean_daily metrics cannot be additive")
            if "日均" not in self.display_name:
                raise ValueError("mean_daily metrics must be labeled as 日均")
        elif self.aggregation == MetricAggregation.MEAN_OF_DAILY_RATIOS:
            if self.grain != MetricGrain.SHOP_WINDOW:
                raise ValueError("mean_of_daily_ratios metrics require shop_window grain")
            if self.additive:
                raise ValueError("mean_of_daily_ratios metrics cannot be additive")
            if self.numerator is None or self.denominator is None:
                raise ValueError("mean_of_daily_ratios metrics require numerator and denominator")
            if "日均" not in self.display_name:
                raise ValueError("mean_of_daily_ratios metrics must be labeled as 日均")
        return self


class CompositionGroup(StrictModel):
    description: NonBlankStr
    must_sum_to: float
    tolerance: float = Field(ge=0)
    forbidden_mix_with_calibers: list[MetricCaliber] = Field(default_factory=list)


class MetricRegistry(StrictModel):
    version: Literal[1]
    runtime_consumed: bool
    runtime_mode: MetricRuntimeMode
    runtime_scopes: list[MetricRuntimeScope]
    updated: date
    legacy_contracts: dict[NonBlankStr, NonBlankStr]
    enums: RegistryEnums
    metrics: list[MetricSpec] = Field(min_length=1)
    composition_groups: dict[str, CompositionGroup]
    display_policy: dict[str, object]

    @model_validator(mode="after")
    def validate_registry(self) -> MetricRegistry:
        if self.runtime_consumed:
            if self.runtime_mode != MetricRuntimeMode.OBSERVE:
                raise ValueError("runtime consumption currently requires runtime_mode=observe")
            if self.runtime_scopes != [MetricRuntimeScope.FACT_ANNOTATION]:
                raise ValueError(
                    "runtime consumption currently supports only fact_annotation"
                )
        elif (
            self.runtime_mode != MetricRuntimeMode.DISABLED
            or self.runtime_scopes
        ):
            raise ValueError(
                "runtime_consumed=false requires runtime_mode=disabled and no scopes"
            )

        enum_types = {
            "unit": MetricUnit,
            "grain": MetricGrain,
            "window_role": WindowRole,
            "caliber": MetricCaliber,
            "source_grain": SourceGrain,
            "aggregation": MetricAggregation,
            "distinct_scope": DistinctScope,
        }
        for field_name, enum_type in enum_types.items():
            declared_values = set(getattr(self.enums, field_name))
            expected_values = set(enum_type)
            if declared_values != expected_values:
                raise ValueError(
                    f"enums.{field_name} must exactly match the Python enum"
                )

        metric_ids = [metric.metric_id for metric in self.metrics]
        display_names = [metric.display_name for metric in self.metrics]
        legacy_keys = [key for metric in self.metrics for key in metric.legacy_keys]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("metric_id must be unique")
        if len(display_names) != len(set(display_names)):
            raise ValueError("display_name must be unique")
        if len(legacy_keys) != len(set(legacy_keys)):
            raise ValueError("legacy_keys must map to exactly one metric_id")
        dynamic_legacy_keys = {
            legacy_key
            for legacy_key in legacy_keys
            if _is_dynamic_dimension_legacy_key(legacy_key)
        }
        if dynamic_legacy_keys:
            raise ValueError(
                "dynamic-dimension legacy keys require an explicit dimension binding: "
                f"{sorted(dynamic_legacy_keys)}"
            )
        if set(self.legacy_contracts) != set(legacy_keys):
            missing = sorted(set(legacy_keys) - set(self.legacy_contracts))
            extra = sorted(set(self.legacy_contracts) - set(legacy_keys))
            raise ValueError(
                "legacy contracts must exactly cover legacy_keys: "
                f"missing={missing}, extra={extra}"
            )
        for metric in self.metrics:
            expected_contract = "|".join(
                (
                    str(metric.unit),
                    str(metric.caliber),
                    str(metric.grain),
                    str(metric.aggregation) if metric.aggregation is not None else "none",
                )
            )
            for legacy_key in metric.legacy_keys:
                actual_contract = self.legacy_contracts[legacy_key]
                if actual_contract != expected_contract:
                    raise ValueError(
                        f"legacy contract mismatch for {legacy_key}: "
                        f"producer={actual_contract}, registry={expected_contract}"
                    )
        forbidden_aliases = {
            alias for metric in self.metrics for alias in metric.forbidden_aliases
        }
        conflicting_names = forbidden_aliases & set(display_names)
        if conflicting_names:
            raise ValueError(
                f"forbidden aliases collide with display names: {sorted(conflicting_names)}"
            )

        for metric in self.metrics:
            if metric.non_additive_group is not None and (
                metric.non_additive_group not in self.composition_groups
            ):
                raise ValueError(
                    f"unknown non_additive_group for {metric.metric_id}: "
                    f"{metric.non_additive_group}"
                )
            if metric.unit not in self.enums.unit:
                raise ValueError(f"unit is not declared in enums: {metric.unit}")
            if metric.grain not in self.enums.grain:
                raise ValueError(f"grain is not declared in enums: {metric.grain}")
            if metric.window_role not in self.enums.window_role:
                raise ValueError(f"window_role is not declared in enums: {metric.window_role}")
            if metric.caliber not in self.enums.caliber:
                raise ValueError(f"caliber is not declared in enums: {metric.caliber}")
            if metric.source_grain is not None and metric.source_grain not in self.enums.source_grain:
                raise ValueError(f"source_grain is not declared in enums: {metric.source_grain}")
            if metric.aggregation is not None and metric.aggregation not in self.enums.aggregation:
                raise ValueError(f"aggregation is not declared in enums: {metric.aggregation}")
            if metric.distinct_scope is not None and metric.distinct_scope not in self.enums.distinct_scope:
                raise ValueError(f"distinct_scope is not declared in enums: {metric.distinct_scope}")
        return self


@dataclass(frozen=True)
class MetricRuntimeIndex:
    by_metric_id: Mapping[str, MetricSpec]
    by_legacy_fact_id: Mapping[str, MetricSpec]
    registry_hash: str

    def resolve(self, fact_id: str) -> MetricSpec | None:
        return self.by_legacy_fact_id.get(fact_id)

    def resolve_validated(
        self,
        fact_id: str,
        *,
        metric_key: str,
        producer_unit: str,
    ) -> tuple[MetricSpec | None, str | None]:
        """Resolve an exact legacy id and verify it agrees with producer semantics.

        The registry may enrich a fact only after the producer-owned unit and the
        registry-owned module/caliber metadata agree. A failed check is deliberately
        returned as an unmapped fact plus a reason; callers keep the producer value and
        rendering instead of letting a stale catalog relabel the number.
        """
        metric = self.resolve(fact_id)
        if metric is None:
            return None, None

        task_id = fact_id.partition(".")[0]
        if task_id not in metric.owners_modules:
            return None, (
                f"owner mismatch: {task_id!r} is not declared for {metric.metric_id}"
            )

        registry_unit = str(metric.unit)
        compatible_units = producer_unit == registry_unit or {
            producer_unit,
            registry_unit,
        } == {MetricUnit.PERCENT.value, MetricUnit.PP.value}
        if not compatible_units:
            return None, (
                f"unit mismatch: producer={producer_unit}, registry={registry_unit}"
            )

        caliber_hint = _producer_caliber_hint(metric_key, producer_unit)
        if caliber_hint is not None and metric.caliber != caliber_hint:
            return None, (
                f"caliber mismatch: producer={caliber_hint}, registry={metric.caliber}"
            )
        return metric, None


def _producer_caliber_hint(
    metric_key: str,
    producer_unit: str,
) -> MetricCaliber | None:
    """Return only high-confidence caliber hints encoded in producer output keys."""
    key = metric_key.lower()
    if producer_unit == MetricUnit.PERSON_DAY.value:
        return MetricCaliber.USER_COUNT
    if key.endswith(("_observed_days", "_count")):
        return MetricCaliber.COUNT
    if key.endswith(("_hhi", "_gini")):
        return MetricCaliber.DIMENSIONLESS
    if "impression" in key and producer_unit == MetricUnit.COUNT.value:
        return MetricCaliber.IMPRESSION
    if "order" in key and producer_unit == MetricUnit.COUNT.value:
        return MetricCaliber.ORDER_COUNT
    if any(token in key for token in ("buyer", "visitor", "_users", "wishlist")) and (
        producer_unit in {MetricUnit.COUNT.value, MetricUnit.PERSON_DAY.value}
    ):
        return MetricCaliber.USER_COUNT
    if producer_unit == MetricUnit.CNY.value:
        return MetricCaliber.AMOUNT
    return None


def build_metric_runtime_index(registry: MetricRegistry) -> MetricRuntimeIndex:
    payload = registry.model_dump(mode="json")
    registry_hash = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return MetricRuntimeIndex(
        by_metric_id=MappingProxyType(
            {metric.metric_id: metric for metric in registry.metrics}
        ),
        by_legacy_fact_id=MappingProxyType(
            {
                legacy_key: metric
                for metric in registry.metrics
                for legacy_key in metric.legacy_keys
            }
        ),
        registry_hash=registry_hash,
    )


def reference_root() -> Path:
    return Path(__file__).resolve().parents[2] / "references"


def load_metric_registry(path: Path | None = None) -> MetricRegistry:
    resolved_path = path or reference_root() / "metrics" / "registry.yaml"
    return MetricRegistry.model_validate(_load_yaml(resolved_path))


def _load_yaml(path: Path) -> object:
    try:
        payload = yaml.load(
            path.read_text(encoding="utf-8"),
            Loader=_UniqueKeySafeLoader,
        )
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"failed to load metric registry {path}: {exc}") from exc
    if payload is None:
        raise ValueError(f"metric registry is empty: {path}")
    return payload
