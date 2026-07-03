import re
from collections import defaultdict
from pathlib import Path

import pandas as pd

from xhs_ceramics_analytics.contracts.normalize import normalize_order_rows
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.db.marts import (
    create_ad_metrics_view,
    create_business_overview_monthly,
    create_note_metrics_view,
)
from xhs_ceramics_analytics.importing.mapping import (
    GRAIN_KEYS,
    TABLE_SIGNATURES,
    map_columns,
    guess_table_type,
)
from xhs_ceramics_analytics.importing.overrides import load_overrides
from xhs_ceramics_analytics.importing.profile import (
    EXCEL_SUFFIXES,
    FileProfile,
    load_table,
    profile_file,
)

_DERIVED_TABLES = ("daily_sku_sales", "business_overview_monthly")
_DERIVED_VIEWS = ("note_metrics", "ad_metrics")
_AUX_TABLES = ("needs_data", "build_manifest", "data_quality", "mapping_diagnostics")
_TABULAR_SUFFIXES = {".csv", *EXCEL_SUFFIXES}
_DOMAIN_HINTS = (("退款原因", "退款原因"), ("人群", "人群画像"))
# Two files that both report a metric for the same grain key may round differently.
# A relative gap at or below this is treated as agreement (silent merge); above it
# is a data-quality conflict naming both files. Distinct from Task 12's refund
# reconcile tolerance, which cross-checks computed vs platform net_gmv.
MERGE_CONFLICT_TOLERANCE = 0.05


def build_database(
    db_path: Path,
    files: list[Path],
    *,
    overrides_path: Path | None = None,
) -> None:
    con = connect(db_path)
    try:
        _drop_refresh_objects(con)
        overrides = load_overrides(
            overrides_path or db_path.parent / "mapping_overrides.yaml"
        )
        grouped, needs_data, diagnostics = _group_files_by_type(con, files, overrides)
        conflicts: list[dict] = []
        manifest: list[dict] = []
        for table_type, tagged in grouped.items():
            conflicts.extend(_detect_conflicts(tagged, table_type))
            manifest.extend(_build_manifest_records(table_type, tagged))
            merged = _combine_frames([frame for _, frame in tagged], table_type)
            _create_table_from_frame(con, db_path, table_type, merged)
        _create_needs_data_table(con, db_path, needs_data)
        _create_build_manifest_table(con, db_path, manifest)
        _create_data_quality_table(con, db_path, conflicts)
        _create_mapping_diagnostics_table(con, db_path, diagnostics)
        create_daily_sku_sales(con)
        if "business_overview_daily" in _existing_tables(con):
            create_business_overview_monthly(con)
        if "notes" in _existing_tables(con):
            create_note_metrics_view(con)
        if "ad_performance_daily" in _existing_tables(con):
            create_ad_metrics_view(con)
    finally:
        con.close()


def _group_files_by_type(
    con, files: list[Path], overrides: dict[str, dict[str, set[str]]]
) -> tuple[dict[str, list], list[dict], list[dict]]:
    # Each grouped value is a list of ``(file_name, canonical_frame)`` pairs (provenance
    # for build_manifest / data_quality). ``diagnostics`` is the flat per-column record
    # list for the mapping_diagnostics table — the file name is attached HERE, where it
    # is known, since ColumnDiagnostic itself carries only table_type/required_column.
    grouped: dict[str, list] = defaultdict(list)
    needs_data: list[dict] = []
    diagnostics: list[dict] = []
    for file in files:
        if file.suffix.lower() not in _TABULAR_SUFFIXES:
            needs_data.append(_needs_data_record(file, "非表格文件（如PNG截图）", "OCR 或手工录入"))
            continue
        try:
            profile = profile_file(file)
            table_type = guess_table_type(profile)
        except ValueError as exc:  # incl. AmbiguousTableTypeError
            needs_data.append(_needs_data_record(file, str(exc), "确认导出列或手工映射"))
            continue
        frame, file_diagnostics = _canonical_frame(con, file, profile, table_type, overrides)
        grouped[table_type].append((file.name, frame))
        for diag in file_diagnostics:
            diagnostics.append(
                {
                    "table_name": diag.table_type,
                    "file": file.name,
                    "required_column": diag.required_column,
                    "status": diag.status,
                    "candidate_sources": "; ".join(diag.candidate_sources),
                    "reason": diag.reason,
                    "action": diag.action,
                }
            )
    return grouped, needs_data, diagnostics


def _needs_data_record(file: Path, reason: str, action: str) -> dict:
    domain = "未识别文件"
    for hint, name in _DOMAIN_HINTS:
        if hint in file.name:
            domain = name
            break
    return {"file": file.name, "domain": domain, "reason": reason, "action": action}


