from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from xhs_ceramics_analytics.contracts.platform_catalog import (  # noqa: E402
    Additivity,
    BindingConfidence,
    BindingMatchBasis,
    BindingStatus,
    Boundedness,
    BusinessDomain,
    CandidateBindingStatus,
    CatalogScope,
    CatalogSummary,
    ClassificationConfidence,
    CURRENT_PLATFORM_MODULES,
    DEFERRED_PLATFORM_MODULES,
    MeasureKind,
    MetricCaliber,
    MetricReviewStatus,
    MetricUnit,
    PLATFORM_MODULE_TABLES,
    PlatformMetric,
    PlatformMetricBinding,
    PlatformMetricCatalog,
    PromotionDecision,
    PromotionReview,
    RefundInclusion,
    TimeAnchor,
    load_source_binding_registry,
    metric_definition_sha256,
    source_snapshot_sha256,
    target_matches_display_name,
    validate_catalog_bundle,
)
from xhs_ceramics_analytics.importing.mapping import FIELD_ALIASES  # noqa: E402


CLASSIFIER_VERSION = "xhs-semantic-v3"
PLATFORM = "xiaohongshu_qianfan"
TRACKED_CATALOG_PATH = REPO_ROOT / "references" / "platform" / "xhs_metric_catalog.yaml"
MINIMUM_BASELINE_METRIC_COUNT = 134
ALLOWED_ENDPOINT_PREFIXES = {
    "ark.xiaohongshu.com": ("/api/",),
    "fe-static.xhscdn.com": ("/formula-static/",),
}


@dataclass(frozen=True)
class ModulePolicy:
    domain: BusinessDomain
    tables: tuple[str, ...] = ()
    current_scope: bool = True


@dataclass(frozen=True)
class ClassifiedMetricDefinition:
    platform_metric_id: int
    display_name: str
    description: str
    modules: tuple[str, ...]
    measure_kind: MeasureKind
    unit: MetricUnit
    caliber: MetricCaliber
    time_anchor: TimeAnchor
    cross_period_additive: Additivity
    boundedness: Boundedness
    refund_inclusion: RefundInclusion
    division_formula_explicit: bool
    classifier_version: str = CLASSIFIER_VERSION

    def hash_payload(self) -> dict[str, object]:
        return {
            "platform_metric_id": self.platform_metric_id,
            "display_name": self.display_name,
            "description": self.description,
            "modules": list(self.modules),
            "measure_kind": self.measure_kind,
            "unit": self.unit,
            "caliber": self.caliber,
            "time_anchor": self.time_anchor,
            "cross_period_additive": self.cross_period_additive,
            "boundedness": self.boundedness,
            "refund_inclusion": self.refund_inclusion,
            "division_formula_explicit": self.division_formula_explicit,
            "classifier_version": self.classifier_version,
        }


MODULE_POLICIES = {
    "数据总览": ModulePolicy(BusinessDomain.OVERVIEW, ("business_overview_daily",)),
    "交易数据/成交分析": ModulePolicy(BusinessDomain.TRANSACTION, ("business_overview_daily",)),
    "商品数据": ModulePolicy(BusinessDomain.PRODUCT, ("sku_performance",)),
    "流量数据": ModulePolicy(BusinessDomain.TRAFFIC, ("traffic_source",)),
    "笔记数据/商品笔记": ModulePolicy(BusinessDomain.NOTES, ("notes",)),
    "笔记数据/普通笔记": ModulePolicy(BusinessDomain.NOTES, ("notes",)),
    "笔记数据/带货笔记": ModulePolicy(BusinessDomain.NOTES, ("notes",)),
    "搜索数据": ModulePolicy(BusinessDomain.SEARCH, ("search_overview", "search_terms")),
    "交易数据/退款分析": ModulePolicy(BusinessDomain.REFUND, ("refund_overview",)),
    "店铺数据/店铺主页": ModulePolicy(
        BusinessDomain.SHOP_PAGE, ("shop_page_funnel", "shop_page_source")
    ),
    "店铺数据/群聊数据": ModulePolicy(BusinessDomain.GROUP_CHAT, current_scope=False),
    "服务数据/客服数据": ModulePolicy(BusinessDomain.CUSTOMER_SERVICE, current_scope=False),
    "服务数据/物流数据": ModulePolicy(BusinessDomain.LOGISTICS, current_scope=False),
    "直播数据/直播总览": ModulePolicy(BusinessDomain.LIVE, current_scope=False),
    "服务数据/评价数据": ModulePolicy(BusinessDomain.REVIEWS, current_scope=False),
    "服务数据/售后数据": ModulePolicy(BusinessDomain.AFTER_SALES, current_scope=False),
    "交易数据/买手分析": ModulePolicy(BusinessDomain.BUYER, current_scope=False),
}
UNKNOWN_MODULE_POLICY = ModulePolicy(BusinessDomain.UNKNOWN, current_scope=False)
if set(MODULE_POLICIES) != CURRENT_PLATFORM_MODULES | DEFERRED_PLATFORM_MODULES:
    raise RuntimeError("module policy registry is out of sync with catalog contract")
if {
    module for module, policy in MODULE_POLICIES.items() if policy.current_scope
} != CURRENT_PLATFORM_MODULES:
    raise RuntimeError("module policy scope flags are out of sync with catalog contract")
if {
    module: frozenset(policy.tables) for module, policy in MODULE_POLICIES.items()
} != PLATFORM_MODULE_TABLES:
    raise RuntimeError("module policy table scopes are out of sync with catalog contract")
TELEMETRY_HOSTS = {"apm-fe.xiaohongshu.com", "spider-tracker.xiaohongshu.com"}
GENERIC_SCHEMA_FIELDS = {
    "code",
    "data",
    "list",
    "msg",
    "proportion",
    "ratio",
    "result",
    "success",
    "value",
}
CANDIDATE_HEADERS = (
    "candidate_id",
    "source_kind",
    "external_key",
    "label",
    "description",
    "modules",
    "source_confidence",
    "association_confidence",
    "proposed_target_kind",
    "proposed_target_id",
    "review_status",
    "review_reason",
    "endpoint_path",
    "sensitivity",
    "report_visibility",
    "evidence_sha256",
)
PROMOTION_HEADERS = (
    "promotion_id",
    "platform_metric_id",
    "module",
    "canonical_table",
    "canonical_field",
    "decision",
    "match_basis",
    "confidence",
    "definition_sha256",
    "reason",
)
SCHEMA_HEADERS = (
    "endpoint_path",
    "field",
    "json_path",
    "observed_types",
    "response_occurrences",
    "schema_role",
    "evidence_sha256",
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a scrubbed, review-gated Xiaohongshu semantic catalog."
    )
    parser.add_argument(
        "--api-metrics",
        type=Path,
        default=REPO_ROOT / "output" / "xiaohongshu-api-metric-dictionary.csv",
    )
    parser.add_argument(
        "--field-candidates",
        type=Path,
        default=REPO_ROOT / "output" / "xiaohongshu-field-dictionary-core.csv",
    )
    parser.add_argument(
        "--api-schema",
        type=Path,
        default=REPO_ROOT / "output" / "xiaohongshu-api-schema.csv",
    )
    parser.add_argument(
        "--source-bindings",
        type=Path,
        default=REPO_ROOT / "references" / "source_bindings" / "xhs_platform_metrics.yaml",
    )
    parser.add_argument(
        "--catalog-output",
        type=Path,
        default=REPO_ROOT / "references" / "platform" / "xhs_metric_catalog.yaml",
    )
    parser.add_argument(
        "--promotion-output",
        type=Path,
        default=REPO_ROOT / "references" / "platform" / "xhs_metric_promotion_review.csv",
    )
    parser.add_argument(
        "--local-output-dir",
        type=Path,
        default=REPO_ROOT / ".xhs-ceramics-analytics" / "catalog",
    )
    parser.add_argument(
        "--allow-metric-removals",
        action="store_true",
        help="Allow an intentional catalog rebuild that omits IDs in the tracked baseline.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_rows = read_csv(
        args.api_metrics,
        {"field", "explanation", "metric_id", "modules", "online", "source_url"},
    )
    metric_rows = [row for row in api_rows if (row.get("metric_id") or "").isdigit()]
    api_field_rows = [row for row in api_rows if not (row.get("metric_id") or "").isdigit()]
    if not metric_rows:
        raise ValueError("API metric input contains no stable numeric metric IDs")
    validate_metric_baseline(metric_rows, allow_removals=args.allow_metric_removals)
    field_candidate_rows = read_csv(
        args.field_candidates,
        {"field", "explanation", "confidence", "source_asset", "source_key", "source_url"},
    )
    schema_rows = read_csv(
        args.api_schema,
        {"endpoint", "field", "json_path", "observed_types", "response_occurrences"},
    )
    registry = load_source_binding_registry(args.source_bindings)

    proposals = build_promotion_reviews(metric_rows)
    catalog = build_catalog(metric_rows, proposals, registry.bindings)
    validate_catalog_bundle(catalog, registry, proposals)
    candidate_rows = build_candidate_ledger(
        catalog,
        api_field_rows,
        field_candidate_rows,
        proposals,
    )
    scrubbed_schema = build_schema_snapshot(schema_rows)
    metadata = {
        "classifier_version": CLASSIFIER_VERSION,
        "platform_metric_count": len(catalog.metrics),
        "promotion_review_count": len(proposals),
        "candidate_count": len(candidate_rows),
        "schema_path_count": len(scrubbed_schema),
        "source_snapshot_sha256": catalog.source_snapshot_sha256,
        "runtime_consumed": False,
    }

    write_yaml(args.catalog_output, catalog.model_dump(mode="json"))
    write_csv(
        args.promotion_output,
        PROMOTION_HEADERS,
        [review.model_dump(mode="json") for review in proposals],
    )
    write_csv(
        args.local_output_dir / "field_review_ledger.csv",
        CANDIDATE_HEADERS,
        candidate_rows,
    )
    write_csv(
        args.local_output_dir / "api_schema_snapshot.csv",
        SCHEMA_HEADERS,
        scrubbed_schema,
    )
    write_json(args.local_output_dir / "metadata.json", metadata)
    print(
        "catalog built: "
        f"{len(catalog.metrics)} platform metrics, "
        f"{len(proposals)} promotion reviews, "
        f"{len(candidate_rows)} local candidates, "
        f"{len(scrubbed_schema)} scrubbed schema paths"
    )
    return 0


