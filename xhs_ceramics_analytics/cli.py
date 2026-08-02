import json as _json
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Annotated

import typer

from xhs_ceramics_analytics.doctor import has_blocking_failures, next_steps, run_checks
from xhs_ceramics_analytics.orchestration import narrative_workflow as _nw
from xhs_ceramics_analytics.paths import (
    run_output_dir,
    run_timestamp,
    state_dir,
)

app = typer.Typer(
    help=(
        "Xiaohongshu ceramics analytics local runner.\n\n"
        "CI tip: use `xhs-ca doctor --strict` as the CI-safe validation entry point "
        "(exits non-zero on blocking failures)."
    )
)

narrative_app = typer.Typer(help="Drive the file-based narrative workflow.")
app.add_typer(narrative_app, name="narrative")


def _write_json_atomic(path: Path, payload) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            _json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _write_sidecar_status(project_root, payload: dict) -> None:
    target_dir = state_dir(project_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "sidecar_status.json"
    temp_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_dir,
            prefix=".sidecar_status.json.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            _json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            temp_path = Path(handle.name)
        temp_path.replace(target)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def _invalidate_fact_sidecars(project_root, error: BaseException) -> None:
    target_dir = state_dir(project_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    for filename in ("facts.json", "results.json"):
        (target_dir / filename).unlink(missing_ok=True)
    _write_sidecar_status(
        project_root,
        {
            "status": "unavailable",
            "error": str(error),
        },
    )


def _build_and_publish_fact_sidecars(
    results,
    blocked_modules,
    project_root,
    block_reasons=None,
    *,
    factbook=None,
):
    """Build one FactBook and publish facts.json/results.json as one snapshot."""
    from xhs_ceramics_analytics.reporting.facts_export import (
        build_factbook,
        factbook_to_json,
    )
    from xhs_ceramics_analytics.reporting.narrative_results import build_narrative_results

    block_reasons = block_reasons or {}
    blocked = [{"slug": s, "reason": block_reasons.get(s, "")} for s in blocked_modules]
    factbook = factbook or build_factbook(results, blocked_modules=tuple(blocked_modules))
    facts_text = factbook_to_json(factbook)
    results_doc = build_narrative_results(
        results,
        blocked_modules=blocked,
        factbook=factbook,
    )
    facts_doc = _json.loads(facts_text)
    for field in ("canonical_version", "facts_hash", "registry_hash", "metric_mapping"):
        if results_doc.get(field) != facts_doc.get(field):
            raise ValueError(f"sidecar metric snapshot mismatch: {field}")

    results_text = _json.dumps(
        results_doc,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    target_dir = state_dir(project_root)
    target_dir.mkdir(parents=True, exist_ok=True)
    targets = tuple(target_dir / filename for filename in ("facts.json", "results.json"))
    temp_paths: list[Path] = []
    try:
        for filename, content in (
            ("facts.json", facts_text),
            ("results.json", results_text),
        ):
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=target_dir,
                prefix=f".{filename}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(content)
                temp_paths.append(Path(handle.name))
        _write_sidecar_status(
            project_root,
            {
                "status": "building",
                "facts_hash": facts_doc["facts_hash"],
                "registry_hash": facts_doc.get("registry_hash"),
            },
        )
        for temp_path, target in zip(temp_paths, targets):
            temp_path.replace(target)
        _write_sidecar_status(
            project_root,
            {
                "status": "ready",
                "facts_hash": facts_doc["facts_hash"],
                "registry_hash": facts_doc.get("registry_hash"),
            },
        )
        typer.echo(f"Wrote facts: {target_dir / 'facts.json'}")
        typer.echo(f"Wrote narrative results: {target_dir / 'results.json'}")
    finally:
        for temp_path in temp_paths:
            temp_path.unlink(missing_ok=True)
    return factbook


def _write_fact_sidecars(
    results,
    blocked_modules,
    project_root,
    block_reasons=None,
    *,
    factbook=None,
):
    """Build and publish one snapshot, invalidating the active pair on interruption."""
    try:
        return _build_and_publish_fact_sidecars(
            results,
            blocked_modules,
            project_root,
            block_reasons,
            factbook=factbook,
        )
    except BaseException as sidecar_error:
        _invalidate_fact_sidecars(project_root, sidecar_error)
        raise


@app.command()
def inspect(
    paths: Annotated[
        list[Path],
        typer.Argument(help="Files or directories to inspect without changing the sources."),
    ],
    out: Annotated[Path | None, typer.Option("--out")] = None,
    project_root: Annotated[Path | None, typer.Option("--project-root")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build a disposable database and report dates, store, dedupe, mappings and coverage."""
    from xhs_ceramics_analytics.importing.inspection import inspect_inputs

    try:
        payload = inspect_inputs(
            paths,
            overrides_path=state_dir(project_root) / "mapping_overrides.yaml",
        )
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    target = out or state_dir(project_root) / "inspection.json"
    _write_json_atomic(target, payload)
    if as_json:
        typer.echo(_json.dumps(payload, ensure_ascii=False))
    else:
        period = payload.get("report_period") or {}
        typer.echo(
            f"inspection: store={payload['store']['selected']} "
            f"period={period.get('start', '?')}..{period.get('end', '?')}"
        )
        typer.echo(f"Wrote inspection: {target}")


@app.command()
def build(
    files: Annotated[
        list[Path], typer.Argument(help="CSV/Excel files or directories to import.")
    ],
    db: Annotated[Path | None, typer.Option(help="Override DuckDB file path.")] = None,
    project_root: Annotated[
        Path | None,
        typer.Option(help="Override local state/output root."),
    ] = None,
) -> None:
    from xhs_ceramics_analytics.db.build import build_database
    from xhs_ceramics_analytics.importing.inspection import (
        input_fingerprint,
        optional_file_fingerprint,
        resolve_inputs,
        snapshot_inputs,
        summarize_database,
    )

    input_files = resolve_inputs(files)
    if not input_files:
        typer.echo("no input files found", err=True)
        raise typer.Exit(code=1)
    baseline_hash = input_fingerprint(input_files)
    overrides_path = state_dir(project_root) / "mapping_overrides.yaml"
    baseline_overrides_hash = optional_file_fingerprint(overrides_path)
    inspection_path = state_dir(project_root) / "inspection.json"
    if inspection_path.is_file():
        try:
            inspection = _json.loads(inspection_path.read_text(encoding="utf-8"))
        except (OSError, _json.JSONDecodeError) as exc:
            typer.echo(f"invalid inspection manifest: {inspection_path}: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        expected_hash = inspection.get("input_hash") if isinstance(inspection, dict) else None
        if inspection.get("provisional") is not True or not expected_hash:
            typer.echo(f"invalid inspection manifest: {inspection_path}", err=True)
            raise typer.Exit(code=1)
        if baseline_hash != expected_hash:
            typer.echo(
                "inputs changed since inspection; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        if inspection.get("mapping_overrides_hash") != baseline_overrides_hash:
            typer.echo(
                "mapping overrides changed since inspection; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
    db_path = db or state_dir(project_root) / "analytics.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".xhs-ca-build-", dir=db_path.parent) as temp_dir:
        temp_root = Path(temp_dir)
        snapshot_files = snapshot_inputs(input_files, temp_root / "inputs")
        if input_fingerprint(snapshot_files) != baseline_hash:
            typer.echo(
                "inputs changed during snapshot; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        snapshot_overrides = None
        if overrides_path.is_file():
            snapshot_overrides = snapshot_inputs(
                [overrides_path], temp_root / "configuration"
            )[0]
        if optional_file_fingerprint(snapshot_overrides) != baseline_overrides_hash:
            typer.echo(
                "mapping overrides changed during snapshot; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        staged_db = temp_root / db_path.name
        build_database(
            staged_db,
            snapshot_files,
            overrides_path=snapshot_overrides,
        )
        current_files = resolve_inputs(files)
        if current_files != input_files:
            typer.echo(
                "input set changed during build; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        if input_fingerprint(input_files) != baseline_hash:
            typer.echo(
                "inputs changed during build; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        current_overrides_hash = optional_file_fingerprint(overrides_path)
        if current_overrides_hash != baseline_overrides_hash:
            typer.echo(
                "mapping overrides changed during build; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        manifest = summarize_database(
            staged_db,
            snapshot_files,
            source_roots=files,
            overrides_path=snapshot_overrides,
            display_files=input_files,
            provisional=False,
        )
        if resolve_inputs(files) != input_files:
            typer.echo(
                "input set changed during build; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        if (
            manifest.get("input_hash") != baseline_hash
            or input_fingerprint(input_files) != baseline_hash
        ):
            typer.echo(
                "inputs changed during build; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        final_overrides_hash = optional_file_fingerprint(overrides_path)
        if (
            manifest.get("mapping_overrides_hash") != baseline_overrides_hash
            or final_overrides_hash != baseline_overrides_hash
        ):
            typer.echo(
                "mapping overrides changed during build; rerun xhs-ca inspect before build",
                err=True,
            )
            raise typer.Exit(code=1)
        staged_db.replace(db_path)
    manifest_path = state_dir(project_root) / "build_manifest.json"
    _write_json_atomic(manifest_path, manifest)
    typer.echo(f"Built DuckDB database: {db_path}")
    typer.echo(f"Wrote build manifest: {manifest_path}")


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
    # slug → why-blocked, harvested from the single coverage sweep in the auto path so
    # the narrative skeleton can explain what data unlocks each blocked module.
    block_reasons: dict[str, str] = {}
    if requested == ["all"]:
        task_ids = list(TASKS)
        basename = name or "all"
    elif requested == ["auto"]:
        from xhs_ceramics_analytics.analysis.coverage import assess_coverage

        coverage = assess_coverage(db_path)
        task_ids = [c.task_id for c in coverage if c.producible]
        block_reasons = {
            c.task_id: "；".join(c.reasons) for c in coverage if not c.producible
        }
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
    # Each production lands in its own timestamped folder so successive runs never
    # overwrite one another. The stamp is read here at the CLI boundary, not inside
    # rendering, so report bytes stay deterministic (it appears in the folder path only).
    output_dir = run_output_dir(basename, run_timestamp(), project_root)
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

    # facts.json is the cache-key + writer-handoff sidecar, NOT a deliverable — it lives in
    # the state dir beside analytics.duckdb / mapping_overrides.yaml / report_runs.jsonl, so
    # outputs/ stays a pure two-file (md+html) delivery surface. Its build must never abort an
    # already-written report. A failed build invalidates the active pair so a later narrative
    # run cannot accidentally consume a stale snapshot from an earlier report.
    blocked = tuple(t for t in TASKS if t not in task_ids)
    factbook = None
    try:
        factbook = _write_fact_sidecars(
            results,
            blocked,
            project_root,
            block_reasons,
        )
    except Exception as exc:
        _invalidate_fact_sidecars(project_root, exc)
        typer.echo(
            f"sidecar build failed; kept report and invalidated the active pair: {exc}",
            err=True,
        )
    if html_out.exists():
        html_out.unlink()
    try:
        html_out.write_text(
            render_html(
                results,
                title=report_title,
                assistant=assistant,
                factbook=factbook,
            ),
            encoding="utf-8",
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
    from xhs_ceramics_analytics.analysis.coverage import assess_coverage
    from xhs_ceramics_analytics.analysis.registry import TASKS, run_task
    from xhs_ceramics_analytics.reporting.facts_export import facts_hash

    db_path = db or state_dir(project_root) / "analytics.duckdb"
    requested = list(tasks) if tasks else ["auto"]
    # slug → why-blocked, harvested from the single coverage sweep in the auto path.
    block_reasons: dict[str, str] = {}
    if requested == ["auto"]:
        coverage = assess_coverage(db_path)
        task_ids = [c.task_id for c in coverage if c.producible]
        block_reasons = {
            c.task_id: "；".join(c.reasons) for c in coverage if not c.producible
        }
    elif requested == ["all"]:
        task_ids = list(TASKS)
    else:
        task_ids = [t for t in requested if t in TASKS]
    results = [run_task(task_id, db_path) for task_id in task_ids]
    blocked = tuple(t for t in TASKS if t not in task_ids)
    try:
        book = _write_fact_sidecars(
            results,
            blocked,
            project_root,
            block_reasons,
        )
    except Exception as exc:
        _invalidate_fact_sidecars(project_root, exc)
        raise
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
    results: Annotated[
        Path,
        typer.Option(
            "--results",
            help="results.json used to build the workflow-compatible cache key.",
        ),
    ],
    edits: Annotated[Path | None, typer.Option("--edits", help="continuity_edits.json (list).")]
    = None,
    out: Annotated[Path | None, typer.Option("--out", help="Where to write frozen_narrative.json.")]
    = None,
) -> None:
    """Draft → apply continuity edits → re-gate (must PASS) → freeze the narrative override."""
    import json as _json

    from xhs_ceramics_analytics.reporting.factcheck_gate import run_gate
    from xhs_ceramics_analytics.reporting.frozen_narrative import payload_hash, write_frozen
    from xhs_ceramics_analytics.reporting.narrative_render import (
        apply_continuity_edits,
        render_draft,
    )

    bundle_data = _json.loads(Path(bundle).read_text(encoding="utf-8"))
    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    results_data = _json.loads(Path(results).read_text(encoding="utf-8"))
    try:
        _nw._validate_sidecar_snapshot(results_data, facts_data)
    except ValueError as exc:
        typer.echo(f"sidecar snapshot rejected: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    result_tables = results_data.get("result_tables")
    if not isinstance(result_tables, dict):
        result_tables = (
            results_data.get("tables") if isinstance(results_data.get("tables"), dict) else {}
        )
    report = (
        run_gate(bundle_data, facts_data, result_tables)
        if result_tables
        else run_gate(bundle_data, facts_data)
    )
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
    write_frozen(
        target,
        facts_data.get("facts_hash", ""),
        drafted,
        results_hash=payload_hash(results_data),
        result_tables=result_tables,
    )
    typer.echo(f"Wrote frozen narrative: {target}")


@app.command(name="render-frozen")
def render_frozen_command(
    frozen: Annotated[Path, typer.Argument(help="frozen_narrative.json.")],
    facts: Annotated[Path, typer.Argument(help="facts.json.")],
    name: Annotated[Path | None, typer.Option("--name", "-n", help="Output basename (no suffix).")]
    = None,
) -> None:
    """Render exactly one final HTML artifact from a current cache."""
    import json as _json

    from xhs_ceramics_analytics.reporting.frozen_narrative import (
        is_cache_hit,
        load_frozen,
    )
    from xhs_ceramics_analytics.reporting.narrative_render import render_frozen

    facts_data = _json.loads(Path(facts).read_text(encoding="utf-8"))
    try:
        frozen_data = load_frozen(frozen)
    except ValueError as exc:
        typer.echo(f"render-frozen refused: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    if not is_cache_hit(
        frozen_data,
        facts_data.get("facts_hash", ""),
        results_hash=(frozen_data or {}).get("results_hash", ""),
        result_tables=(frozen_data or {}).get("result_tables"),
    ):
        typer.echo("render-frozen refused: stale or incompatible cache", err=True)
        raise typer.Exit(code=1)
    # An explicit --name is an operator-chosen path base (dev tool), used verbatim; the
    # default lands in a timestamped production folder like every other deliverable.
    base = name or (run_output_dir("经营诊断报告", run_timestamp(), None) / "经营诊断报告")
    title = Path(base).name.replace("_", " ").strip()
    try:
        _markdown, html = render_frozen(frozen_data, facts_data, title=title)
    except ValueError as exc:
        typer.echo(f"render-frozen refused: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    Path(f"{base}.html").write_text(html, encoding="utf-8")
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
    output_dir = run_output_dir(basename, run_timestamp(), project_root)
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


def _validate_active_sidecar_status(
    results_path: Path,
    facts_path: Path,
    results_doc: dict,
    facts_doc: dict,
) -> None:
    results_parent = results_path.resolve().parent
    facts_parent = facts_path.resolve().parent
    if results_parent != facts_parent:
        raise typer.BadParameter(
            "results.json and facts.json must come from the same directory"
        )
    status_path = facts_parent / "sidecar_status.json"
    if not status_path.exists():
        raise typer.BadParameter(
            f"sidecar_status.json is required for this sidecar pair: {status_path}"
        )
    status = _read_json_input(status_path, "sidecar_status.json")
    if status.get("status") != "ready":
        raise typer.BadParameter(
            "sidecar_status.json is not ready: "
            f"{status.get('status', 'unknown')}"
        )
    expected_hash = status.get("facts_hash")
    if not expected_hash or any(
        document.get("facts_hash") != expected_hash
        for document in (facts_doc, results_doc)
    ):
        raise typer.BadParameter(
            "sidecar_status.json facts_hash does not match facts.json/results.json"
        )


@narrative_app.command("prepare")
def narrative_prepare(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    results: Annotated[Path, typer.Option("--results")],
    facts: Annotated[Path, typer.Option("--facts")],
    name: Annotated[str, typer.Option("--name")],
    project_root: Annotated[Path | None, typer.Option("--project-root")] = None,
    force: Annotated[bool, typer.Option("--force")] = False,
    multi_agent_authorized: Annotated[
        bool,
        typer.Option(
            "--multi-agent-authorized",
            help="Confirm the user explicitly authorized the quality multi-agent workflow.",
        ),
    ] = False,
    multi_agent_declined: Annotated[
        bool,
        typer.Option(
            "--multi-agent-declined",
            help="Confirm the user explicitly declined the quality multi-agent workflow.",
        ),
    ] = False,
    multi_agent_unavailable: Annotated[
        bool,
        typer.Option(
            "--multi-agent-unavailable",
            help="Confirm this host has no sub-agent facility and use deterministic-only delivery.",
        ),
    ] = False,
) -> None:
    """Initialize a run directory from results.json + facts.json."""
    results_doc = _read_json_input(results, "results")
    facts_doc = _read_json_input(facts, "facts")
    _validate_active_sidecar_status(results, facts, results_doc, facts_doc)
    try:
        state = _nw.prepare_run(
            run_dir, results=results_doc, facts_json=facts_doc,
            report_name=name, project_root=project_root, force=force,
            multi_agent_authorized=multi_agent_authorized,
            multi_agent_declined=multi_agent_declined,
            multi_agent_unavailable=multi_agent_unavailable,
        )
    except (FileExistsError, ValueError) as exc:
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


@narrative_app.command("validate")
def narrative_validate(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    stage: Annotated[str, typer.Option("--stage")],
    source: Annotated[Path, typer.Option("--source")],
    section_id: Annotated[str | None, typer.Option("--section-id")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id")] = None,
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a task result against its static and run-scoped contract."""
    if not source.exists():
        raise typer.BadParameter(f"source file not found: {source}")
    try:
        payload = _nw.validate_output(
            run_dir,
            stage=stage,
            source=source,
            section_id=section_id,
            task_id=task_id,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(_json.dumps(payload, ensure_ascii=False))
    else:
        typer.echo(f"valid: task_id={payload.get('task_id')}")


@narrative_app.command("reserve")
def narrative_reserve(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    capacity: Annotated[int, typer.Option("--capacity")],
    as_json: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Reserve the next tasks that fit within the host's concurrency capacity."""
    try:
        tasks = _nw.reserve_tasks(run_dir, capacity=capacity)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    if as_json:
        typer.echo(_json.dumps(tasks, ensure_ascii=False))
    else:
        typer.echo(f"reserved: {len(tasks)} task(s)")


@narrative_app.command("record-dispatch")
def narrative_record_dispatch(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    task_id: Annotated[str, typer.Option("--task-id")],
    agent_id: Annotated[str, typer.Option("--agent-id")],
    result_path: Annotated[Path, typer.Option("--result-path")],
) -> None:
    """Persist the agent and result path assigned to one reserved task."""
    try:
        task = _nw.record_dispatch(
            run_dir,
            task_id=task_id,
            agent_id=agent_id,
            result_path=result_path,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_json.dumps(task, ensure_ascii=False))


@narrative_app.command("record-agent-state")
def narrative_record_agent_state(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    task_id: Annotated[str, typer.Option("--task-id")],
    status: Annotated[str, typer.Option("--status")],
    error: Annotated[str | None, typer.Option("--error")] = None,
) -> None:
    """Record result-ready, failed, or closed for a dispatched task."""
    try:
        task = _nw.record_agent_state(
            run_dir,
            task_id=task_id,
            status=status,
            error=error,
        )
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_json.dumps(task, ensure_ascii=False))


@narrative_app.command("release")
def narrative_release(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    task_id: Annotated[str, typer.Option("--task-id")],
) -> None:
    """Release an unassigned reservation after a partial dispatch failure."""
    try:
        task = _nw.release_task(run_dir, task_id=task_id)
    except (ValueError, FileNotFoundError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(_json.dumps(task, ensure_ascii=False))


@narrative_app.command("ingest")
def narrative_ingest(
    run_dir: Annotated[Path, typer.Option("--run-dir")],
    stage: Annotated[str, typer.Option("--stage")],
    source: Annotated[Path | None, typer.Option("--source")] = None,
    section_id: Annotated[str | None, typer.Option("--section-id")] = None,
    task_id: Annotated[str | None, typer.Option("--task-id")] = None,
) -> None:
    """Ingest a sub-agent's JSON output for the given stage."""
    if source is not None and not source.exists():
        raise typer.BadParameter(f"source file not found: {source}")
    try:
        state = _nw.ingest_output(
            run_dir,
            stage=stage,
            source=source,
            section_id=section_id,
            task_id=task_id,
        )
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
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
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
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"stage={state['stage']} reason={state['degradation_reason']}")


if __name__ == "__main__":
    app()
