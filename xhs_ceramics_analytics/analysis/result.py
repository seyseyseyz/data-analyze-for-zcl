from dataclasses import dataclass, field

from xhs_ceramics_analytics.evidence import EvidenceStrength


@dataclass
class Finding:
    title: str
    conclusion: str
    evidence_strength: EvidenceStrength
    key_numbers: dict[str, object] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)
    recommended_action: str | None = None
    evidence_reason: str | None = None


@dataclass
class AnalysisResult:
    task_id: str
    title: str
    findings: list[Finding]
    tables: dict[str, list[dict[str, object]]] = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
