from pathlib import Path
from typing import Annotated

import typer

from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
from xhs_ceramics_analytics.db.build import build_database
from xhs_ceramics_analytics.paths import outputs_dir, state_dir
from xhs_ceramics_analytics.reporting.markdown import render_markdown

app = typer.Typer(help="Xiaohongshu ceramics analytics local runner.")


@app.command()
def build(
    files: Annotated[list[Path], typer.Argument(help="CSV files to import.")],
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
) -> None:
    db_path = db or state_dir() / "analytics.duckdb"
    build_database(db_path, files)
    typer.echo(f"Built DuckDB database: {db_path}")


@app.command()
def run(
    task: Annotated[
        str,
        typer.Argument(help="Task id to run, or 'all' for the full report menu."),
    ] = "weekly_business_review",
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
) -> None:
    db_path = db or state_dir() / "analytics.duckdb"
    if task == "all":
        results = [run_task(task_id, db_path) for task_id in TASKS]
    else:
        results = [run_task(task, db_path)]
    out = outputs_dir() / f"{task}.md"
    out.write_text(render_markdown(results), encoding="utf-8")
    typer.echo(f"Wrote report: {out}")


if __name__ == "__main__":
    app()
