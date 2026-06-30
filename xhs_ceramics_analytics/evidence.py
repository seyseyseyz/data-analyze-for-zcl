from enum import StrEnum


class EvidenceStrength(StrEnum):
    STRONG = "strong"
    MEDIUM = "medium"
    WEAK = "weak"
    NOT_JUDGABLE = "not_judgable"


def score_evidence(
    sample_size: int, has_controls: bool, confounder_count: int
) -> EvidenceStrength:
    if sample_size <= 0 or confounder_count < 0:
        return EvidenceStrength.NOT_JUDGABLE
    if sample_size >= 30 and has_controls and confounder_count == 0:
        return EvidenceStrength.STRONG
    if sample_size >= 10 and confounder_count <= 1:
        return EvidenceStrength.MEDIUM
    return EvidenceStrength.WEAK
