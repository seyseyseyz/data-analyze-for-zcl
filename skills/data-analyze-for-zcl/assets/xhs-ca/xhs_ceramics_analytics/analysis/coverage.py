"""Task coverage assessment — which analyses the current DB can actually produce.

The report only ever contained a few sections because task selection was manual
and easy to under-pick. Coverage inverts that: it runs every registered task
against the built DB and classifies each as *producible* (at least one finding
above NOT_JUDGABLE) or *blocked* (degraded), capturing the blocking reason so the
workflow can (a) include every producible task by default and (b) tell the
operator exactly what data unlocks the rest. Never raises — a task that errors is
reported as blocked with the exception text.
"""
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
from xhs_ceramics_analytics.evidence import EvidenceStrength


@dataclass(frozen=True)
class TaskCoverage:
    task_id: str
    producible: bool
    finding_count: int
    strengths: dict[str, int] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def assess_coverage(db_path: Path) -> list[TaskCoverage]:
    """Classify every registered task against ``db_path``. Order follows TASKS."""
    coverage: list[TaskCoverage] = []
    for task_id in TASKS:
        try:
            result = run_task(task_id, db_path)
        except Exception as exc:  # never raise — a broken task is just "blocked"
            coverage.append(
                TaskCoverage(task_id, False, 0, {}, [f"运行异常：{type(exc).__name__}: {exc}"])
            )
            continue
        strengths = dict(Counter(f.evidence_strength.value for f in result.findings))
        producible = any(
            f.evidence_strength != EvidenceStrength.NOT_JUDGABLE for f in result.findings
        )
        reasons: list[str] = []
        if not producible:
            reasons = list(result.limitations) or [
                f.conclusion for f in result.findings
            ]
        coverage.append(
            TaskCoverage(task_id, producible, len(result.findings), strengths, reasons)
        )
    return coverage


def producible_task_ids(db_path: Path) -> list[str]:
    """The task ids that yield at least one non-NOT_JUDGABLE finding, in TASKS order."""
    return [c.task_id for c in assess_coverage(db_path) if c.producible]
