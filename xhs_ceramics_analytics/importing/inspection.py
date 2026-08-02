from __future__ import annotations

import hashlib
import re
import shutil
import tempfile
from collections import Counter, defaultdict, deque
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from xhs_ceramics_analytics.analysis.coverage import assess_coverage
from xhs_ceramics_analytics.db.build import build_database
from xhs_ceramics_analytics.db.duck import connect

_DATE_SOURCES = (
    ("business_overview_daily", "date"),
    ("orders", "paid_time"),
    ("search_overview", "date"),
    ("shop_page_funnel", "date"),
    ("shop_page_source", "date"),
    ("notes", "publish_time"),
    ("refund_overview", "stat_period"),
)
_SUMMARY_NAMES = {"全部", "all", "汇总", "总计", "unknown", "未知"}
_MONTH_RANGE_RE = re.compile(r"(?P<start>\d{1,2})\s*[-~至—]\s*(?P<end>\d{1,2})\s*月")


def resolve_inputs(paths: list[Path]) -> list[Path]:
    resolved: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if path.is_file():
            resolved.append(path)
            continue
        if not path.is_dir():
            raise FileNotFoundError(f"input path not found: {path}")
        resolved.extend(
            candidate
            for candidate in path.rglob("*")
            if candidate.is_file()
            and ".xhs-ceramics-analytics" not in candidate.parts
            and not any(part.startswith(".") for part in candidate.relative_to(path).parts)
        )
    return sorted(set(resolved), key=lambda path: str(path))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _input_hash(files: list[Path], hashes: dict[Path, str]) -> str:
    return hashlib.sha256(
        "\n".join(
            f"{path.name}\0{hashes[path]}"
            for path in sorted(files, key=lambda candidate: str(candidate))
        ).encode("utf-8")
    ).hexdigest()


def input_fingerprint(files: list[Path]) -> str:
    resolved = [Path(path).resolve() for path in files]
    return _input_hash(resolved, {path: _sha256(path) for path in resolved})


def optional_file_fingerprint(path: Path | None) -> str | None:
    if path is None:
        return None
    path = Path(path)
    return _sha256(path) if path.is_file() else None


def snapshot_inputs(files: list[Path], snapshot_root: Path) -> list[Path]:
    """Copy resolved inputs to unique immutable paths while preserving basenames."""
    snapshot_root = Path(snapshot_root)
    snapshots: list[Path] = []
    for index, source in enumerate(files):
        target = snapshot_root / f"{index:06d}" / Path(source).name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        snapshots.append(target)
    return snapshots


def _existing_tables(con) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _columns(con, table_name: str) -> set[str]:
    return {
        row[1]
        for row in con.execute(
            f"PRAGMA table_info('{table_name.replace(chr(39), chr(39) * 2)}')"
        ).fetchall()
    }


def _records(con, query: str, params=None) -> list[dict]:
    frame = con.execute(query, params or []).fetchdf()
    return frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")


def _parse_date_value(value) -> tuple[date | None, date | None]:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None, None
    if isinstance(value, pd.Timestamp):
        parsed = value.date()
        return parsed, parsed
    if isinstance(value, datetime):
        parsed = value.date()
        return parsed, parsed
    if isinstance(value, date):
        return value, value
    text = str(value).strip()
    if not text:
        return None, None
    parts = re.split(r"\s*[~至]\s*", text, maxsplit=1)
    parsed_parts = [_parse_single_date(part) for part in parts]
    if len(parsed_parts) == 2 and all(parsed_parts):
        return parsed_parts[0], parsed_parts[1]
    parsed = _parse_single_date(text)
    return parsed, parsed


def _parse_single_date(value: str) -> date | None:
    text = str(value).strip()
    digits = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if digits:
        try:
            return date(*(int(part) for part in digits.groups()))
        except ValueError:
            return None
    match = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        try:
            return date(*(int(part) for part in match.groups()))
        except ValueError:
            return None
    return None


def _date_ranges(con, tables: set[str]) -> list[dict]:
    ranges: list[dict] = []
    for table_name, field in _DATE_SOURCES:
        if table_name not in tables or field not in _columns(con, table_name):
            continue
        escaped_table = table_name.replace('"', '""')
        escaped_field = field.replace('"', '""')
        values = con.execute(
            f'SELECT "{escaped_field}" FROM "{escaped_table}" '
            f'WHERE "{escaped_field}" IS NOT NULL'
        ).fetchall()
        starts: list[date] = []
        ends: list[date] = []
        for (value,) in values:
            start, end = _parse_date_value(value)
            if start is not None:
                starts.append(start)
            if end is not None:
                ends.append(end)
        if starts and ends:
            ranges.append(
                {
                    "table_name": table_name,
                    "field": field,
                    "start": min(starts).isoformat(),
                    "end": max(ends).isoformat(),
                }
            )
    return ranges


