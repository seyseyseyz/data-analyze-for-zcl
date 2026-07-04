from dataclasses import dataclass, field

from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength


@dataclass
class Finding:
    title: str
    conclusion: str
    evidence_strength: EvidenceStrength
    key_numbers: dict[str, object] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    evidence_reason: str | None = None
    confounders: list[str] = field(default_factory=list)
    next_test: str | None = None
    appendix: str | None = None
    # Orthogonal to evidence_strength (causal): how precisely this finding's
    # numbers describe the observed period. None when a module has not scored it.
    descriptive_reliability: DescriptiveReliability | None = None


@dataclass
class Subsection:
    title: str
    body: str | None = None
    table_name: str | None = None
    findings: list[Finding] = field(default_factory=list)


@dataclass
class AnalysisResult:
    task_id: str
    title: str
    findings: list[Finding]
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    subsections: list[Subsection] = field(default_factory=list)
    named_examples: list[dict[str, object]] = field(default_factory=list)
