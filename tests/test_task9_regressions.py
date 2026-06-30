from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect
from xhs_ceramics_analytics.evidence import EvidenceStrength


def _run(task_id: str, db_path: Path):
    return run_task(task_id, db_path)


def _create_notes(con) -> None:
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          publish_time TIMESTAMP
        )
        """
    )


def _create_skus(con) -> None:
    con.execute(
        """
        CREATE TABLE skus (
          sku_id VARCHAR
        )
        """
    )


def _create_note_sku_links(con) -> None:
    con.execute(
        """
        CREATE TABLE note_sku_links (
          note_id VARCHAR,
          sku_id VARCHAR
        )
        """
    )


def _create_daily_sku_sales(con) -> None:
    con.execute(
        """
        CREATE TABLE daily_sku_sales (
          date DATE,
          sku_id VARCHAR,
          units DOUBLE
        )
        """
    )


def test_task9_missing_daily_sku_sales_returns_not_judgable(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        _create_notes(con)
        _create_skus(con)
        _create_note_sku_links(con)
        con.execute(
            """
            INSERT INTO notes VALUES ('n1', TIMESTAMP '2026-06-01 09:00:00')
            """
        )
        con.execute("INSERT INTO skus VALUES ('s1')")
        con.execute("INSERT INTO note_sku_links VALUES ('n1', 's1')")
    finally:
        con.close()

    lift = _run("sku_counterfactual_lift", db_path)
    curve = _run("content_response_curve", db_path)

    assert lift.tables["sku_lift"] == []
    assert lift.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert "daily_sku_sales" in " ".join(lift.limitations)

    assert curve.tables["response_windows"] == []
    assert curve.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert "daily_sku_sales" in " ".join(curve.limitations)


def test_task9_missing_required_sales_columns_returns_not_judgable(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        _create_notes(con)
        _create_skus(con)
        _create_note_sku_links(con)
        con.execute(
            """
            CREATE TABLE daily_sku_sales (
              sku_id VARCHAR,
              units DOUBLE
            )
            """
        )
        con.execute(
            """
            INSERT INTO notes VALUES ('n1', TIMESTAMP '2026-06-01 09:00:00')
            """
        )
        con.execute("INSERT INTO skus VALUES ('s1')")
        con.execute("INSERT INTO note_sku_links VALUES ('n1', 's1')")
    finally:
        con.close()

    lift = _run("sku_counterfactual_lift", db_path)
    curve = _run("content_response_curve", db_path)

    assert lift.tables["sku_lift"] == []
    assert lift.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert curve.tables["response_windows"] == []
    assert curve.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE


def test_task9_not_judgable_without_links_or_notes(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        _create_daily_sku_sales(con)
        con.execute(
            """
            INSERT INTO daily_sku_sales VALUES
              (DATE '2026-06-01', 's1', 2.0)
            """
        )
    finally:
        con.close()

    lift = _run("sku_counterfactual_lift", db_path)
    curve = _run("content_response_curve", db_path)

    assert lift.tables["sku_lift"] == []
    assert lift.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE
    assert curve.tables["response_windows"] == []
    assert curve.findings[0].evidence_strength == EvidenceStrength.NOT_JUDGABLE


def test_task9_uses_publish_anchored_windows_and_exposes_long_tail(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        _create_notes(con)
        _create_note_sku_links(con)
        _create_daily_sku_sales(con)
        con.execute(
            """
            INSERT INTO notes VALUES ('n1', TIMESTAMP '2026-06-10 09:00:00')
            """
        )
        con.execute("INSERT INTO note_sku_links VALUES ('n1', 's1')")
        con.execute(
            """
            INSERT INTO daily_sku_sales VALUES
              (DATE '2026-06-09', 's1', 2.0),
              (DATE '2026-06-07', 's1', 1.0),
              (DATE '2026-06-08', 's1', 1.0),
              (DATE '2026-06-06', 's1', 1.0),
              (DATE '2026-06-04', 's1', 1.0),
              (DATE '2026-06-05', 's1', 1.0),
              (DATE '2026-06-10', 's1', 5.0),
              (DATE '2026-06-11', 's1', 1.0),
              (DATE '2026-06-12', 's1', 1.0),
              (DATE '2026-06-13', 's1', 1.0),
              (DATE '2026-06-14', 's1', 2.0),
              (DATE '2026-06-15', 's1', 2.0),
              (DATE '2026-06-16', 's1', 2.0),
              (DATE '2026-06-17', 's1', 2.0),
              (DATE '2026-06-18', 's1', 3.0),
              (DATE '2026-06-19', 's1', 3.0),
              (DATE '2026-06-20', 's1', 3.0),
              (DATE '2026-06-21', 's1', 3.0),
              (DATE '2026-06-22', 's1', 3.0),
              (DATE '2026-06-23', 's1', 3.0),
              (DATE '2026-06-24', 's1', 3.0)
            """
        )
    finally:
        con.close()

    lift = _run("sku_counterfactual_lift", db_path)
    curve = _run("content_response_curve", db_path)

    lift_by_window = {row["window"]: row for row in lift.tables["sku_lift"]}
    assert set(lift_by_window) == {"d0_1", "d1_3", "d4_7", "d8_14"}
    assert lift_by_window["d0_1"]["pre_units"] == 2.0
    assert lift_by_window["d0_1"]["post_units"] == 5.0
    assert lift_by_window["d0_1"]["absolute_lift"] == 3.0
    assert lift_by_window["d0_1"]["relative_lift"] == 1.5
    assert lift_by_window["d1_3"]["pre_units"] == 4.0
    assert lift_by_window["d1_3"]["post_units"] == 3.0
    assert lift_by_window["d4_7"]["pre_units"] == 5.0
    assert lift_by_window["d4_7"]["post_units"] == 8.0
    assert lift_by_window["d8_14"]["pre_units"] == 7.0
    assert lift_by_window["d8_14"]["post_units"] == 21.0

    assert curve.tables["response_windows"] == [
        {
            "note_id": "n1",
            "sku_id": "s1",
            "publish_time": "2026-06-10 09:00:00",
            "d0_1_units": 5.0,
            "d1_3_units": 3.0,
            "d4_7_units": 8.0,
            "d8_14_units": 21.0,
        }
    ]


def test_task9_relative_lift_is_none_when_pre_window_is_zero(tmp_path):
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        _create_notes(con)
        _create_note_sku_links(con)
        _create_daily_sku_sales(con)
        con.execute(
            """
            INSERT INTO notes VALUES ('n1', TIMESTAMP '2026-06-10 09:00:00')
            """
        )
        con.execute("INSERT INTO note_sku_links VALUES ('n1', 's1')")
        con.execute(
            """
            INSERT INTO daily_sku_sales VALUES
              (DATE '2026-06-10', 's1', 3.0),
              (DATE '2026-06-11', 's1', 1.0),
              (DATE '2026-06-12', 's1', 1.0),
              (DATE '2026-06-13', 's1', 1.0),
              (DATE '2026-06-18', 's1', 2.0),
              (DATE '2026-06-19', 's1', 2.0),
              (DATE '2026-06-20', 's1', 2.0),
              (DATE '2026-06-21', 's1', 2.0),
              (DATE '2026-06-22', 's1', 2.0),
              (DATE '2026-06-23', 's1', 2.0),
              (DATE '2026-06-24', 's1', 2.0)
            """
        )
    finally:
        con.close()

    result = _run("sku_counterfactual_lift", db_path)

    lift_by_window = {row["window"]: row for row in result.tables["sku_lift"]}
    assert lift_by_window["d0_1"]["pre_units"] == 0.0
    assert lift_by_window["d0_1"]["relative_lift"] is None
    assert lift_by_window["d8_14"]["relative_lift"] is None