def _store_summary(con, tables: set[str]) -> dict:
    sources = (
        ("traffic_source", "account_name", 1),
        ("notes", "作者昵称", 2),
        ("notes", "author_nickname", 2),
        ("refund_overview", "account_name", 3),
    )
    candidates: list[dict] = []
    for table_name, field, priority in sources:
        if table_name not in tables or field not in _columns(con, table_name):
            continue
        escaped_table = table_name.replace('"', '""')
        escaped_field = field.replace('"', '""')
        rows = con.execute(
            f'SELECT CAST("{escaped_field}" AS VARCHAR), COUNT(*) '
            f'FROM "{escaped_table}" WHERE "{escaped_field}" IS NOT NULL '
            f'GROUP BY 1 ORDER BY 2 DESC, 1'
        ).fetchall()
        for value, count in rows:
            name = str(value).strip()
            if not name or name.casefold() in _SUMMARY_NAMES:
                continue
            candidates.append(
                {
                    "name": name,
                    "source_table": table_name,
                    "source_field": field,
                    "count": int(count),
                    "priority": priority,
                }
            )
    candidates.sort(key=lambda item: (item["priority"], -item["count"], item["name"]))
    return {
        "selected": candidates[0]["name"] if candidates else "店铺",
        "candidates": candidates,
        "used_neutral_fallback": not candidates,
    }


def summarize_database(
    db_path: Path,
    files: list[Path],
    *,
    source_roots: list[Path] | None = None,
    overrides_path: Path | None = None,
    display_files: list[Path] | None = None,
    provisional: bool,
) -> dict:
    files = [Path(path).resolve() for path in files]
    display_files = (
        [Path(path).resolve() for path in display_files]
        if display_files is not None
        else files
    )
    if len(display_files) != len(files):
        raise ValueError("display_files must align one-to-one with files")
    hashes = {path: _sha256(path) for path in files}
    hash_groups: dict[str, list[Path]] = defaultdict(list)
    for path, display_path in zip(files, display_files, strict=True):
        hash_groups[hashes[path]].append(display_path)
    duplicate_file_groups = [
        {"sha256": digest, "files": [str(path) for path in sorted(paths)]}
        for digest, paths in sorted(hash_groups.items())
        if len(paths) > 1
    ]

    con = connect(db_path)
    try:
        tables = _existing_tables(con)
        manifest_rows = (
            _records(
                con,
                "SELECT table_name, file, row_count, sha256 FROM build_manifest",
            )
            if "build_manifest" in tables
            else []
        )
        manifest_by_identity: dict[tuple[str, str], deque[dict]] = defaultdict(deque)
        for row in manifest_rows:
            manifest_by_identity[(str(row["file"]), str(row["sha256"]))].append(row)
        file_entries = []
        for path, display_path in zip(files, display_files, strict=True):
            matching_rows = manifest_by_identity.get((path.name, hashes[path]))
            contributions = [matching_rows.popleft()] if matching_rows else []
            file_entries.append(
                {
                    "path": str(display_path),
                    "name": display_path.name,
                    "sha256": hashes[path],
                    "size_bytes": path.stat().st_size,
                    "tables": sorted(
                        {str(row["table_name"]) for row in contributions}
                    ),
                    "input_rows": sum(int(row["row_count"]) for row in contributions),
                }
            )

        conflicts = Counter()
        if "data_quality" in tables:
            conflicts.update(
                {
                    str(table): int(count)
                    for table, count in con.execute(
                        "SELECT table_name, COUNT(*) FROM data_quality GROUP BY 1"
                    ).fetchall()
                }
            )
        statistics = {
            str(row["table_name"]): row
            for row in (
                _records(con, "SELECT * FROM build_statistics")
                if "build_statistics" in tables
                else []
            )
        }
        table_summaries = []
        for table_name in sorted({str(row["table_name"]) for row in manifest_rows}):
            input_rows = sum(
                int(row["row_count"])
                for row in manifest_rows
                if str(row["table_name"]) == table_name
            )
            escaped_table = table_name.replace('"', '""')
            accepted_rows = int(
                con.execute(f'SELECT COUNT(*) FROM "{escaped_table}"').fetchone()[0]
            )
            table_statistics = statistics.get(table_name) or {}
            duplicate_rows = int(
                table_statistics.get(
                    "exact_duplicate_rows", max(input_rows - accepted_rows, 0)
                )
            )
            merged_rows = int(table_statistics.get("merged_rows", 0))
            table_summaries.append(
                {
                    "table_name": table_name,
                    "input_rows": input_rows,
                    "accepted_rows": accepted_rows,
                    "duplicate_rows": duplicate_rows,
                    "merged_rows": merged_rows,
                    "conflict_count": conflicts[table_name],
                }
            )

        ranges = _date_ranges(con, tables)
        report_period = None
        if ranges:
            primary = ranges[0]
            report_period = {
                "start": primary["start"],
                "end": primary["end"],
                "source_table": primary["table_name"],
                "source_field": primary["field"],
            }
        store = _store_summary(con, tables)
        diagnostics = (
            _records(con, "SELECT * FROM mapping_diagnostics")
            if "mapping_diagnostics" in tables
            else []
        )
        needs_data = (
            _records(con, "SELECT * FROM needs_data") if "needs_data" in tables else []
        )
    finally:
        con.close()

    coverage_rows = assess_coverage(db_path)
    coverage = {
        "producible": [
            {
                "task_id": row.task_id,
                "finding_count": row.finding_count,
                "strengths": row.strengths,
            }
            for row in coverage_rows
            if row.producible
        ],
        "blocked": [
            {"task_id": row.task_id, "reasons": list(row.reasons)}
            for row in coverage_rows
            if not row.producible
        ],
    }

    warnings: list[str] = []
    if report_period:
        actual_start = int(report_period["start"][5:7])
        actual_end = int(report_period["end"][5:7])
        for root in source_roots or []:
            match = _MONTH_RANGE_RE.search(Path(root).name)
            if match and (
                int(match.group("start")) != actual_start
                or int(match.group("end")) != actual_end
            ):
                warnings.append(
                    f"目录名 {Path(root).name} 标注 {match.group(0)}，"
                    f"实际经营主数据为 {actual_start}-{actual_end}月"
                )

    input_hash = _input_hash(files, hashes)
    return {
        "schema_version": 2,
        "provisional": provisional,
        "input_hash": input_hash,
        "mapping_overrides_hash": (
            _sha256(Path(overrides_path))
            if overrides_path is not None and Path(overrides_path).is_file()
            else None
        ),
        "files": file_entries,
        "duplicate_file_groups": duplicate_file_groups,
        "tables": table_summaries,
        "date_ranges": ranges,
        "report_period": report_period,
        "store": store,
        "mapping": {
            "diagnostics_count": len(diagnostics),
            "diagnostics": diagnostics,
        },
        "needs_data": needs_data,
        "coverage": coverage,
        "warnings": warnings,
    }


