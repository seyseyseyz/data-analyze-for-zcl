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

    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook as _build_factbook,
        factbook_to_json as _factbook_to_json,
    )

    # facts.json is the cache-key + writer-handoff sidecar, NOT a deliverable — it lives in
    # the state dir beside analytics.duckdb / mapping_overrides.yaml / report_runs.jsonl, so
    # outputs/ stays a pure two-file (md+html) delivery surface. Its build must never abort an
    # already-written report: like the HTML path below, a sidecar failure degrades to a warning.
    blocked = tuple(t for t in TASKS if t not in task_ids)
    facts_out = state_dir(project_root) / "facts.json"
    try:
        facts_out.write_text(
            _factbook_to_json(_build_factbook(results, blocked_modules=blocked)), encoding="utf-8"
        )
        typer.echo(f"Wrote facts: {facts_out}")
    except Exception as exc:
        typer.echo(
            f"facts.json build failed; kept report and skipped the sidecar: {exc}",
            err=True,
        )
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
def facts(
    tasks: Annotated[
        list[str] | None,
        typer.Argument(help="Task ids, or 'auto' for the producible set. Emits facts.json."),
    ] = None,
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None, typer.Option(help="Override local state/output root.")
    ] = None,
) -> None:
    """Build the deterministic FactBook and write facts.json into the state dir (0 agents)."""
    from xhs_ceramics_analytics.analysis.coverage import producible_task_ids
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook,
        facts_hash,
        factbook_to_json,
    )

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    requested = list(tasks) if tasks else ["auto"]
    if requested == ["auto"]:
        task_ids = list(producible_task_ids(db_path))
    elif requested == ["all"]:
        task_ids = list(TASKS)
    else:
        task_ids = [t for t in requested if t in TASKS]
    results = [run_task(task_id, db_path) for task_id in task_ids]
    blocked = tuple(t for t in TASKS if t not in task_ids)
    book = build_factbook(results, blocked_modules=blocked)
    out = state_dir(project_root) / "facts.json"
    out.write_text(factbook_to_json(book), encoding="utf-8")
    typer.echo(f"Wrote facts: {out}")
    typer.echo(f"facts_hash: {facts_hash(book)}")


@app.command()
def gate(
    bundle: Annotated[Path, typer.Argument(help="narrative_bundle.json to validate.")],
    facts: Annotated[Path, typer.Argument(help="facts.json from `xhs-ca facts`.")],
    out: Annotated[Path | None, typer.Option("--out", help="Where to write gate_report.json.")]
    = None,
) -> None:
    """Validate a narrative_bundle against the FactBook. Exits 1 on any HARD failure."""
    import json as _json

    from xhs_ceramics_analytics.reporting.factcheck_gate import gate_report_to_json, run_gate

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    report = run_gate(bundle_data, facts_data)
    report_json = gate_report_to_json(report)
    if out is not None:
        Path(out).write_text(report_json, encoding="utf-8")
        typer.echo(f"Wrote gate report: {out}")
    typer.echo(f"gate: {report.status} "
               f"({len(report.hard_failures)} hard, {len(report.warnings)} warn)")
    if report.status != "PASS":
        for failure in report.hard_failures:
            typer.echo(f"  HARD {failure['code']}: {failure['detail']}", err=True)
        raise typer.Exit(code=1)


