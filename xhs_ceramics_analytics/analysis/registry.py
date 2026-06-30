from pathlib import Path
from typing import Callable

from xhs_ceramics_analytics.analysis import account_baseline, data_quality, note_funnel
from xhs_ceramics_analytics.analysis.result import AnalysisResult


TASKS: dict[str, Callable[[Path], AnalysisResult]] = {
    "data_quality_check": data_quality.run,
    "account_baseline": account_baseline.run,
    "note_funnel": note_funnel.run,
}


def run_task(task_id: str, db_path: Path) -> AnalysisResult:
    if task_id not in TASKS:
        raise KeyError(f"unknown analysis task: {task_id}")
    return TASKS[task_id](db_path)
