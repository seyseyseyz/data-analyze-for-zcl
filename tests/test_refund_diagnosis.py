from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "refund.duckdb"
    return connect(db_path), db_path


def _make_refund_overview(con, rows):
    con.execute(
        """
        CREATE TABLE refund_overview (
          carrier VARCHAR,
          refund_amount_pay DOUBLE,
          pre_ship_refund_amount DOUBLE,
          post_ship_refund_amount DOUBLE,
          return_refund_amount DOUBLE,
          refund_orders_pay DOUBLE,
          refund_rate_pay DOUBLE,
          refund_users DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO refund_overview VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def test_missing_refund_overview_is_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert result.task_id == "refund_structure_diagnosis"
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "refund_overview" in result.limitations[0]


def test_layer_finding_identifies_dominant_layer(tmp_path):
    con, db_path = _con(tmp_path)
    # return layer dominates total refund amount
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    layer = result.tables["refund_layer_breakdown"]
    kn = result.findings[0].key_numbers
    assert kn["dominant_layer"] == "return"
    assert {r["layer"] for r in layer} == {"pre_ship", "post_ship", "return"}
    assert result.findings[0].recommended_action  # lever text present
    assert result.findings[0].evidence_strength.value == "weak"
