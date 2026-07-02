from pathlib import Path
from typing import Annotated

import typer

from xhs_ceramics_analytics.doctor import has_blocking_failures, next_steps, run_checks
from xhs_ceramics_analytics.paths import outputs_dir, state_dir

app = typer.Typer(help="Xiaohongshu ceramics analytics local runner.")


@app.command()
def build(
    files: Annotated[list[Path], typer.Argument(help="CSV or Excel files to import.")],
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None,
        typer.Option(help="Override local state/output root."),
    ] = None,
) -> None:
    from xhs_ceramics_analytics.db.build import build_database

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    build_database(db_path, files)
    typer.echo(f"Built DuckDB database: {db_path}")


@app.command()
def doctor(
    strict: Annotated[
        bool,
        typer.Option(help="Exit non-zero when required checks are missing."),
    ] = False,
    project_root: Annotated[
        Path | None,
        typer.Option(help="Override local state/output root."),
    ] = None,
) -> None:
    checks = run_checks(root=project_root)
    typer.echo("Environment Doctor")
    for check in checks:
        typer.echo(f"[{check.status.value.upper()}] {check.name}: {check.detail}")
    typer.echo("NEXT:")
    for step in next_steps(checks):
        typer.echo(f"- {step}")

    if strict and has_blocking_failures(checks):
        raise typer.Exit(1)


@app.command()
def run(
    task: Annotated[
        str,
        typer.Argument(help="Task id to run, or 'all' for the full report menu."),
    ] = "weekly_business_review",
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None,
        typer.Option(help="Override local state/output root."),
    ] = None,
) -> None:
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.html import render_html
    from xhs_ceramics_analytics.reporting.markdown import render_markdown

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    if task == "all":
        results = [run_task(task_id, db_path) for task_id in TASKS]
    else:
        results = [run_task(task, db_path)]
    output_dir = outputs_dir(project_root)
    markdown_out = output_dir / f"{task}.md"
    html_out = output_dir / f"{task}.html"
    errors_out = output_dir / "render_errors.txt"
    markdown_out.write_text(render_markdown(results), encoding="utf-8")
    typer.echo(f"Wrote report: {markdown_out}")
    if html_out.exists():
        html_out.unlink()
    try:
        html_out.write_text(render_html(results), encoding="utf-8")
    except Exception as exc:
        errors_out.write_text(
            f"HTML rendering failed for task {task}: {exc}\n",
            encoding="utf-8",
        )
        typer.echo(
            f"HTML rendering failed; kept Markdown report and wrote error: {errors_out}",
            err=True,
        )
        return
    typer.echo(f"Wrote report: {html_out}")
    if errors_out.exists():
        errors_out.unlink()


if __name__ == "__main__":
    app()
