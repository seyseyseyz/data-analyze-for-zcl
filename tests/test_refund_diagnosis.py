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


def test_carrier_finding_compares_two_carriers(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con,
        [
            ("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 300.0, 0.30, 90.0),
            ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 50.0, 0.05, 70.0),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    titles = [f.title for f in result.findings]
    assert "载体退款率对比" in titles
    comp = result.tables["carrier_refund_comparison"]
    assert {r["carrier"] for r in comp} == {"笔记", "商卡"}
    finding = next(f for f in result.findings if f.title == "载体退款率对比")
    assert finding.key_numbers["carrier_high"] == "笔记"
    assert finding.key_numbers["significant"] is True


def test_carrier_finding_skipped_for_single_carrier(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "载体退款率对比" not in [f.title for f in result.findings]
    assert any("载体" in lim for lim in result.limitations)


def _make_business_overview(con, rows):
    con.execute(
        "CREATE TABLE business_overview_daily (date DATE, refund_rate_pay DOUBLE)"
    )
    con.executemany("INSERT INTO business_overview_daily VALUES (?, ?)", rows)


def test_trend_finding_reports_direction(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
              ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0)]
    )
    _make_business_overview(
        con, [("2026-04-30", 0.05), ("2026-05-31", 0.08), ("2026-06-30", 0.12)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "退款率时间趋势")
    assert finding.key_numbers["trend_direction"] == "上升"
    assert len(result.tables["refund_trend"]) == 3


def test_trend_finding_skipped_without_business_overview(tmp_path):
    con, db_path = _con(tmp_path)
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
              ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0)]
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    assert "退款率时间趋势" not in [f.title for f in result.findings]
    assert any("business_overview_daily" in lim for lim in result.limitations)


def _make_notes(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR, title VARCHAR,
          note_refund_rate_pay DOUBLE, note_paid_orders DOUBLE
        )
        """
    )
    con.executemany("INSERT INTO notes VALUES (?, ?, ?, ?)", rows)


def _make_content_features(con, rows):
    con.execute(
        """
        CREATE TABLE content_features (
          note_id VARCHAR, composition_type VARCHAR,
          scene_hint VARCHAR, copy_angle VARCHAR
        )
        """
    )
    con.executemany("INSERT INTO content_features VALUES (?, ?, ?, ?)", rows)


def _refund_overview_two(con):
    _make_refund_overview(
        con, [("笔记", 10000.0, 2000.0, 3000.0, 5000.0, 100.0, 0.10, 90.0),
              ("商卡", 8000.0, 1000.0, 2000.0, 5000.0, 80.0, 0.08, 70.0)]
    )


def test_note_finding_flags_high_refund_and_feature(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    # two clearly high-refund notes share composition 'flatlay'; low-refund notes differ
    _make_notes(
        con,
        [
            ("n1", "高退款A", 0.40, 100.0),
            ("n2", "高退款B", 0.38, 100.0),
            ("n3", "低退款C", 0.03, 100.0),
            ("n4", "低退款D", 0.02, 100.0),
        ],
    )
    _make_content_features(
        con,
        [
            ("n1", "flatlay", "kitchen", "price"),
            ("n2", "flatlay", "studio", "quality"),
            ("n3", "closeup", "kitchen", "story"),
            ("n4", "closeup", "outdoor", "story"),
        ],
    )
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "笔记退款反思")
    assert finding.key_numbers["high_refund_note_count"] >= 1
    ids = {r["note_id"] for r in result.tables["high_refund_notes"]}
    assert {"n1", "n2"} <= ids


def test_note_finding_degrades_without_content_features(tmp_path):
    con, db_path = _con(tmp_path)
    _refund_overview_two(con)
    _make_notes(con, [("n1", "高退款A", 0.40, 100.0), ("n2", "低退款B", 0.02, 100.0)])
    con.close()
    result = run_task("refund_structure_diagnosis", db_path)
    finding = next(f for f in result.findings if f.title == "笔记退款反思")
    assert finding.key_numbers["top_feature"] is None
    assert any("特征" in c for c in finding.caveats)
