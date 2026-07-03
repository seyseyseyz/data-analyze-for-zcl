"""Coverage assessment classifies producible vs blocked tasks without raising."""
from pathlib import Path

from xhs_ceramics_analytics.analysis.coverage import (
    assess_coverage,
    producible_task_ids,
)
from xhs_ceramics_analytics.db.duck import connect


def _empty_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "empty.duckdb"
    connect(db_path).close()
    return db_path


def _notes_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "notes.duckdb"
    con = connect(db_path)
    con.execute("CREATE TABLE notes (note_id VARCHAR, note_gmv DOUBLE)")
    con.executemany(
        "INSERT INTO notes VALUES (?, ?)",
        [(f"n{i}", float(100 - i * 5)) for i in range(12)],
    )
    con.close()
    return db_path


def test_assess_coverage_never_raises_and_covers_every_task(tmp_path):
    coverage = assess_coverage(_empty_db(tmp_path))
    from xhs_ceramics_analytics.analysis.registry import TASKS

    assert {c.task_id for c in coverage} == set(TASKS)
    # On an empty DB nothing is producible, and each blocked task carries a reason.
    assert all(not c.producible for c in coverage)
    assert all(c.reasons for c in coverage)


def test_producible_task_ids_detects_unlocked_module(tmp_path):
    ids = producible_task_ids(_notes_db(tmp_path))
    # A notes table with GMV unlocks the note-commercial diagnosis.
    assert "note_commercial_diagnosis" in ids
    # Tasks needing other tables stay blocked.
    assert "sku_structure_diagnosis" not in ids
