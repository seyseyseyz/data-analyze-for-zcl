"""facts_export — the single source of every number string in the report.

An ``AnalysisResult`` list is distilled into a ``FactBook``: one immutable ``Fact``
per numeric key_number, plus the registries and ledgers the gate and writer need.
Every money/percent value is pre-rendered here by Python (``rendered``) so the
narrative layer only ever copies a string — it can never round or invent a number.
Raw floats live in ``Fact.value`` for computation but are EXCLUDED from the hash
(see Task 11) so float noise never thrashes the cache. Conflicting duplicate
``fact_id`` values are rejected before sidecars are published.
"""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.contracts.metrics import (
    MetricRuntimeIndex,
    MetricRuntimeScope,
    build_metric_runtime_index,
    load_metric_registry,
)
from xhs_ceramics_analytics.contracts.platform_catalog import (
    build_platform_semantic_context,
)
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength
from xhs_ceramics_analytics.reporting.formatting import is_money_field, is_percent_field
from xhs_ceramics_analytics.reporting.labels import format_index, format_magnitude


@dataclass(frozen=True)
class Fact:
    fact_id: str
    value: float | None
    rendered: str
    metric_key: str
    unit: str
    metric_id: str | None = None
    display_name: str | None = None
    caliber: str | None = None
    aggregation: str | None = None
    grain: str | None = None
    formula: str | None = None
    mapping_error: str | None = None
    denominator: str | None = None
    evidence_strength: EvidenceStrength = EvidenceStrength.NOT_JUDGABLE
    descriptive_reliability: DescriptiveReliability | None = None
    entity_type: str | None = None
    direction: str | None = None
    pool_id: str | None = None
    assumption: str | None = None


@dataclass(frozen=True)
class MetricMappingDiagnostics:
    status: str = "disabled"
    mapped_count: int = 0
    unmapped_count: int = 0
    unmapped_fact_ids: tuple[str, ...] = ()
    rejection_reasons: dict[str, str] = field(default_factory=dict)
    registry_hash: str | None = None
    error: str | None = None

    @property
    def coverage_rate(self) -> float | None:
        total = self.mapped_count + self.unmapped_count
        return self.mapped_count / total if total else None

    @property
    def rejected_count(self) -> int:
        return len(self.rejection_reasons)


@dataclass(frozen=True)
class FactBook:
    facts: dict[str, Fact] = field(default_factory=dict)
    entity_registry: list[str] = field(default_factory=list)
    non_additive_ledger: dict = field(default_factory=dict)
    absent_link_registry: list[str] = field(default_factory=list)
    module_reading: dict = field(default_factory=dict)
    blocked_modules: list[str] = field(default_factory=list)
    shared_spine_facts: list[str] = field(default_factory=list)
    domain_slices: dict = field(default_factory=dict)
    metric_mapping: MetricMappingDiagnostics = field(default_factory=MetricMappingDiagnostics)


@dataclass(frozen=True)
class ResultFindingRef:
    path: str
    finding: Finding


def iter_result_finding_refs(result: AnalysisResult):
    """Yield every finding with a deterministic structural path.

    Paths use collection positions rather than reader-facing titles, so punctuation,
    localization, or copy edits cannot change fact identity for an unchanged structure.
    """
    for finding_index, finding in enumerate(result.findings):
        yield ResultFindingRef(path=f"finding_{finding_index:02d}", finding=finding)
    for subsection_index, subsection in enumerate(result.subsections):
        for finding_index, finding in enumerate(subsection.findings):
            yield ResultFindingRef(
                path=f"subsection_{subsection_index:02d}.finding_{finding_index:02d}",
                finding=finding,
            )


def iter_result_findings(result: AnalysisResult):
    for ref in iter_result_finding_refs(result):
        yield ref.finding


