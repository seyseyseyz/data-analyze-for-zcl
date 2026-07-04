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
    if sample_size >= 10 and has_controls and confounder_count <= 1:
        return EvidenceStrength.MEDIUM
    return EvidenceStrength.WEAK


class DescriptiveReliability(StrEnum):
    """How precisely a described quantity is pinned down for the period observed.

    This is orthogonal to :class:`EvidenceStrength`. ``score_evidence`` answers
    "can this support a causal claim" — observational data caps at WEAK there.
    ``score_reliability`` answers a different question: "how trustworthy is this
    number *as a description of what happened*", which large samples and tight
    confidence intervals genuinely support even when no causal claim is possible.
    Reporting both keeps a precise, high-volume fact from reading like a hunch.
    """

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOT_APPLICABLE = "not_applicable"


# Volume behind the number (the denominator) governs the no-CI fallback.
_RELIABILITY_HIGH_N = 100
_RELIABILITY_MEDIUM_N = 30
# When a proportion CI is available, its absolute width (hi - lo) governs precision.
_RELIABILITY_HIGH_CI_WIDTH = 0.10
_RELIABILITY_MEDIUM_CI_WIDTH = 0.20


def score_reliability(
    sample_size: int | None,
    ci_low: float | None = None,
    ci_high: float | None = None,
) -> DescriptiveReliability:
    """Grade descriptive precision from sample size and (optionally) a CI width.

    Never raises — bad inputs degrade to ``NOT_APPLICABLE``. With a proportion CI,
    precision is driven by its width (a rare event over a huge denominator can
    still be imprecise). Without a CI, it falls back to the raw volume behind the
    number.
    """
    if sample_size is None or sample_size <= 0:
        return DescriptiveReliability.NOT_APPLICABLE
    if ci_low is not None and ci_high is not None:
        width = abs(ci_high - ci_low)
        if sample_size >= _RELIABILITY_HIGH_N and width <= _RELIABILITY_HIGH_CI_WIDTH:
            return DescriptiveReliability.HIGH
        if sample_size >= _RELIABILITY_MEDIUM_N and width <= _RELIABILITY_MEDIUM_CI_WIDTH:
            return DescriptiveReliability.MEDIUM
        return DescriptiveReliability.LOW
    if sample_size >= _RELIABILITY_HIGH_N:
        return DescriptiveReliability.HIGH
    if sample_size >= _RELIABILITY_MEDIUM_N:
        return DescriptiveReliability.MEDIUM
    return DescriptiveReliability.LOW
