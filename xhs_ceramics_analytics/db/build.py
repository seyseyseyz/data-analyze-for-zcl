import re
from pathlib import Path

import pandas as pd

from xhs_ceramics_analytics.contracts.normalize import normalize_order_rows
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.db.marts import create_note_metrics_view
from xhs_ceramics_analytics.importing.mapping import (
    TABLE_SIGNATURES,
    guess_field_mapping,
    guess_table_type,
)
from xhs_ceramics_analytics.importing.profile import (
    EXCEL_SUFFIXES,
    FileProfile,
    load_table,
    profile_file,
)

_DERIVED_TABLES = ("daily_sku_sales",)
_DERIVED_VIEWS = ("note_metrics",)


def build_database(db_path: Path, files: list[Path]) -> None:
    con = connect(db_path)
    try:
        _drop_refresh_objects(con)
        for file in files:
            profile = profile_file(file)
            table_type = guess_table_type(profile)
            if file.suffix.lower() in EXCEL_SUFFIXES:
                _load_dataframe_table(con, db_path, file, profile, table_type)
            elif table_type == "orders":
                _load_csv_orders_table(con, db_path, file, table_type)
            else:
                _load_csv_table(con, file, profile, table_type)
        create_daily_sku_sales(con)
        if "notes" in _existing_tables(con):
            create_note_metrics_view(con)
    finally:
        con.close()


def _drop_refresh_objects(con) -> None:
    for view in _DERIVED_VIEWS:
        con.execute(f"DROP VIEW IF EXISTS {_quote_identifier(view)}")
    for table in [*_DERIVED_TABLES, *TABLE_SIGNATURES]:
        con.execute(f"DROP TABLE IF EXISTS {_quote_identifier(table)}")


def _load_csv_table(con, file: Path, profile: FileProfile, table_type: str) -> None:
    load_profile = FileProfile(
        path=profile.path,
        table_name=profile.table_name,
        columns=_duckdb_csv_columns(con, file),
        row_count=profile.row_count,
        sample_rows=profile.sample_rows,
    )
    projection = ", ".join(_projected_columns(load_profile, table_type))
    con.execute(
        f"""
        CREATE TABLE {_quote_identifier(table_type)} AS
        SELECT {projection}
        FROM read_csv_auto(?)
        """,
        [str(file)],
    )


def _load_dataframe_table(
    con,
    db_path: Path,
    file: Path,
    profile: FileProfile,
    table_type: str,
) -> None:
    frame = load_table(file, sheet=profile.sheet_name)
    projected = _projected_frame(frame, profile, table_type)
    projected = _normalized_frame(projected, table_type)
    staging_path = _write_staging_csv(db_path, table_type, projected)
    con.execute(
        f"""
        CREATE TABLE {_quote_identifier(table_type)} AS
        SELECT *
        FROM read_csv_auto(?)
        """,
        [str(staging_path)],
    )


def _projected_frame(frame, profile: FileProfile, table_type: str):
    field_mapping = guess_field_mapping(profile, table_type)
    rename_mapping = {source: target for target, source in field_mapping.items()}
    projected = frame.rename(columns=rename_mapping)
    projected.columns = [
        _safe_column_name(column) if column not in TABLE_SIGNATURES[table_type] else column
        for column in projected.columns
    ]
    return projected


def _load_csv_orders_table(con, db_path: Path, file: Path, table_type: str) -> None:
    frame = con.execute("SELECT * FROM read_csv_auto(?)", [str(file)]).fetchdf()
    profile = FileProfile(
        path=file,
        table_name=file.stem,
        columns=list(frame.columns),
        row_count=len(frame),
        sample_rows=frame.head(5).astype(object).where(pd.notna(frame.head(5)), None).to_dict(
            orient="records"
        ),
    )
    projected = _projected_frame(frame, profile, table_type)
    projected = _normalized_frame(projected, table_type)
    staging_path = _write_staging_csv(db_path, table_type, projected)
    con.execute(
        f"""
        CREATE TABLE {_quote_identifier(table_type)} AS
        SELECT *
        FROM read_csv_auto(?)
        """,
        [str(staging_path)],
    )


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


def _duckdb_csv_columns(con, file: Path) -> list[str]:
    con.execute("SELECT * FROM read_csv_auto(?) LIMIT 0", [str(file)])
    return [column[0] for column in con.description]


def _projected_columns(profile: FileProfile, table_type: str) -> list[str]:
    field_mapping = guess_field_mapping(profile, table_type)
    source_to_target = {source: target for target, source in field_mapping.items()}
    reserved_names = set(source_to_target.values())
    used_names: set[str] = set()
    projections: list[str] = []
    for source_column in profile.columns:
        if source_column in source_to_target:
            output_name = source_to_target[source_column]
        else:
            output_name = _unique_name(
                _safe_column_name(source_column),
                used_names | reserved_names,
            )
        used_names.add(output_name)
        projections.append(
            f"{_quote_identifier(source_column)} AS {_quote_identifier(output_name)}"
        )
    return projections


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
    con.execute(
        """
        CREATE OR REPLACE TABLE daily_sku_sales AS
        SELECT
          CAST(paid_time AS DATE) AS date,
          sku_id,
          SUM(CAST(quantity AS DOUBLE)) AS units,
          SUM(CAST(paid_amount AS DOUBLE)) AS gmv,
          COUNT(DISTINCT order_id) AS order_count
        FROM orders
        WHERE paid_time IS NOT NULL AND sku_id IS NOT NULL
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    )
