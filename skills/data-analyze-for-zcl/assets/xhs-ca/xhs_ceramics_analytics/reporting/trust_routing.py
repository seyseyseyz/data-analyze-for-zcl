"""Route the two evidence axes + claim kind to a reader-facing 强/中/弱 tag.

The tag CALIBRATES a conclusion — it never suppresses it (bold judgments are the
North Star). A mechanism/causal claim on this single-window, no-control data is
capped at 弱 regardless of how clean the underlying numbers look. Measurement and
sizing claims earn 强 from a strong-evidence or high-descriptive-reliability
anchor, 中 from a medium anchor, else 弱. Pure function, never raises.
"""
from xhs_ceramics_analytics.evidence import DescriptiveReliability, EvidenceStrength

_STRONG, _MEDIUM, _WEAK = "强", "中", "弱"


def confidence_tag(
    evidence_strength: EvidenceStrength,
    descriptive_reliability: DescriptiveReliability | None,
    claim_kind: str,
) -> str:
    """Return 强/中/弱. Mechanism claims are always 弱 (single-window causal cap)."""
    if claim_kind == "mechanism":
        return _WEAK
    if (
        evidence_strength == EvidenceStrength.STRONG
        or descriptive_reliability == DescriptiveReliability.HIGH
    ):
        return _STRONG
    if descriptive_reliability == DescriptiveReliability.MEDIUM:
        return _MEDIUM
    return _WEAK
