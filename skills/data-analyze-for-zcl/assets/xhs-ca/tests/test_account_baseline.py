"""account_baseline — publish baseline + C2 best-posting-window (weekday × 时段)."""
from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "acct.duckdb"
    return connect(db_path), db_path


def _make_notes(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR, publish_time TIMESTAMP, reads DOUBLE, note_gmv DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO notes VALUES (?,?,?,?)", rows)


# 周三·晚间 (Wed 20:00) clearly outperforms 周一·早间 (Mon 08:00); a lone 周五·午间
# post must be dropped by the min-3-posts window guard.
_WINDOW_ROWS = [
    ("n1", "2026-04-06 08:00:00", 100.0, 200.0),  # Mon 早间
    ("n2", "2026-04-13 08:00:00", 110.0, 210.0),  # Mon 早间
    ("n3", "2026-04-20 08:00:00", 90.0, 190.0),   # Mon 早间
    ("n4", "2026-04-08 20:00:00", 500.0, 900.0),  # Wed 晚间
    ("n5", "2026-04-15 20:00:00", 520.0, 950.0),  # Wed 晚间
    ("n6", "2026-04-22 20:00:00", 480.0, 880.0),  # Wed 晚间
    ("n7", "2026-04-10 12:00:00", 999.0, 999.0),  # Fri 午间 — lone post, dropped
]


def test_best_posting_window_ranks_wednesday_evening(tmp_path):
    con, db_path = _con(tmp_path)
    _make_notes(con, _WINDOW_ROWS)
    con.close()
    result = run_task("account_baseline", db_path)

    windows = result.tables["posting_windows"]
    labels = {r["publish_window"] for r in windows}
    assert "周三·晚间" in labels
    assert "周五·午间" not in labels  # min_n guard dropped the lone post
    best = windows[0]
    assert best["publish_window"] == "周三·晚间"
    assert best["posts"] == 3
    assert best["avg_reads"] == 500.0  # (500+520+480)/3
    assert best["perf_lift"] > 0

    finding = next(f for f in result.findings if f.title == "最优发布窗口")
    assert "周三·晚间" in finding.conclusion
    assert "阅读量" in finding.conclusion
    assert finding.key_numbers["best_window"] == "周三·晚间"


def test_posting_window_absent_without_performance_column(tmp_path):
    con, db_path = _con(tmp_path)
    con.execute("CREATE TABLE notes (note_id VARCHAR, publish_time TIMESTAMP)")
    con.executemany(
        "INSERT INTO notes VALUES (?,?)",
        [("n1", "2026-04-08 20:00:00"), ("n2", "2026-04-15 20:00:00")],
    )
    con.close()
    result = run_task("account_baseline", db_path)
    # Baseline finding still emitted; window finding degrades away cleanly.
    assert result.findings[0].title == "发布基线"
    assert "posting_windows" not in result.tables
    assert not any(f.title == "最优发布窗口" for f in result.findings)


def test_posting_window_skipped_when_no_window_reaches_min_posts(tmp_path):
    con, db_path = _con(tmp_path)
    # Every window has ≤2 posts → nothing clears the guard → no window finding.
    _make_notes(
        con,
        [
            ("n1", "2026-04-06 08:00:00", 100.0, 200.0),
            ("n2", "2026-04-08 20:00:00", 500.0, 900.0),
            ("n3", "2026-04-10 12:00:00", 300.0, 400.0),
        ],
    )
    con.close()
    result = run_task("account_baseline", db_path)
    assert "posting_windows" not in result.tables