def _create_needs_data_table(con, db_path: Path, needs_data: list[dict]) -> None:
    frame = pd.DataFrame(needs_data, columns=["file", "domain", "reason", "action"])
    _create_table_from_frame(con, db_path, "needs_data", frame)


def _build_manifest_records(table_type: str, tagged: list) -> list[dict]:
    """One provenance row per contributing file (spec §A.2)."""
    return [
        {"table_name": table_type, "file": name, "row_count": int(len(frame))}
        for name, frame in tagged
    ]


def _create_build_manifest_table(con, db_path: Path, manifest: list[dict]) -> None:
    frame = pd.DataFrame(manifest, columns=["table_name", "file", "row_count"])
    _create_table_from_frame(con, db_path, "build_manifest", frame)


def _coerce_number(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _values_conflict(a: object, b: object) -> bool:
    """True when two files disagree on a shared column beyond tolerance.

    Nulls never conflict — coalesce fills them. Numeric values compare by
    relative gap against ``MERGE_CONFLICT_TOLERANCE``; non-numeric by exact string.
    """
    if pd.isna(a) or pd.isna(b):
        return False
    a_num, b_num = _coerce_number(a), _coerce_number(b)
    if a_num is not None and b_num is not None:
        scale = max(abs(a_num), abs(b_num))
        if scale == 0:
            return False
        return abs(a_num - b_num) / scale > MERGE_CONFLICT_TOLERANCE
    return str(a) != str(b)


def _format_grain_key(key_cols: list[str], key: tuple) -> str:
    return ", ".join(f"{col}={value}" for col, value in zip(key_cols, key))


def _detect_conflicts(tagged: list, table_type: str) -> list[dict]:
    """Cross-file coalesce conflicts for a grain-keyed type (spec §A.2).

    For each pair of files that describe the same grain key, any shared column
    whose values disagree beyond tolerance becomes one data-quality row naming
    both files. Non-grain-keyed types (plain-union) and single-file types skip.
    """
    keys = GRAIN_KEYS.get(table_type)
    if not keys or len(tagged) < 2:
        return []
    key_cols = [key for key in keys if all(key in frame.columns for _, frame in tagged)]
    if not key_cols:
        return []
    indexed: list[tuple[str, dict]] = []
    for name, frame in tagged:
        rows = {tuple(row[col] for col in key_cols): row for _, row in frame.iterrows()}
        indexed.append((name, rows))
    conflicts: list[dict] = []
    for i in range(len(indexed)):
        name_a, rows_a = indexed[i]
        for j in range(i + 1, len(indexed)):
            name_b, rows_b = indexed[j]
            for key in set(rows_a) & set(rows_b):
                row_a, row_b = rows_a[key], rows_b[key]
                shared = (set(row_a.index) & set(row_b.index)) - set(key_cols)
                for column in sorted(shared):
                    if _values_conflict(row_a[column], row_b[column]):
                        conflicts.append(
                            {
                                "table_name": table_type,
                                "grain_key": _format_grain_key(key_cols, key),
                                "column_name": column,
                                "file_a": name_a,
                                "file_b": name_b,
                                "value_a": str(row_a[column]),
                                "value_b": str(row_b[column]),
                            }
                        )
    return conflicts


def _create_data_quality_table(con, db_path: Path, conflicts: list[dict]) -> None:
    frame = pd.DataFrame(
        conflicts,
        columns=[
            "table_name", "grain_key", "column_name",
            "file_a", "file_b", "value_a", "value_b",
        ],
    )
    _create_table_from_frame(con, db_path, "data_quality", frame)


def _create_mapping_diagnostics_table(con, db_path: Path, diagnostics: list[dict]) -> None:
    frame = pd.DataFrame(
        diagnostics,
        columns=[
            "table_name", "file", "required_column", "status",
            "candidate_sources", "reason", "action",
        ],
    )
    _create_table_from_frame(con, db_path, "mapping_diagnostics", frame)


def _canonical_frame(con, file: Path, profile: FileProfile, table_type: str, overrides):
    if file.suffix.lower() in EXCEL_SUFFIXES:
        frame = load_table(file, sheet=profile.sheet_name)
    else:
        frame = con.execute("SELECT * FROM read_csv_auto(?)", [str(file)]).fetchdf()
        profile = FileProfile(
            path=file,
            table_name=profile.table_name,
            columns=list(frame.columns),
            row_count=len(frame),
            sample_rows=profile.sample_rows,
        )
    projected, diagnostics = _projected_frame(frame, profile, table_type, overrides)
    return _normalized_frame(projected, table_type), diagnostics


def _combine_frames(frames: list, table_type: str):
    combined = pd.concat(frames, ignore_index=True, sort=False)
    keys = GRAIN_KEYS.get(table_type)
    if not keys:
        return combined
    key_cols = [key for key in keys if key in combined.columns]
    if not key_cols:
        return combined
    merged = combined.groupby(key_cols, dropna=False, as_index=False, sort=False).first()
    ordered = [column for column in combined.columns if column in merged.columns]
    return merged[ordered]


def _create_table_from_frame(con, db_path: Path, table_type: str, frame) -> None:
    staging_path = _write_staging_csv(db_path, table_type, frame)
    con.execute(
        f"""
        CREATE TABLE {_quote_identifier(table_type)} AS
        SELECT *
        FROM read_csv_auto(?)
        """,
        [str(staging_path)],
    )


def _drop_refresh_objects(con) -> None:
    for view in _DERIVED_VIEWS:
        con.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view)}")
    for table in [*_DERIVED_TABLES, *_AUX_TABLES, *TABLE_SIGNATURES]:
        con.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table)}")