def read_csv(path: Path, required_headers: set[str]) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ValueError(f"CSV has no header: {path}")
            missing_headers = required_headers - set(reader.fieldnames)
            if missing_headers:
                raise ValueError(
                    f"CSV {path} is missing required headers: {sorted(missing_headers)}"
                )
            return [dict(row) for row in reader]
    except (OSError, csv.Error) as exc:
        raise ValueError(f"failed to read CSV {path}: {exc}") from exc


def validate_metric_baseline(
    metric_rows: list[dict[str, str]],
    *,
    allow_removals: bool,
) -> None:
    incoming_ids = {int(row["metric_id"]) for row in metric_rows}
    if allow_removals:
        return
    if len(incoming_ids) < MINIMUM_BASELINE_METRIC_COUNT:
        raise ValueError(
            "API metric input is incomplete: "
            f"found {len(incoming_ids)} stable IDs, expected at least "
            f"{MINIMUM_BASELINE_METRIC_COUNT}; use --allow-metric-removals only for "
            "an intentional reviewed removal"
        )
    if not TRACKED_CATALOG_PATH.exists():
        return
    try:
        baseline_payload = yaml.safe_load(TRACKED_CATALOG_PATH.read_text(encoding="utf-8"))
        baseline_ids = {int(metric["platform_metric_id"]) for metric in baseline_payload["metrics"]}
    except (OSError, TypeError, KeyError, ValueError, yaml.YAMLError) as exc:
        raise ValueError(f"failed to read tracked metric baseline: {exc}") from exc
    missing_ids = sorted(baseline_ids - incoming_ids)
    if missing_ids:
        raise ValueError(
            "API metric input omits tracked stable IDs: "
            f"{missing_ids}; use --allow-metric-removals only for an intentional reviewed removal"
        )


