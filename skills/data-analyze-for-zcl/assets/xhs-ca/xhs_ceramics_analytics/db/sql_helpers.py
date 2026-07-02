"""Small reusable SQL fragment builders for DuckDB queries."""


def numeric_expr(columns: set[str], column: str) -> str:
    """Return a SQL fragment that casts ``column`` to DOUBLE when present.

    Falls back to the SQL literal ``NULL`` when the column is absent so
    expressions such as ``SUM(...)`` propagate ``NULL`` instead of raising.
    """
    if column not in columns:
        return "NULL"
    return f"CAST({column} AS DOUBLE)"
