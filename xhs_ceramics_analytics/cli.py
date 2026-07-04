from pathlib import Path
from typing import Annotated

import typer

from xhs_ceramics_analytics.doctor import has_blocking_failures, next_steps, run_checks
from xhs_ceramics_analytics.paths import outputs_dir, state_dir

app = typer.Typer(
    help=(
        "Xiaohongshu ceramics analytics local runner.\n\n"
        "CI tip: use `xhs-ca doctor --strict` as the CI-safe validation entry point "
        "(exits non-zero on blocking failures)."
    )
)


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


@app.command("render-html")
def render_html_command(
    markdown_file: Annotated[
        Path,
        typer.Argument(help="Markdown report to convert into a single-file HTML report."),
    ],
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output HTML path. Defaults to <report>.html."),
    ] = None,
    title: Annotated[
        str | None,
        typer.Option(help="Override the report title. Defaults to the first H1."),
    ] = None,
) -> None:
    from xhs_ceramics_analytics.reporting.html import render_markdown_document_html

    html_out = output or markdown_file.with_suffix(".html")
    html_out.parent.mkdir(parents=True, exist_ok=True)
    if html_out.exists():
        html_out.unlink()
    markdown_text = markdown_file.read_text(encoding="utf-8")
    html_out.write_text(
        render_markdown_document_html(markdown_text, title=title),
        encoding="utf-8",
    )
    typer.echo(f"Wrote report: {html_out}")


@app.command()
def run(
    tasks: Annotated[
        list[str] | None,
        typer.Argument(
            help=(
                "One or more task ids, 'auto' for every task the data can actually "
                "produce, or 'all' for the full menu. Passing several ids composes "
                "ONE integrated report instead of a file per task."
            )
        ),
    ] = None,
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None,
        typer.Option(help="Override local state/output root."),
    ] = None,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            "-n",
            help=(
                "Output basename for the report. Defaults to the single slug, "
                "or '经营诊断报告' when several modules are combined."
            ),
        ),
    ] = None,
    assistant: Annotated[
        str | None,
        typer.Option(
            "--assistant",
            help=(
                "Name shown in the '追问' section for follow-up analysis. "
                "Defaults to a neutral '分析助手'."
            ),
        ),
    ] = None,
) -> None:
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.html import render_html
    from xhs_ceramics_analytics.reporting.markdown import render_markdown

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    requested = list(tasks) if tasks else ["weekly_business_review"]
    if requested == ["all"]:
        task_ids = list(TASKS)
        basename = name or "all"
    elif requested == ["auto"]:
        from xhs_ceramics_analytics.analysis.coverage import producible_task_ids

        task_ids = producible_task_ids(db_path)
        if not task_ids:
            raise typer.BadParameter(
                "no task is producible on this database — run `xhs-ca coverage` to see why."
            )
        basename = name or "经营诊断报告"
        typer.echo(f"auto-selected {len(task_ids)} producible task(s): {', '.join(task_ids)}")
    else:
        unknown = [task_id for task_id in requested if task_id not in TASKS]
        if unknown:
            raise typer.BadParameter(f"unknown task(s): {', '.join(unknown)}")
        task_ids = requested
        basename = name or (requested[0] if len(requested) == 1 else "经营诊断报告")

    results = [run_task(task_id, db_path) for task_id in task_ids]
    output_dir = outputs_dir(project_root)
    markdown_out = output_dir / f"{basename}.md"
    html_out = output_dir / f"{basename}.html"
    errors_out = output_dir / "render_errors.txt"
    # ``name`` doubles as the file basename (kept filesystem-friendly with
    # underscores) and the on-page report title. Underscores read as broken in a
    # Chinese headline, so present them as spaces in the display title while the
    # file on disk still uses the raw ``name``.
    report_title = name.replace("_", " ").strip() if name else None
    markdown_out.write_text(render_markdown(results, title=report_title), encoding="utf-8")
    typer.echo(f"Wrote report: {markdown_out}")
    if html_out.exists():
        html_out.unlink()
    try:
        html_out.write_text(
            render_html(results, title=report_title, assistant=assistant), encoding="utf-8"
        )
    except Exception as exc:
        errors_out.write_text(
            f"HTML rendering failed for report {basename}: {exc}\n",
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


@app.command()
def coverage(
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None,
        typer.Option(help="Override local state/output root."),
    ] = None,
) -> None:
    """Report which tasks the built database can actually produce vs what is blocked."""
    from xhs_ceramics_analytics.analysis.coverage import assess_coverage

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    rows = assess_coverage(db_path)
    producible = [row for row in rows if row.producible]
    blocked = [row for row in rows if not row.producible]

    typer.echo(f"能产出 ({len(producible)}):")
    for row in producible:
        strengths = ", ".join(f"{k}×{v}" for k, v in row.strengths.items())
        typer.echo(f"  [OK] {row.task_id} ({strengths})")
    typer.echo(f"\n被阻断 ({len(blocked)}) — 附解锁所需数据:")
    for row in blocked:
        reason = row.reasons[0] if row.reasons else "降级/不可诊断"
        typer.echo(f"  [--] {row.task_id}: {reason}")

    if producible:
        slugs = " ".join(row.task_id for row in producible)
        typer.echo(f"\n建议：xhs-ca run {slugs} --name <表意名称>")
        typer.echo("或直接：xhs-ca run auto --name <表意名称>")


if __name__ == "__main__":
    app()