def build_catalog(
    metric_rows: list[dict[str, str]],
    proposals: list[PromotionReview],
    bindings: list[PlatformMetricBinding],
) -> PlatformMetricCatalog:
    parsed_rows = parse_unique_metric_rows(metric_rows)
    display_name_counts = Counter(row["field"] for row in parsed_rows)
    proposal_ids = {
        review.platform_metric_id
        for review in proposals
        if review.decision == PromotionDecision.PROPOSED
    }
    accepted_contexts = {
        (binding.platform_metric_id, binding.module)
        for binding in bindings
        if binding.status == BindingStatus.ACCEPTED
    }

    metrics: list[PlatformMetric] = []
    for row in parsed_rows:
        definition = classify_metric_definition(row)
        platform_metric_id = definition.platform_metric_id
        display_name = definition.display_name
        description = definition.description
        modules = list(definition.modules)
        scope_status = classify_scope(modules)
        review_reasons = classify_review_reasons(
            platform_metric_id,
            display_name,
            description,
            display_name_counts,
            definition.unit,
            proposal_ids,
        )
        current_contexts = {
            (platform_metric_id, module)
            for module in modules
            if module_policy(module).current_scope
        }
        if current_contexts and current_contexts <= accepted_contexts:
            review_status = MetricReviewStatus.BOUND
            candidate_binding_status = CandidateBindingStatus.APPROVED
        elif scope_status == CatalogScope.DEFERRED:
            review_status = MetricReviewStatus.DEFERRED
            candidate_binding_status = CandidateBindingStatus.DEFERRED
        else:
            review_status = MetricReviewStatus.NEW_CONTRACT
            if "duplicate_display_name" in review_reasons:
                candidate_binding_status = CandidateBindingStatus.REVIEW_REQUIRED
            elif platform_metric_id in proposal_ids:
                candidate_binding_status = CandidateBindingStatus.PROPOSED_EXACT
            else:
                candidate_binding_status = CandidateBindingStatus.CLASSIFIED_UNMAPPED
        if review_status == MetricReviewStatus.NEW_CONTRACT:
            review_reasons.append("no_approved_binding")

        metrics.append(
            PlatformMetric(
                platform_metric_id=platform_metric_id,
                display_name=display_name,
                description=description,
                modules=modules,
                online=parse_optional_bool(row.get("online", "")),
                scope_status=scope_status,
                review_status=review_status,
                business_domains=classify_business_domains(modules),
                measure_kind=definition.measure_kind,
                unit=definition.unit,
                caliber=definition.caliber,
                time_anchor=definition.time_anchor,
                cross_period_additive=definition.cross_period_additive,
                boundedness=definition.boundedness,
                refund_inclusion=definition.refund_inclusion,
                division_formula_explicit=definition.division_formula_explicit,
                classification_confidence=classify_confidence(
                    definition.measure_kind,
                    definition.unit,
                ),
                candidate_binding_status=candidate_binding_status,
                review_required=review_status == MetricReviewStatus.NEW_CONTRACT,
                review_reasons=review_reasons,
                classifier_version=definition.classifier_version,
                endpoint_path=endpoint_path(row.get("source_url", "")),
                definition_sha256=metric_definition_sha256(definition.hash_payload()),
            )
        )

    metrics.sort(key=lambda metric: metric.platform_metric_id)
    summary = CatalogSummary(
        metric_count=len(metrics),
        current_count=sum(metric.scope_status == CatalogScope.CURRENT for metric in metrics),
        deferred_count=sum(metric.scope_status == CatalogScope.DEFERRED for metric in metrics),
        bound_count=sum(metric.review_status == MetricReviewStatus.BOUND for metric in metrics),
        new_contract_count=sum(
            metric.review_status == MetricReviewStatus.NEW_CONTRACT for metric in metrics
        ),
        rejected_count=sum(
            metric.review_status == MetricReviewStatus.REJECTED for metric in metrics
        ),
    )
    return PlatformMetricCatalog(
        version=1,
        platform=PLATFORM,
        source_snapshot_sha256=source_snapshot_sha256(metrics),
        summary=summary,
        metrics=metrics,
    )


