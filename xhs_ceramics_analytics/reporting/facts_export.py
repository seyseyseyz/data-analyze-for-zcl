"""facts_export — the single source of every number string in the report.

An ``AnalysisResult`` list is distilled into a ``FactBook``: one immutable ``Fact``
per numeric key_number, plus the registries and ledgers the gate and writer need.
Every money/percent value is pre-rendered here by Python (``rendered``) so the
narrative layer only ever copies a string — it can never round or invent a number.
Raw floats live in ``Fact.value`` for computation but are EXCLUDED from the hash
(see Task 11) so float noise never thrashes the cache. Pure + never raises.
"""
import hashlib
import json
from dataclasses import dataclass, field

from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.analytics.numeric import to_finite_float
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength


@dataclass(frozen=True)
class Fact:
    fact_id: str
    value: float | None
    rendered: str
    metric_key: str
    unit: str
    caliber: str | None = None
    denominator: str | None = None
    evidence_strength: EvidenceStrength = EvidenceStrength.NOT_JUDGABLE
    descriptive_reliability: DescriptiveReliability | None = None
    entity_type: str | None = None
    direction: str | None = None
    pool_id: str | None = None
    assumption: str | None = None


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


def render_cny(value: object) -> str:
    """Python-owned money string. ≥1万 → 万-notation (1dp); else grouped yuan."""
    v = to_finite_float(value)
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    mag = abs(v)
    if mag >= 10000:
        return f"{sign}¥{mag / 10000:.1f}万"
    return f"{sign}¥{mag:,.0f}"


def render_count(value: object) -> str:
    """Python-owned count string — like ``render_cny`` but no currency sign."""
    v = to_finite_float(value)
    if v is None:
        return "—"
    sign = "-" if v < 0 else ""
    mag = abs(v)
    if mag >= 10000:
        return f"{sign}{mag / 10000:.1f}万"
    return f"{sign}{mag:,.0f}"


def render_pct(value: object) -> str:
    """Python-owned percent string. Fractions (|v|≤1) are scaled ×100; already-scaled
    percentage-point values pass through so a rate is never double-scaled."""
    v = to_finite_float(value)
    if v is None:
        return "—"
    scaled = v * 100 if abs(v) <= 1 else v
    return f"{scaled:.1f}%"


# key_numbers carry no unit metadata, so a numeric fact's kind is inferred from its
# metric key. Defaulting the unknown to a *count* (never money) is the safe direction:
# a mislabeled 250 reads as "250" not "¥250", and a rate 0.23 reads as "23.0%" not "¥0".
_PERCENT_HINTS_ASCII = ("rate", "ratio", "conversion", "pct", "percent", "roi", "roas", "share")
_PERCENT_HINTS_CJK = ("率", "占比", "渗透")
_MONEY_HINTS_ASCII = ("gmv", "amount", "price", "revenue", "spend", "cost", "sales")
_MONEY_HINTS_CJK = (
    "金额", "客单", "单价", "价格", "成交额", "销售额", "营收", "收入",
    "花费", "消耗", "退款金额", "支付金额", "均价", "客单价",
)


def _metric_kind(key: str) -> str:
    raw = str(key)
    low = raw.lower()
    if any(h in low for h in _PERCENT_HINTS_ASCII) or any(h in raw for h in _PERCENT_HINTS_CJK):
        return "percent"
    if any(h in low for h in _MONEY_HINTS_ASCII) or any(h in raw for h in _MONEY_HINTS_CJK):
        return "money"
    return "count"


_RENDER = {"money": render_cny, "percent": render_pct, "count": render_count}
_UNIT = {"money": "cny", "percent": "percent", "count": "count"}


def _numeric_facts_from_finding(task_id: str, finding) -> dict[str, Fact]:
    facts: dict[str, Fact] = {}
    for key, raw in finding.key_numbers.items():
        v = to_finite_float(raw)
        if v is None:  # non-numeric (labels like "客单价") are not facts
            continue
        fact_id = f"{task_id}.{key}"
        kind = _metric_kind(key)
        facts[fact_id] = Fact(
            fact_id=fact_id,
            value=v,
            rendered=_RENDER[kind](v),
            metric_key=key,
            unit=_UNIT[kind],
            evidence_strength=finding.evidence_strength,
            descriptive_reliability=finding.descriptive_reliability,
        )
    return facts


def build_factbook(
    results: list[AnalysisResult],
    *,
    blocked_modules: tuple[str, ...] = (),
    absent_links: tuple[str, ...] = (),
    non_additive: dict | None = None,
    shared_spine_facts: tuple[str, ...] = (),
    domain_slices: dict | None = None,
) -> FactBook:
    """Distil analysis results into an immutable FactBook. Never raises."""
    facts: dict[str, Fact] = {}
    entities: list[str] = []
    module_reading: dict = {}
    for result in results:
        for finding in result.findings:
            facts.update(_numeric_facts_from_finding(result.task_id, finding))
        for example in result.named_examples:
            name = example.get("name")
            if name and name not in entities:
                entities.append(str(name))
        if result.findings:
            head = result.findings[0]
            module_reading[result.task_id] = {
                "conclusion": head.conclusion,
                "action": head.recommended_action,
                "caveats": list(head.caveats),
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
    )


# Bump only with an intentional canonicalization change (moves every facts_hash).
CANONICAL_VERSION = 1


def _fact_canonical(fact: Fact) -> dict:
    """Fact fields that define identity for hashing — raw ``value`` deliberately absent."""
    return {
        "fact_id": fact.fact_id,
        "rendered": fact.rendered,
        "metric_key": fact.metric_key,
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
        canonical_payload(book), sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fact_full(fact: Fact) -> dict:
    d = _fact_canonical(fact)
    d["value"] = fact.value  # full JSON keeps the raw value for the narrative layer
    return d


def factbook_to_json(book: FactBook) -> str:
    """Full deterministic JSON (includes raw ``value``) for downstream agents."""
    payload = {
        "facts_hash": facts_hash(book),
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
_GOLDEN_TEST_HASH = "7503129e1ca260142350a0dbe9b03fd01461a27355f58830672447627fc5bf27"
