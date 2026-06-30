from pathlib import Path

from xhs_ceramics_analytics.analysis.result import AnalysisResult, Finding
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def run(db_path: Path) -> AnalysisResult:
    con = connect(db_path)
    try:
        rows = [
            {
                "table": name,
                "rows": con.sql(f"SELECT COUNT(*) FROM {_quote_identifier(name)}").fetchone()[0],
            }
            for (name,) in con.sql("SHOW TABLES").fetchall()
        ]
    finally:
        con.close()
    missing = [row["table"] for row in rows if row["rows"] == 0]
    return AnalysisResult(
        task_id="data_quality_check",
        title="Data Quality Check",
        findings=[
            Finding(
                title="Imported tables are available",
                conclusion=(
                    f"Detected {len(rows)} tables. Empty tables: "
                    f"{', '.join(missing) if missing else 'none'}."
                ),
                evidence_strength=(
                    EvidenceStrength.STRONG if rows else EvidenceStrength.NOT_JUDGABLE
                ),
                key_numbers={"table_count": len(rows)},
                caveats=[]
                if not missing
                else ["Some tables are empty and related analyses will degrade."],
            )
        ],
        tables={"table_row_counts": rows},
        limitations=[],
    )


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'