def fact_id_map_for_result(result: AnalysisResult) -> dict[tuple[str, str], str]:
    """Map ``(finding_path, metric_key)`` to one deterministic numeric fact id.

    A key that occurs once keeps its legacy ``task.key`` id. Repeated keys receive a
    structural scope, preventing collisions without needlessly invalidating existing
    narrative bindings for the common unique-key case.
    """
    refs = list(iter_result_finding_refs(result))
    key_counts = Counter(
        str(key)
        for ref in refs
        for key, raw in ref.finding.key_numbers.items()
        if to_finite_float(raw) is not None
    )
    return {
        (ref.path, str(key)): (
            f"{result.task_id}.{key}"
            if key_counts[str(key)] == 1
            else f"{result.task_id}.{ref.path}.{key}"
        )
        for ref in refs
        for key, raw in ref.finding.key_numbers.items()
        if to_finite_float(raw) is not None
    }


def _grouped_magnitude(value: object, *, currency: bool) -> str:
    """Grouped magnitude string for the facts appendix, guarding non-finite values.

    Non-finite / missing values degrade to ``—``; every finite value delegates to the
    shared :func:`labels.format_magnitude` rule (≥1万 → 万-notation 1dp, else grouped
    whole units, ``¥`` when ``currency``), so a facts number reads identically to the
    same amount in prose / tables / charts. Shared by :func:`render_cny` /
    :func:`render_count`.
    """
    v = to_finite_float(value)
    if v is None:
        return "—"
    return format_magnitude(v, currency=currency)


def render_cny(value: object) -> str:
    """Python-owned money string. ≥1万 → 万-notation (1dp); else grouped yuan."""
    return _grouped_magnitude(value, currency=True)


def render_count(value: object) -> str:
    """Python-owned count string — like ``render_cny`` but no currency sign."""
    return _grouped_magnitude(value, currency=False)


def render_index(value: object) -> str:
    """Python-owned concentration-index string (HHI/gini). Dimensionless — no currency
    sign, no percent scaling. Mirrors the table path (``format_scalar``'s ``_hhi``
    branch via :func:`format_index`) so a 0.0028 HHI stays ``0.0028`` and a 0.64 gini
    stays ``0.64`` instead of being flattened to ``¥1``. A value that rounds to zero
    reads ``0``; a non-finite value degrades to ``—``."""
    v = to_finite_float(value)
    if v is None:
        return "—"
    return format_index(v)


def render_pct(value: object) -> str:
    """Python-owned percent string. Fractions (|v|≤1) are scaled ×100; already-scaled
    percentage-point values pass through so a rate is never double-scaled. A value that
    rounds to zero drops the minus sign so the reader never sees ``-0.0%``."""
    v = to_finite_float(value)
    if v is None:
        return "—"
    scaled = v * 100 if abs(v) <= 1 else v
    text = f"{scaled:.1f}"
    if text == "-0.0":  # tiny negative rounded to zero → normalize the sign
        text = "0.0"
    return f"{text}%"


# key_numbers carry no unit metadata, so a numeric fact's kind is inferred from its
# metric key. Defaulting the unknown to a *count* (never money) is the safe direction:
# a mislabeled 250 reads as "250" not "¥250", and a rate 0.23 reads as "23.0%" not "¥0".
#
# These are only a LAST-RESORT substring heuristic for keys the fact-layer allow-lists
# (``is_percent_field`` / ``is_money_field``) don't name — ``_metric_kind`` consults the
# allow-lists FIRST so a key classifies identically here and on the table path. Loose
# tokens that both directions can own were removed: "conversion" (contrib_conversion is
# yuan, in MONEY_FIELDS — the old substring forced it to a bogus "-17104.8%") and "pct"
# (real ``*_pct`` change-fractions live in PERCENT_FIELDS/`_pct` suffix already).
_PERCENT_HINTS_ASCII = ("rate", "ratio", "percent", "roi", "roas", "share")
_PERCENT_HINTS_CJK = ("率", "占比", "渗透")
_MONEY_HINTS_ASCII = ("gmv", "amount", "price", "revenue", "spend", "cost", "sales")
_MONEY_HINTS_CJK = (
    "金额",
    "客单",
    "单价",
    "价格",
    "成交额",
    "销售额",
    "营收",
    "收入",
    "花费",
    "消耗",
    "退款金额",
    "支付金额",
    "均价",
    "客单价",
)


