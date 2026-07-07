import json as _json
from pathlib import Path
from typing import Annotated

import typer

from xhs_ceramics_analytics.doctor import has_blocking_failures, next_steps, run_checks
from xhs_ceramics_analytics.orchestration import narrative_workflow as _nw
from xhs_ceramics_analytics.paths import outputs_dir, state_dir

app = typer.Typer(
    help=(
        "Xiaohongshu ceramics analytics local runner.\n\n"
        "CI tip: use `xhs-ca doctor --strict` as the CI-safe validation entry point "
        "(exits non-zero on blocking failures)."
    )
)

narrative_app = typer.Typer(help="Drive the file-based narrative workflow.")
app.add_typer(narrative_app, name="narrative")


def _write_narrative_results(results, blocked_modules, project_root) -> None:
    """Emit results.json (the narrative `--results` input) beside facts.json.

    Like the facts.json / HTML paths, this is a sidecar: a failure here must never
    abort an already-produced fact layer — it degrades to a warning. results.json is
    the domain-sliced document `xhs-ca narrative prepare --results` consumes; facts.json
    cannot serve that role (its ``domain_slices`` is an always-empty cache dict).
    """
    from xhs_ceramics_analytics.reporting.narrative_results import build_narrative_results

    out = state_dir(project_root) / "results.json"
    try:
        out.write_text(
            _json.dumps(
                build_narrative_results(results, blocked_modules=blocked_modules),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        typer.echo(f"Wrote narrative results: {out}")
    except Exception as exc:
        typer.echo(
            f"results.json build failed; kept the fact layer and skipped the narrative sidecar: {exc}",
            err=True,
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
    _write_narrative_results(results, blocked, project_root)
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
    _write_narrative_results(results, blocked, project_root)
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


def _read_json_input(path: Path, label: str) -> dict:
    if not path.exists():
        raise typer.BadParameter(f"{label} file not found: {path}")
    try:
        return _json.loads(path.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as exc:
        raise typer.BadParameter(f"{label} file is not valid JSON: {exc}") from exc


@narrative_app.command("prepare")
def narrative_prepare(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    results: Annotated[Path, typer.Option("--results")],
    facts: Annotated[Path, typer.Option("--facts")],
    name: Annotated[str, typer.Option("--name")],
    project_root: Annotated[Path | None, typer.Option("--project-root")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
) -> None:
    """Initialize a run directory from results.json + facts.json."""
    results_doc = _read_json_input(results, "results")
    facts_doc = _read_json_input(facts, "facts")
    try:
        state = _nw.prepare_run(
            run_dir, results=results_doc, facts_json=facts_doc,
            report_name=name, project_root=project_root, force=force,
        )
    except FileExistsError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"prepared: stage={state['stage']} merged={state['merged_sections']}")


@narrative_app.command("status")
def narrative_status(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Show the current stage and next action for a run."""
    try:
        payload = _nw.status_json(run_dir)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(_json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"stage={payload['stage']}  next={payload['next_action']}")


@narrative_app.command("ingest")
def narrative_ingest(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    stage: Annotated[str, typer.Option("--stage")],
    source: Annotated[Path | None, typer.Option("--source")] = None,
    section_id: Annotated[str | None, typer.Option("--section-id")] = None,
) -> None:
    """Ingest a sub-agent's JSON output for the given stage."""
    if source is not None and not source.exists():
        raise typer.BadParameter(f"source file not found: {source}")
    try:
        state = _nw.ingest_output(run_dir, stage=stage, source=source, section_id=section_id)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"ingested {stage}: {len(state['sections'])} section(s) recorded")


@narrative_app.command("advance")
def narrative_advance(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    project_root: Annotated[Path | None, typer.Option("--project-root")] = None,
) -> None:
    """Advance the run one step through the stage machine."""
    try:
        state = _nw.advance_run(run_dir, project_root=project_root)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stage={state['stage']}")


@narrative_app.command("finalize-deterministic")
def narrative_finalize_deterministic(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    reason: Annotated[str, typer.Option("--reason")],
    project_root: Annotated[Path | None, typer.Option("--project-root")] = None,
) -> None:
    """Deliver the deterministic skeleton fallback report and mark the run blocked."""
    try:
        state = _nw.finalize_deterministic(run_dir, project_root=project_root, reason=reason)
    except FileNotFoundError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stage={state['stage']} reason={state['degradation_reason']}")


if __name__ == "__main__":
    app()