@app.command(name="render-draft")
def render_draft_command(
    bundle: Annotated[Path, typer.Argument(help="narrative_bundle.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    out: Annotated[Path | None, typer.Option("--out", help="Where to write the draft markdown.")]
    = None,
) -> None:
    """Fill {tN} tokens from fact.rendered and write a draft markdown (no numbers invented)."""
    import json as _json

    from xhs_ceramics_analytics.reporting.narrative_render import (
        bundle_to_markdown,
        render_draft,
    )

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    drafted = render_draft(bundle_data, facts_data)
    md = bundle_to_markdown(drafted, facts_data)
    target = out or (state_dir(None) / "draft.md")
    Path(target).write_text(md, encoding="utf-8")
    typer.echo(f"Wrote draft: {target}")


@app.command()
def finalize(
    bundle: Annotated[Path, typer.Argument(help="narrative_bundle.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    edits: Annotated[Path | None, typer.Option("--edits", help="continuity_edits.json (list).")]
    = None,
    out: Annotated[Path | None, typer.Option("--out", help="Where to write frozen_narrative.json.")]
    = None,
) -> None:
    """Draft → apply continuity edits → re-gate (must PASS) → freeze the narrative override."""
    import json as _json

    from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
    from xhs_ceramics_analytics.reporting.frozen_narrative import write_frozen
    from xhs_ceramics_analytics.reporting.narrative_render import (
        apply_continuity_edits,
        render_draft,
    )

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    report = run_gate(bundle_data, facts_data)
    if report.status != "PASS":
        typer.echo(f"gate FAIL — cannot finalize: {report.hard_failures}", err=True)
        raise typer.Exit(code=1)
    drafted = render_draft(report.bundle, facts_data)
    if edits is not None:
        edit_list = _json.loads(Path(edits).read_text(encoding="utf-8"))
        try:
            drafted = apply_continuity_edits(drafted, edit_list)
        except ValueError as exc:
            typer.echo(f"continuity edit rejected: {exc}", err=True)
            raise typer.Exit(code=1) from exc
    target = out or (state_dir(None) / "frozen_narrative.json")
    write_frozen(target, facts_data.get("facts_hash", ""), drafted)
    typer.echo(f"Wrote frozen narrative: {target}")


@app.command(name="render-frozen")
def render_frozen_command(
    frozen: Annotated[Path, typer.Argument(help="frozen_narrative.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    name: Annotated[Path | None, typer.Option("--name", "-n", help="Output basename (no suffix).")]
    = None,
) -> None:
    """Render md+html from a frozen narrative; re-gates and checks facts_hash (tamper evidence)."""
    import json as _json

    from xhs_ceramics_analytics.reporting.narrative_render import render_frozen

    frozen_data = _json.loads(Path(frozen).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    try:
        md, html = render_frozen(frozen_data, facts_data)
    except ValueError as exc:
        typer.echo(f"render-frozen refused: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    base = name or (outputs_dir(None) / "经营诊断报告")
    Path(f"{base}.md").write_text(md, encoding="utf-8")
    Path(f"{base}.html").write_text(html, encoding="utf-8")
    typer.echo(f"Wrote report: {base}.md")
    typer.echo(f"Wrote report: {base}.html")

    from xhs_ceramics_analytics.reporting.report_telemetry import (
        append_run_record,
        build_run_record,
    )

    record = build_run_record(
        mode="frozen", facts_hash=facts_data.get("facts_hash", ""), cache_hit=True,
    )
    try:
        append_run_record(state_dir(None) / "report_runs.jsonl", record)
    except Exception:
        pass  # telemetry is best-effort; never break the report


@app.command()
def skeleton(
    tasks: Annotated[list[str] | None, typer.Argument(help="Task ids or 'auto'.")] = None,
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[Path | None, typer.Option(help="Override state/output root.")] = None,
    name: Annotated[str | None, typer.Option("--name", "-n", help="Output basename.")] = None,
) -> None:
    """Deterministic 0-agent skeleton report (facts + tables + charts + tags), md+html."""
    from xhs_ceramics_analytics.analysis.coverage import producible_task_ids
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.html import render_markdown_document_html
    from xhs_ceramics_analytics.reporting.narrative_render import skeleton_markdown

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    requested = list(tasks) if tasks else ["auto"]
    if requested == ["auto"]:
        task_ids = list(producible_task_ids(db_path))
    elif requested == ["all"]:
        task_ids = list(TASKS)
    else:
        task_ids = [t for t in requested if t in TASKS]
    results = [run_task(task_id, db_path) for task_id in task_ids]
    basename = name or "经营诊断报告"
    report_title = basename.replace("_", " ").strip()
    md = skeleton_markdown(results, title=report_title)
    output_dir = outputs_dir(project_root)
    (output_dir / f"{basename}.md").write_text(md, encoding="utf-8")
    (output_dir / f"{basename}.html").write_text(
        render_markdown_document_html(md, title=report_title), encoding="utf-8"
    )
    typer.echo(f"Wrote skeleton report: {output_dir / f'{basename}.md'}")
    typer.echo(f"Wrote skeleton report: {output_dir / f'{basename}.html'}")

    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook as _build_factbook,
        facts_hash as _facts_hash,
    )
    from xhs_ceramics_analytics.reporting.report_telemetry import (
        append_run_record,
        build_run_record,
    )

    book = _build_factbook(results, blocked_modules=tuple(t for t in TASKS if t not in task_ids))
    record = build_run_record(
        mode="skeleton", facts_hash=_facts_hash(book), cache_hit=False,
        degradation_reason="skeleton_cli",
    )
    try:
        append_run_record(state_dir(project_root) / "report_runs.jsonl", record)
    except Exception:
        pass  # telemetry is best-effort; never break the report


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