def _metric_kind(key: str) -> str:
    raw = str(key)
    # Producer-owned cross-period semantics. These fields are sums of daily-distinct
    # users and therefore person-days, not period-unique counts. Observed-day counters
    # take precedence because ``paired_ratio_observed_days`` contains a rate-like token.
    if raw.endswith("_observed_days"):
        return "count"
    if raw.endswith(("_buyer_days", "_visitor_days", "_user_days")):
        return "person_day"
    # Allow-list first: reuse the fact layer's suffix-anchored predicates (the same ones
    # ``format_scalar`` uses), so a known key classifies EXACTLY as the table path does.
    # Percent before money so ``*_share`` concentrations stay percent, never yuan.
    if is_percent_field(raw):
        return "percent"
    # Concentration indices (HHI/gini) are dimensionless. They must be caught BEFORE the
    # money check — both the allow-list (``gmv_gini`` has no unit suffix) and the loose
    # ``gmv`` substring hint below would otherwise force ``repeat_gmv_hhi``/``gmv_gini``
    # to money, flattening a 0.64 index to the nonsensical "¥1". Mirrors format_scalar's
    # dedicated ``_hhi`` branch on the table path.
    if raw.endswith(("_hhi", "_gini")):
        return "index"
    if is_money_field(raw):
        return "money"
    # Fallback: trimmed substring hints only for keys the anchored allow-lists don't name.
    low = raw.lower()
    if any(h in low for h in _PERCENT_HINTS_ASCII) or any(h in raw for h in _PERCENT_HINTS_CJK):
        return "percent"
    if any(h in low for h in _MONEY_HINTS_ASCII) or any(h in raw for h in _MONEY_HINTS_CJK):
        return "money"
    return "count"


_RENDER = {
    "money": render_cny,
    "percent": render_pct,
    "count": render_count,
    "person_day": render_count,
    "index": render_index,
}
_UNIT = {
    "money": "cny",
    "percent": "percent",
    "count": "count",
    "person_day": "person_day",
    "index": "index",
}


def _renderer_for_unit(unit: str):
    return {
        "cny": render_cny,
        "percent": render_pct,
        "pp": render_pct,
        "count": render_count,
        "person_day": render_count,
        "index": render_index,
    }.get(unit, render_count)


def numeric_facts_from_finding(
    task_id: str,
    finding,
    *,
    metric_index: MetricRuntimeIndex | None = None,
    fact_ids: Mapping[str, str] | None = None,
) -> dict[str, Fact]:
    """The single source of ``fact_id`` truth: one ``Fact`` per NUMERIC key_number,
    keyed ``{task_id}.{key}`` and pre-rendered by Python. Non-numeric keys (labels)
    are skipped. Reused by the narrative slice producer so a claim's ``{tN}`` binds to
    the exact same ``fact_id`` the gate validates against — coupling by construction,
    never by a re-derived formula. Pure, never raises."""
    facts: dict[str, Fact] = {}
    for key, raw in finding.key_numbers.items():
        v = to_finite_float(raw)
        if v is None:  # non-numeric (labels like "客单价") are not facts
            continue
        fact_id = fact_ids.get(str(key), f"{task_id}.{key}") if fact_ids else f"{task_id}.{key}"
        kind = _metric_kind(key)
        producer_unit = _UNIT[kind]
        metric = None
        mapping_error = None
        if metric_index is not None:
            legacy_fact_id = f"{task_id}.{key}"
            if metric_index.resolve(fact_id) is not None:
                metric, mapping_error = metric_index.resolve_validated(
                    fact_id,
                    metric_key=str(key),
                    producer_unit=producer_unit,
                )
            elif fact_id != legacy_fact_id and metric_index.resolve(legacy_fact_id) is not None:
                mapping_error = (
                    f"scoped fact requires an explicit registry binding: {legacy_fact_id}"
                )
            else:
                metric, mapping_error = metric_index.resolve_validated(
                    fact_id,
                    metric_key=str(key),
                    producer_unit=producer_unit,
                )
        unit = str(metric.unit) if metric is not None else producer_unit
        facts[fact_id] = Fact(
            fact_id=fact_id,
            value=v,
            rendered=_renderer_for_unit(unit)(v),
            metric_key=key,
            unit=unit,
            metric_id=metric.metric_id if metric is not None else None,
            display_name=metric.display_name if metric is not None else None,
            caliber=str(metric.caliber) if metric is not None else None,
            aggregation=str(metric.aggregation)
            if metric is not None and metric.aggregation
            else None,
            grain=str(metric.grain) if metric is not None else None,
            formula=metric.formula if metric is not None else None,
            mapping_error=mapping_error,
            denominator=metric.denominator if metric is not None else None,
            evidence_strength=finding.evidence_strength,
            descriptive_reliability=finding.descriptive_reliability,
        )
    return facts