def parse_unique_metric_rows(metric_rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not metric_rows:
        raise ValueError("platform metric input must not be empty")
    rows_by_id: dict[int, dict[str, str]] = {}
    for row in metric_rows:
        metric_id = int(row["metric_id"])
        normalized = {
            "metric_id": str(metric_id),
            "field": (row.get("field") or "").strip(),
            "explanation": (row.get("explanation") or "").strip(),
            "modules": (row.get("modules") or "").strip(),
            "online": (row.get("online") or "").strip(),
            "source_url": (row.get("source_url") or "").strip(),
        }
        if not normalized["field"] or not normalized["explanation"]:
            raise ValueError(f"metric {metric_id} is missing display name or description")
        previous = rows_by_id.get(metric_id)
        if previous is not None and previous != normalized:
            raise ValueError(f"platform metric {metric_id} has conflicting definitions")
        rows_by_id[metric_id] = normalized
    return [rows_by_id[metric_id] for metric_id in sorted(rows_by_id)]


def classify_metric_definition(row: dict[str, str]) -> ClassifiedMetricDefinition:
    platform_metric_id = int(row["metric_id"])
    display_name = row["field"].strip()
    description = row["explanation"].strip()
    modules = tuple(split_modules(row.get("modules", "")))
    measure_kind = classify_measure_kind(display_name, description)
    unit = classify_unit(measure_kind, description)
    return ClassifiedMetricDefinition(
        platform_metric_id=platform_metric_id,
        display_name=display_name,
        description=description,
        modules=modules,
        measure_kind=measure_kind,
        unit=unit,
        caliber=classify_caliber(display_name, measure_kind),
        time_anchor=classify_time_anchor(display_name, description),
        cross_period_additive=classify_additivity(measure_kind),
        boundedness=classify_boundedness(description),
        refund_inclusion=classify_refund_inclusion(display_name, description),
        division_formula_explicit=has_explicit_division_formula(description),
    )


def build_promotion_reviews(metric_rows: list[dict[str, str]]) -> list[PromotionReview]:
    reviews: list[PromotionReview] = []
    for row in parse_unique_metric_rows(metric_rows):
        definition = classify_metric_definition(row)
        platform_metric_id = definition.platform_metric_id
        display_name = definition.display_name
        definition_sha256 = metric_definition_sha256(definition.hash_payload())
        modules = list(definition.modules)
        if classify_scope(modules) == CatalogScope.DEFERRED:
            for module in modules:
                reviews.append(
                    PromotionReview(
                        promotion_id=promotion_id(platform_metric_id, module, "deferred"),
                        platform_metric_id=platform_metric_id,
                        module=module,
                        decision=PromotionDecision.DEFERRED,
                        definition_sha256=definition_sha256,
                        reason="module_outside_current_skill_scope",
                    )
                )
            continue

        for module in modules:
            policy = module_policy(module)
            if not policy.current_scope:
                continue
            hits: list[tuple[str, str]] = []
            for table_name in policy.tables:
                for canonical_field, aliases in FIELD_ALIASES.get(table_name, {}).items():
                    if target_matches_display_name(
                        display_name,
                        table_name,
                        canonical_field,
                    ):
                        hits.append((table_name, canonical_field))
            if len(hits) != 1:
                continue
            canonical_table, canonical_field = hits[0]
            reviews.append(
                PromotionReview(
                    promotion_id=promotion_id(
                        platform_metric_id,
                        module,
                        f"{canonical_table}.{canonical_field}",
                    ),
                    platform_metric_id=platform_metric_id,
                    module=module,
                    canonical_table=canonical_table,
                    canonical_field=canonical_field,
                    decision=PromotionDecision.PROPOSED,
                    match_basis=BindingMatchBasis.EXACT_EXISTING_ALIAS,
                    confidence=BindingConfidence.HIGH,
                    definition_sha256=definition_sha256,
                    reason="exact_table_scoped_alias_requires_human_approval",
                )
            )
    return sorted(
        reviews,
        key=lambda review: (
            review.platform_metric_id,
            review.module,
            review.canonical_table or "",
            review.canonical_field or "",
        ),
    )


def build_candidate_ledger(
    catalog: PlatformMetricCatalog,
    api_field_rows: list[dict[str, str]],
    field_candidate_rows: list[dict[str, str]],
    proposals: list[PromotionReview],
) -> list[dict[str, object]]:
    proposals_by_metric: dict[int, list[PromotionReview]] = defaultdict(list)
    for proposal in proposals:
        if proposal.decision == PromotionDecision.PROPOSED:
            proposals_by_metric[proposal.platform_metric_id].append(proposal)

    candidate_rows: list[dict[str, object]] = []
    for metric in catalog.metrics:
        targets = [
            f"{review.canonical_table}.{review.canonical_field}@{review.module}"
            for review in proposals_by_metric.get(metric.platform_metric_id, [])
        ]
        candidate_rows.append(
            candidate_record(
                source_kind="api_metric",
                external_key=str(metric.platform_metric_id),
                label=metric.display_name,
                description=metric.description,
                modules="; ".join(metric.modules),
                source_confidence="high",
                association_confidence="high",
                proposed_target_kind="canonical_field" if targets else "",
                proposed_target_id="; ".join(targets),
                review_status=metric.review_status.value,
                review_reason="; ".join(metric.review_reasons) or "classified_unmapped",
                endpoint_path_value=metric.endpoint_path,
            )
        )

    for row in api_field_rows:
        label = (row.get("field") or "").strip()
        description = (row.get("explanation") or "").strip()
        if not label or not description:
            continue
        external_key = f"api_field:{digest({'label': label, 'description': description})[:20]}"
        candidate_rows.append(
            candidate_record(
                source_kind="api_field",
                external_key=external_key,
                label=label,
                description=description,
                modules=(row.get("modules") or "").strip(),
                source_confidence=(row.get("confidence") or "medium").strip(),
                association_confidence="medium",
                proposed_target_kind="",
                proposed_target_id="",
                review_status="deferred",
                review_reason="no_stable_platform_metric_id",
                endpoint_path_value=endpoint_path(row.get("source_url", "")),
            )
        )

    for row in field_candidate_rows:
        label = (row.get("field") or "").strip()
        description = (row.get("explanation") or "").strip()
        if not label or not description:
            continue
        source_fingerprint = digest(
            {
                "source_asset": (row.get("source_asset") or "unknown_asset").strip(),
                "source_key": (row.get("source_key") or "unknown_key").strip(),
                "label": label,
            }
        )
        candidate_rows.append(
            candidate_record(
                source_kind="ui_tooltip",
                external_key=f"ui_tooltip:{source_fingerprint[:24]}",
                label=label,
                description=description,
                modules="",
                source_confidence=(row.get("confidence") or "medium").strip(),
                association_confidence="low",
                proposed_target_kind="",
                proposed_target_id="",
                review_status="pending",
                review_reason="proximity_pairing_requires_manual_verification",
                endpoint_path_value=endpoint_path(row.get("source_url", "")),
            )
        )

    deduped: dict[str, dict[str, object]] = {}
    for row in candidate_rows:
        candidate_id_value = str(row["candidate_id"])
        previous = deduped.get(candidate_id_value)
        if previous is not None and previous != row:
            raise ValueError(f"candidate ID collision: {candidate_id_value}")
        deduped[candidate_id_value] = row
    return sorted(
        deduped.values(),
        key=lambda row: (str(row["source_kind"]), str(row["external_key"]), str(row["label"])),
    )


def candidate_record(
    *,
    source_kind: str,
    external_key: str,
    label: str,
    description: str,
    modules: str,
    source_confidence: str,
    association_confidence: str,
    proposed_target_kind: str,
    proposed_target_id: str,
    review_status: str,
    review_reason: str,
    endpoint_path_value: str,
) -> dict[str, object]:
    evidence_sha256 = digest(
        {
            "source_kind": source_kind,
            "external_key": external_key,
            "label": label,
            "description": description,
            "modules": modules,
        }
    )
    return {
        "candidate_id": f"cand_{evidence_sha256[:24]}",
        "source_kind": source_kind,
        "external_key": external_key,
        "label": label,
        "description": description,
        "modules": modules,
        "source_confidence": source_confidence,
        "association_confidence": association_confidence,
        "proposed_target_kind": proposed_target_kind,
        "proposed_target_id": proposed_target_id,
        "review_status": review_status,
        "review_reason": review_reason,
        "endpoint_path": endpoint_path_value,
        "sensitivity": "public_definition",
        "report_visibility": "internal_only",
        "evidence_sha256": evidence_sha256,
    }


def build_schema_snapshot(schema_rows: list[dict[str, str]]) -> list[dict[str, object]]:
    snapshot_rows: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in schema_rows:
        raw_endpoint = (row.get("endpoint") or "").strip()
        parsed = urlsplit(raw_endpoint)
        if parsed.hostname in TELEMETRY_HOSTS:
            continue
        path = endpoint_path(raw_endpoint)
        field = (row.get("field") or "").strip()
        json_path = (row.get("json_path") or "").strip()
        observed_types = (row.get("observed_types") or "").strip()
        response_occurrences = (row.get("response_occurrences") or "").strip()
        if not path or not field or not json_path:
            continue
        key = (path, json_path, observed_types)
        evidence_sha256 = digest(
            {
                "endpoint_path": path,
                "field": field,
                "json_path": json_path,
                "observed_types": observed_types,
            }
        )
        snapshot_rows[key] = {
            "endpoint_path": path,
            "field": field,
            "json_path": json_path,
            "observed_types": observed_types,
            "response_occurrences": response_occurrences,
            "schema_role": "wrapper" if field.lower() in GENERIC_SCHEMA_FIELDS else "business",
            "evidence_sha256": evidence_sha256,
        }
    return [snapshot_rows[key] for key in sorted(snapshot_rows)]


def classify_scope(modules: list[str]) -> CatalogScope:
    if modules and all(not module_policy(module).current_scope for module in modules):
        return CatalogScope.DEFERRED
    return CatalogScope.CURRENT


def classify_business_domains(modules: list[str]) -> list[BusinessDomain]:
    domains = list(dict.fromkeys(module_policy(module).domain for module in modules))
    return domains or [BusinessDomain.UNKNOWN]


def module_policy(module: str) -> ModulePolicy:
    return MODULE_POLICIES.get(module, UNKNOWN_MODULE_POLICY)


def classify_measure_kind(display_name: str, description: str) -> MeasureKind:
    if "时长" in display_name or "用时" in display_name:
        return MeasureKind.DURATION_AVERAGE
    if "占比" in display_name:
        return MeasureKind.SHARE
    if "率" in display_name:
        return MeasureKind.RATIO
    if "退款后支付金额" in display_name:
        return MeasureKind.NET_AMOUNT
    if "客单价" in display_name or "人均支付金额" in display_name:
        return MeasureKind.AVERAGE_AMOUNT
    if "金额" in display_name:
        return MeasureKind.AMOUNT_TOTAL
    if re.search(
        r"人数|买家数|用户数|消费者数|客户数|买手数|粉丝数|访客数",
        display_name,
    ):
        if re.search(r"去重|只计为?1?人|只记为?一人|记为一位", description):
            return MeasureKind.DISTINCT_COUNT
        return MeasureKind.COUNT
    if re.search(
        r"次数|订单数|件数|笔记数|笔记篇数|会话量|评价数|包裹数|访问量|浏览量|阅读量",
        display_name,
    ):
        return MeasureKind.EVENT_COUNT
    return MeasureKind.COUNT


def classify_unit(measure_kind: MeasureKind, description: str) -> MetricUnit:
    if measure_kind in {
        MeasureKind.AMOUNT_TOTAL,
        MeasureKind.AVERAGE_AMOUNT,
        MeasureKind.NET_AMOUNT,
    }:
        return MetricUnit.CNY
    if measure_kind in {MeasureKind.RATIO, MeasureKind.SHARE}:
        return MetricUnit.PERCENT
    if measure_kind == MeasureKind.DURATION_AVERAGE:
        if "单位秒" in description:
            return MetricUnit.SECONDS
        if "分钟" in description:
            return MetricUnit.MINUTES
        return MetricUnit.UNKNOWN
    return MetricUnit.COUNT


def classify_caliber(display_name: str, measure_kind: MeasureKind) -> MetricCaliber:
    if measure_kind in {
        MeasureKind.AMOUNT_TOTAL,
        MeasureKind.AVERAGE_AMOUNT,
        MeasureKind.NET_AMOUNT,
    }:
        return MetricCaliber.AMOUNT
    if measure_kind in {MeasureKind.RATIO, MeasureKind.SHARE}:
        return MetricCaliber.DIMENSIONLESS
    if measure_kind == MeasureKind.DURATION_AVERAGE:
        return MetricCaliber.DURATION
    if re.search(
        r"人数|买家数|用户数|消费者数|客户数|买手数|粉丝数|访客数",
        display_name,
    ):
        return MetricCaliber.USER_COUNT
    if "订单数" in display_name or "售后单" in display_name:
        return MetricCaliber.ORDER_COUNT
    if "件数" in display_name:
        return MetricCaliber.ITEM_COUNT
    if "包裹" in display_name:
        return MetricCaliber.PACKAGE_COUNT
    if "笔记数" in display_name or "笔记篇数" in display_name:
        return MetricCaliber.NOTE_COUNT
    if "会话" in display_name:
        return MetricCaliber.SESSION_COUNT
    if re.search(r"次数|评价数|访问量|浏览量|阅读量", display_name):
        return MetricCaliber.EVENT_COUNT
    return MetricCaliber.UNKNOWN


def classify_time_anchor(display_name: str, description: str) -> TimeAnchor:
    if "支付时间" in display_name:
        return TimeAnchor.PAYMENT_TIME
    if "退款时间" in display_name:
        return TimeAnchor.REFUND_COMPLETION_TIME
    if "订单支付时间" in description:
        return TimeAnchor.PAYMENT_TIME
    if "发布至今" in description:
        return TimeAnchor.LIFETIME_SINCE_PUBLISH
    if "统计时间" in description or "统计周期" in description:
        return TimeAnchor.ANALYSIS_WINDOW
    if re.search(r"当日|当天|每日|本轮", description):
        return TimeAnchor.EVENT_TIME
    return TimeAnchor.UNKNOWN


def classify_additivity(measure_kind: MeasureKind) -> Additivity:
    if measure_kind in {
        MeasureKind.AVERAGE_AMOUNT,
        MeasureKind.RATIO,
        MeasureKind.SHARE,
        MeasureKind.DURATION_AVERAGE,
        MeasureKind.DISTINCT_COUNT,
    }:
        return Additivity.FALSE
    return Additivity.UNKNOWN


def classify_boundedness(description: str) -> Boundedness:
    if re.search(r"大于\s*100%|超过\s*100%", description):
        return Boundedness.MAY_EXCEED_1
    return Boundedness.UNKNOWN


def classify_refund_inclusion(display_name: str, description: str) -> RefundInclusion:
    if "退款后支付金额" in display_name:
        return RefundInclusion.NET_AFTER_REFUND
    if "退款" in display_name:
        return RefundInclusion.REFUND_POOL
    if re.search(r"(?:未|不)剔除(?:成功)?退款", description):
        return RefundInclusion.GROSS_INCLUDES_REFUNDS
    return RefundInclusion.UNKNOWN


def has_explicit_division_formula(description: str) -> bool:
    description_without_dates = re.sub(
        r"(?<!\d)(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?!\d)",
        "",
        description,
    )
    return bool(re.search(r"÷|除以|/", description_without_dates))


def classify_confidence(
    measure_kind: MeasureKind,
    unit: MetricUnit,
) -> ClassificationConfidence:
    if measure_kind == MeasureKind.DURATION_AVERAGE and unit == MetricUnit.UNKNOWN:
        return ClassificationConfidence.LOW
    if measure_kind == MeasureKind.COUNT:
        return ClassificationConfidence.MEDIUM
    return ClassificationConfidence.HIGH


def classify_review_reasons(
    platform_metric_id: int,
    display_name: str,
    description: str,
    display_name_counts: Counter[str],
    unit: MetricUnit,
    proposal_ids: set[int],
) -> list[str]:
    reasons: list[str] = []
    if display_name_counts[display_name] > 1:
        reasons.append("duplicate_display_name")
    if unit == MetricUnit.UNKNOWN and ("时长" in display_name or "用时" in display_name):
        reasons.append("unknown_duration_unit")
    if re.search(r"最长追踪\s*90\s*天", description):
        reasons.append("refund_maturity_window_90_days")
    if re.search(r"大于\s*100%|超过\s*100%", description):
        reasons.append("ratio_may_exceed_100_percent")
    if "发布至今" in description:
        reasons.append("lifetime_metric_not_window_additive")
    if platform_metric_id in proposal_ids:
        reasons.append("proposed_binding_not_approved")
    return reasons


def split_modules(raw_modules: str) -> list[str]:
    return list(
        dict.fromkeys(module.strip() for module in raw_modules.split(";") if module.strip())
    )


def parse_optional_bool(value: str) -> bool | None:
    normalized = value.strip().lower()
    if not normalized:
        return None
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError(f"invalid optional boolean: {value!r}")


def endpoint_path(url: str) -> str:
    paths: list[str] = []
    for raw_url in re.split(r";\s*", url.strip()):
        if not raw_url:
            continue
        parsed = urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            continue
        allowed_prefixes = ALLOWED_ENDPOINT_PREFIXES.get(parsed.hostname)
        if allowed_prefixes is None or not parsed.path.startswith(allowed_prefixes):
            continue
        if ".." in parsed.path.split("/") or ".har" in parsed.path.casefold():
            continue
        paths.append(parsed.path)
    return "; ".join(dict.fromkeys(paths)) or "/unknown"


def promotion_id(platform_metric_id: int, module: str, target: str) -> str:
    return f"promo_{digest({'id': platform_metric_id, 'module': module, 'target': target})[:24]}"


def digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_yaml(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False, width=120)
    path.write_text(text, encoding="utf-8")


def write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else value for key, value in row.items()})


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
