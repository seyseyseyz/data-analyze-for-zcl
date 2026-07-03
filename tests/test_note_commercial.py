from pathlib import Path

from xhs_ceramics_analytics.analysis.note_commercial import run
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "notes.duckdb"
    return connect(db_path), db_path


def _make_notes_full(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          title VARCHAR,
          note_type VARCHAR,
          related_product_name VARCHAR,
          reads DOUBLE,
          note_gmv DOUBLE,
          note_paid_orders DOUBLE,
          note_paid_buyers DOUBLE,
          note_refund_rate_pay DOUBLE,
          note_refund_orders_pay DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def _make_notes_partial(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          note_gmv DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO notes VALUES (?, ?)", rows)


# ---- Required table missing -------------------------------------------------


def test_missing_notes_table_degrades_not_judgable(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()
    result = run(db_path)
    assert result.findings
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "notes" in result.limitations[0]


# ---- Full notes table produces WEAK findings --------------------------------


def test_full_notes_produce_weak_findings(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [
        # note_id, title, note_type, related_product_name, reads, note_gmv,
        # note_paid_orders, note_paid_buyers, note_refund_rate_pay, note_refund_orders_pay
        ("n1", "头部笔记1", "种草", "青花瓷碗", 5000.0, 10000.0, 40.0, 42.0, 0.05, 2.0),
        ("n2", "头部笔记2", "种草", "青花瓷碗", 4500.0, 8000.0, 35.0, 36.0, 0.03, 1.0),
        ("n3", "笔记3", "评测", "白瓷盘", 4000.0, 6000.0, 30.0, 31.0, 0.08, 2.0),
        ("n4", "笔记4", "评测", "白瓷盘", 3500.0, 4000.0, 20.0, 21.0, 0.35, 7.0),
        ("n5", "笔记5", "种草", "手绘杯", 3000.0, 3000.0, 15.0, 16.0, 0.10, 2.0),
        ("n6", "笔记6", "种草", "手绘杯", 2500.0, 2000.0, 12.0, 12.0, 0.02, 0.0),
        ("n7", "笔记7", "开箱", "青花瓷碗", 2000.0, 1500.0, 10.0, 10.0, 0.06, 1.0),
        ("n8", "笔记8", "开箱", "白瓷盘", 1500.0, 1000.0, 8.0, 8.0, 0.04, 0.0),
        ("n9", "笔记9", "评测", "手绘杯", 1000.0, 800.0, 5.0, 5.0, 0.20, 1.0),
        ("n10", "笔记10", "种草", "青花瓷碗", 800.0, 500.0, 4.0, 4.0, 0.0, 0.0),
        ("n11", "笔记11", "开箱", "白瓷盘", 400.0, 200.0, 2.0, 2.0, 0.0, 0.0),
        ("n12", "笔记12", "评测", "手绘杯", 100.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    ]
    _make_notes_full(con, rows)
    con.close()
    result = run(db_path)

    assert result.findings
    pareto = next(f for f in result.findings if "集中度" in f.title)
    assert pareto.evidence_strength.value == "weak"
    assert "note_gmv_pareto" in result.tables
    assert result.tables["note_gmv_pareto"]

    other_titles = {f.title for f in result.findings if f is not pareto}
    assert {"转化效率分布", "笔记级退款异常"} & other_titles


# ---- Partial columns skip gated findings ------------------------------------


def test_partial_columns_skip_gated_findings(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [
        ("n1", 10000.0),
        ("n2", 8000.0),
        ("n3", 6000.0),
        ("n4", 0.0),
    ]
    _make_notes_partial(con, rows)
    con.close()
    result = run(db_path)

    assert result.findings
    pareto = next(f for f in result.findings if "集中度" in f.title)
    assert pareto.evidence_strength.value == "weak"

    titles = {f.title for f in result.findings}
    assert "转化效率分布" not in titles
    assert "笔记级退款异常" not in titles
    assert result.limitations