def _merge_facts(target: dict[str, Fact], incoming: dict[str, Fact]) -> None:
    for fact_id, fact in incoming.items():
        existing = target.get(fact_id)
        if existing is not None and existing != fact:
            raise ValueError(f"conflicting fact_id: {fact_id}")
        target[fact_id] = fact


def build_factbook(
    results: list[AnalysisResult],
    *,
    blocked_modules: tuple[str, ...] = (),
    absent_links: tuple[str, ...] = (),
    non_additive: dict | None = None,
    shared_spine_facts: tuple[str, ...] = (),
    domain_slices: dict | None = None,
    metric_registry_path: Path | None = None,
) -> FactBook:
    """Distil analysis results into an immutable FactBook."""
    metric_index: MetricRuntimeIndex | None = None
    metric_status = "disabled"
    metric_error: str | None = None
    try:
        registry = load_metric_registry(metric_registry_path)
        if (
            registry.runtime_consumed
            and MetricRuntimeScope.FACT_ANNOTATION in registry.runtime_scopes
        ):
            metric_index = build_metric_runtime_index(registry)
            metric_status = str(registry.runtime_mode)
    except Exception as exc:
        metric_status = "unavailable"
        metric_error = str(exc)

    facts: dict[str, Fact] = {}
    entities: list[str] = []
    module_reading: dict = {}
    for result in results:
        refs = list(iter_result_finding_refs(result))
        result_findings = [ref.finding for ref in refs]
        id_map = fact_id_map_for_result(result)
        for ref in refs:
            _merge_facts(
                facts,
                numeric_facts_from_finding(
                    result.task_id,
                    ref.finding,
                    metric_index=metric_index,
                    fact_ids={
                        str(key): fact_id
                        for (path, key), fact_id in id_map.items()
                        if path == ref.path
                    },
                ),
            )
        for example in result.named_examples:
            name = example.get("name")
            if name and name not in entities:
                entities.append(str(name))
        if result_findings:
            head = result_findings[0]
            module_reading[result.task_id] = {
                "conclusion": head.conclusion,
                "action": head.recommended_action,
                "caveats": list(head.caveats),
            }
    unmapped_fact_ids = tuple(
        sorted(fact_id for fact_id, fact in facts.items() if fact.metric_id is None)
    )
    rejection_reasons = {
        fact_id: fact.mapping_error
        for fact_id, fact in sorted(facts.items())
        if fact.mapping_error is not None
    }
    return FactBook(
        facts=facts,
        entity_registry=entities,
        non_additive_ledger=non_additive or {},
        absent_link_registry=list(absent_links),
        module_reading=module_reading,
        blocked_modules=list(blocked_modules),
        shared_spine_facts=list(shared_spine_facts),
        domain_slices=domain_slices or {},
        metric_mapping=MetricMappingDiagnostics(
            status=metric_status,
            mapped_count=len(facts) - len(unmapped_fact_ids),
            unmapped_count=len(unmapped_fact_ids),
            unmapped_fact_ids=unmapped_fact_ids,
            rejection_reasons=rejection_reasons,
            registry_hash=metric_index.registry_hash if metric_index is not None else None,
            error=metric_error,
        ),
    )


# Bump only with an intentional canonicalization change (moves every facts_hash).
CANONICAL_VERSION = 3


