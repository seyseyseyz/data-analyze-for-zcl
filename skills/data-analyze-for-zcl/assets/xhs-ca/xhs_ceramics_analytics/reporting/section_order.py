"""Canonical section ordering shared by the Markdown and HTML compositors.

Data-quality tasks are transparency/appendix material, not a read-time gate:
the blocking data check runs at build time (字段映射自愈), so by the time a
report is composed these sections *back* the conclusions rather than gate them.
They therefore always render last, no matter what order the slugs were passed
in — the reader hits business conclusions first and the data caveats close out
the report as an appendix.
"""

from xhs_ceramics_analytics.analysis.result import AnalysisResult

# Rendered last, in this order, after every analysis module.
APPENDIX_TASKS: tuple[str, ...] = ("data_quality_check", "ad_data_quality_check")


def order_results(results: list[AnalysisResult]) -> list[AnalysisResult]:
    """Stable-order results so appendix (data-quality) sections come last.

    Non-appendix modules keep the caller's order; appendix modules are moved to
    the end following ``APPENDIX_TASKS`` priority.
    """
    body = [result for result in results if result.task_id not in APPENDIX_TASKS]
    appendix = sorted(
        (result for result in results if result.task_id in APPENDIX_TASKS),
        key=lambda result: APPENDIX_TASKS.index(result.task_id),
    )
    return body + appendix
