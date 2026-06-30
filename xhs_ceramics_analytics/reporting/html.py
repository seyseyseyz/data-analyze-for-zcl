from jinja2 import Environment, PackageLoader, select_autoescape

from xhs_ceramics_analytics.analysis.result import AnalysisResult
from xhs_ceramics_analytics.reporting.markdown import render_markdown


def render_html(results: list[AnalysisResult]) -> str:
    env = Environment(
        loader=PackageLoader("xhs_ceramics_analytics.reporting", "templates"),
        autoescape=select_autoescape(),
    )
    template = env.get_template("report.html.j2")
    return template.render(markdown_report=render_markdown(results), results=results)