def _fact_canonical(fact: Fact) -> dict:
    """Fact fields that define identity for hashing — raw ``value`` deliberately absent."""
    return {
        "fact_id": fact.fact_id,
        "rendered": fact.rendered,
        "metric_key": fact.metric_key,
        "metric_id": fact.metric_id,
        "unit": fact.unit,
        "caliber": fact.caliber,
        "denominator": fact.denominator,
        "evidence_strength": str(fact.evidence_strength),
        "descriptive_reliability": (
            str(fact.descriptive_reliability) if fact.descriptive_reliability else None
        ),
        "entity_type": fact.entity_type,
        "direction": fact.direction,
        "pool_id": fact.pool_id,
        "assumption": fact.assumption,
    }


def _float_stable(obj: object) -> object:
    """Round floats to a fixed precision so ledger/slice float noise never thrashes the
    cache (129000.0000001 == 129000.0). Recurses into dicts/lists; leaves the rest as-is."""
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, 6)
    if isinstance(obj, dict):
        return {k: _float_stable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_float_stable(v) for v in obj]
    return obj


def canonical_payload(book: FactBook) -> dict:
    """Deterministic, float-noise-free view of a FactBook for hashing."""
    return {
        "canonical_version": CANONICAL_VERSION,
        "registry_hash": book.metric_mapping.registry_hash,
        "facts": {fid: _fact_canonical(book.facts[fid]) for fid in sorted(book.facts)},
        "entity_registry": sorted(book.entity_registry),
        "absent_link_registry": sorted(book.absent_link_registry),
        "blocked_modules": sorted(book.blocked_modules),
        "shared_spine_facts": sorted(book.shared_spine_facts),
        "non_additive_ledger": _float_stable(book.non_additive_ledger),
        "domain_slices": _float_stable(book.domain_slices),
    }


def facts_hash(book: FactBook) -> str:
    """sha256 of the canonical (float-noise-free) payload. The cache key. Never raises."""
    blob = json.dumps(
        canonical_payload(book),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fact_full(fact: Fact) -> dict:
    d = _fact_canonical(fact)
    d["value"] = fact.value  # full JSON keeps the raw value for the narrative layer
    d["display_name"] = fact.display_name
    d["aggregation"] = fact.aggregation
    d["grain"] = fact.grain
    d["formula"] = fact.formula
    d["mapping_error"] = fact.mapping_error
    return d


def metric_mapping_to_dict(diagnostics: MetricMappingDiagnostics) -> dict:
    payload = {
        "status": diagnostics.status,
        "mapped_count": diagnostics.mapped_count,
        "unmapped_count": diagnostics.unmapped_count,
        "coverage_rate": diagnostics.coverage_rate,
        "unmapped_fact_ids": list(diagnostics.unmapped_fact_ids),
        "error": diagnostics.error,
    }
    if diagnostics.rejection_reasons:
        payload["rejected_count"] = diagnostics.rejected_count
        payload["rejection_reasons"] = diagnostics.rejection_reasons
    return payload


def factbook_to_json(book: FactBook) -> str:
    """Full deterministic JSON (includes raw ``value``) for downstream agents."""
    payload = {
        "canonical_version": CANONICAL_VERSION,
        "facts_hash": facts_hash(book),
        "registry_hash": book.metric_mapping.registry_hash,
        "metric_mapping": metric_mapping_to_dict(book.metric_mapping),
        "platform_semantics": build_platform_semantic_context(),
        "facts": {fid: _fact_full(book.facts[fid]) for fid in sorted(book.facts)},
        "entity_registry": sorted(book.entity_registry),
        "absent_link_registry": sorted(book.absent_link_registry),
        "module_reading": book.module_reading,
        "blocked_modules": sorted(book.blocked_modules),
        "shared_spine_facts": sorted(book.shared_spine_facts),
        "non_additive_ledger": book.non_additive_ledger,
        "domain_slices": book.domain_slices,
    }
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2, default=str)


# GOLDEN: placeholder; replaced with the real hash in Step 4.
_GOLDEN_TEST_HASH = "b0b674bcebbbd3632c83e3f94cf1bcbcd0cfe4ceb71e82ae9060f9718b15a5ad"
