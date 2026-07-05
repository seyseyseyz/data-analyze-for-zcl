"""每周经营复盘:按有数据的子段逐条产出结论 (病根 E / E1)。"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "weekly.duckdb"
    return connect(db_path), db_path


def test_weekly_review_emits_one_finding_per_ready_section(tmp_path):
    con, db_path = _con(tmp_path)
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR, publish_time TIMESTAMP, reads DOUBLE, impressions DOUBLE,
          likes DOUBLE, collects DOUBLE, comments DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO notes VALUES (?,?,?,?,?,?,?)",
        [
            ("n1", "2026-05-01 10:00:00", 1000.0, 5000.0, 100.0, 50.0, 20.0),
            ("n2", "2026-05-02 10:00:00", 1200.0, 6000.0, 120.0, 60.0, 24.0),
        ],
    )
    con.execute("CREATE TABLE daily_sku_sales (sku_id VARCHAR, units DOUBLE, gmv DOUBLE)")
    con.executemany(
        "INSERT INTO daily_sku_sales VALUES (?,?,?)",
        [("sku-a", 30.0, 1500.0), ("sku-b", 10.0, 600.0)],
    )
    con.close()

    result = run_task("weekly_business_review", db_path)
    # data_quality + baseline + funnel + product_opportunity all ready → 逐段一条。
    assert len(result.findings) >= 3
    titles = " ".join(f.title for f in result.findings)
    assert "账号基线" in titles
    assert "漏斗" in titles
    # 不再是恒一条"已汇总 N 个模块"。
    assert not any("已汇总" in f.conclusion for f in result.findings)


def test_weekly_review_degrades_to_single_not_judgable_when_no_data(tmp_path):
    con, db_path = _con(tmp_path)
    con.close()  # empty DB: no tables at all → every section missing.

    result = run_task("weekly_business_review", db_path)
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