def inspect_inputs(
    paths: list[Path], *, overrides_path: Path | None = None
) -> dict:
    roots = [Path(path).expanduser().resolve() for path in paths]
    files = resolve_inputs(roots)
    if not files:
        raise ValueError("no input files found")
    baseline_hash = input_fingerprint(files)
    overrides_path = Path(overrides_path) if overrides_path is not None else None
    baseline_overrides_hash = (
        _sha256(overrides_path)
        if overrides_path is not None and overrides_path.is_file()
        else None
    )
    with tempfile.TemporaryDirectory(prefix="xhs-ca-inspect-") as temp_dir:
        temp_root = Path(temp_dir)
        snapshot_files = snapshot_inputs(files, temp_root / "inputs")
        if input_fingerprint(snapshot_files) != baseline_hash:
            raise ValueError("inputs changed during inspection; rerun xhs-ca inspect")
        snapshot_overrides = None
        if overrides_path is not None and overrides_path.is_file():
            snapshot_overrides = snapshot_inputs(
                [overrides_path], temp_root / "configuration"
            )[0]
        if optional_file_fingerprint(snapshot_overrides) != baseline_overrides_hash:
            raise ValueError(
                "mapping overrides changed during inspection; rerun xhs-ca inspect"
            )
        db_path = temp_root / "analytics.duckdb"
        build_database(db_path, snapshot_files, overrides_path=snapshot_overrides)
        if resolve_inputs(roots) != files:
            raise ValueError("input set changed during inspection; rerun xhs-ca inspect")
        if input_fingerprint(files) != baseline_hash:
            raise ValueError("inputs changed during inspection; rerun xhs-ca inspect")
        summary = summarize_database(
            db_path,
            snapshot_files,
            source_roots=roots,
            overrides_path=snapshot_overrides,
            display_files=files,
            provisional=True,
        )
        if (
            summary.get("input_hash") != baseline_hash
            or input_fingerprint(files) != baseline_hash
        ):
            raise ValueError("inputs changed during inspection; rerun xhs-ca inspect")
        final_overrides_hash = (
            _sha256(overrides_path)
            if overrides_path is not None and overrides_path.is_file()
            else None
        )
        if (
            summary.get("mapping_overrides_hash") != baseline_overrides_hash
            or final_overrides_hash != baseline_overrides_hash
        ):
            raise ValueError(
                "mapping overrides changed during inspection; rerun xhs-ca inspect"
            )
        return summary
