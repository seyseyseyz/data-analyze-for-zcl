"""Opt-in report-contract guard for analysis findings.

Consuming §-tasks call ``assert_finding_contract`` on the findings they emit.
It is deliberately NOT wired into the renderers: legacy findings predate the
confounders/next_test fields and are grandfathered.
"""
from xhs_ceramics_analytics.analysis.result import Finding
from xhs_ceramics_analytics.evidence import EvidenceStrength

_REQUIRES_FULL_CONTRACT = {EvidenceStrength.STRONG, EvidenceStrength.MEDIUM}


def assert_finding_contract(finding: Finding) -> None:
    """Raise ``ValueError`` if a STRONG/MEDIUM finding omits required elements."""
    if finding.evidence_strength not in _REQUIRES_FULL_CONTRACT:
        return
    missing: list[str] = []
    if not finding.confounders:
        missing.append("confounders")
    if not finding.next_test:
        missing.append("next_test")
    if missing:
        raise ValueError(
            f"{finding.evidence_strength.value} finding {finding.title!r} "
            f"missing required contract fields: {', '.join(missing)}."
        )