def _projected_frame(frame, profile: FileProfile, table_type: str, overrides):
    result = map_columns(profile, table_type, overrides=overrides)
    rename_mapping = {source: target for target, source in result.mapping.items()}
    projected = frame.rename(columns=rename_mapping)
    reserved = set(rename_mapping.values())
    used: set[str] = set()
    new_columns: list[str] = []
    for column in projected.columns:
        if column in reserved:
            new_columns.append(column)
        else:
            safe = _unique_name(_safe_column_name(column), used | reserved)
            used.add(safe)
            new_columns.append(safe)
    projected.columns = new_columns
    return projected, result.diagnostics


def _normalized_frame(frame, table_type: str):
    if table_type != "orders":
        return frame

    records = frame.astype(object).where(pd.notna(frame), None).to_dict(orient="records")
    normalized_orders = normalize_order_rows(records)
    normalized = pd.DataFrame([order.model_dump() for order in normalized_orders])
    extra_columns = [
        column
        for column in frame.columns
        if column not in normalized.columns and column not in TABLE_SIGNATURES[table_type]
    ]
    if extra_columns:
        normalized = pd.concat([normalized, frame[extra_columns].reset_index(drop=True)], axis=1)
    return normalized


def _write_staging_csv(db_path: Path, table_type: str, frame) -> Path:
    staging_dir = db_path.parent / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_path = staging_dir / f"{table_type}.normalized.csv"
    frame.to_csv(staging_path, index=False)
    return staging_path


def _existing_tables(con) -> set[str]:
    return {row[0] for row in con.sql("SHOW TABLES").fetchall()}


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _safe_column_name(column: str) -> str:
    normalized = re.sub(r"\W+", "_", column.strip().lower()).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    if not normalized:
        return "column"
    if normalized[0].isdigit():
        return f"column_{normalized}"
    return normalized


def _unique_name(name: str, used_names: set[str]) -> str:
    if name not in used_names:
        return name
    suffix = 2
    while f"{name}_{suffix}" in used_names:
        suffix += 1
    return f"{name}_{suffix}"


def create_daily_sku_sales(con) -> None:
    if "orders" not in _existing_tables(con):
        return
    order_columns = {
        row[1] for row in con.sql("PRAGMA table_info('orders')").fetchall()
    }
    required_columns = {"order_id", "paid_time", "sku_id", "quantity", "paid_amount"}
    if not required_columns.issubset(order_columns):
        return
    refund_filter = ""
    if "refund_status_optional" in order_columns:
        refund_filter = """
          AND (
            refund_status_optional IS NULL
            OR lower(trim(CAST(refund_status_optional AS VARCHAR))) NOT IN (
              'refund',
              'refunded',
              'refund_success',
              'partial_refund',
              'cancelled',
              'canceled',
              '已退款',
              '退款成功',
              '部分退款',
              '已取消',
              '取消'
            )
          )
        """
    con.execute(
        f"""
        CREATE OR REPLACE TABLE daily_sku_sales AS
        SELECT
          CAST(paid_time AS DATE) AS date,
          sku_id,
          SUM(CAST(quantity AS DOUBLE)) AS units,
          SUM(CAST(paid_amount AS DOUBLE)) AS gmv,
          COUNT(DISTINCT order_id) AS order_count
        FROM orders
        WHERE paid_time IS NOT NULL AND sku_id IS NOT NULL
          {refund_filter}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )
