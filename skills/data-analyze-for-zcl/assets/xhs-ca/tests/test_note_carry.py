"""笔记承接效率诊断 (note_carry_efficiency) 测试。

覆盖：正常路径数值正确性、缺列降级、部分缺失 caveat、除零守卫。
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.note_carry import run
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "notes.duckdb"
    return connect(db_path), db_path


def _make_notes_full(con, rows):
    """创建包含所有承接字段的 notes 表。
    列顺序：note_id, title, reads, impressions,
            to_shop_home_count, to_shop_home_gmv,
            to_live_count, to_live_gmv
    """
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          title VARCHAR,
          reads DOUBLE,
          impressions DOUBLE,
          to_shop_home_count DOUBLE,
          to_shop_home_gmv DOUBLE,
          to_live_count DOUBLE,
          to_live_gmv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def _make_notes_partial_shop(con, rows):
    """创建只有店铺主页承接字段的 notes 表（缺直播字段）。"""
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          title VARCHAR,
          reads DOUBLE,
          impressions DOUBLE,
          to_shop_home_count DOUBLE,
          to_shop_home_gmv DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)", rows
    )


def _make_notes_missing_all(con, rows):
    """创建完全缺少承接字段的 notes 表。"""
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          title VARCHAR,
          reads DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO notes VALUES (?, ?, ?)", rows
    )


# ---- Missing tables / columns -----------------------------------------------


def test_missing_notes_table_degrades_not_judgable(tmp_path):
    """没有 notes 表时返回 NOT_JUDGABLE."""
    con, db_path = _con(tmp_path)
    con.close()
    result = run(db_path)
    assert result.findings
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "notes" in result.limitations[0]


def test_missing_all_carry_columns_degrades_not_judgable(tmp_path):
    """四列都缺时返回 NOT_JUDGABLE."""
    con, db_path = _con(tmp_path)
    rows = [
        ("n1", "笔记1", 1000.0),
        ("n2", "笔记2", 2000.0),
    ]
    _make_notes_missing_all(con, rows)
    con.close()

    result = run(db_path)
    assert result.findings
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert any("进店" in c or "直播" in c for c in result.findings[0].caveats)


# ---- Full data produces WEAK findings with correct numbers ------------------


def test_full_data_produces_weak_findings(tmp_path):
    """完整数据产出 WEAK evidence."""
    con, db_path = _con(tmp_path)
    rows = [
        # note_id, title, reads, impressions,
        # to_shop_home_count, to_shop_home_gmv,
        # to_live_count, to_live_gmv
        ("n1", "笔记1", 5000.0, 10000.0, 500.0, 5000.0, 100.0, 2000.0),
        ("n2", "笔记2", 4000.0, 8000.0, 400.0, 4000.0, 80.0, 1600.0),
        ("n3", "笔记3", 3000.0, 6000.0, 300.0, 3000.0, 60.0, 1200.0),
    ]
    _make_notes_full(con, rows)
    con.close()

    result = run(db_path)
    assert result.findings
    finding = result.findings[0]
    assert finding.evidence_strength.value == "weak"
    assert finding.title == "笔记承接效率（进店与直播）"
    assert "note_carry" in result.tables


def test_correct_aggregation_numbers(tmp_path):
    """验证汇总数值正确性。"""
    con, db_path = _con(tmp_path)
    rows = [
        ("n1", "笔记1", 5000.0, 10000.0, 500.0, 5000.0, 100.0, 2000.0),
        ("n2", "笔记2", 4000.0, 8000.0, 400.0, 4000.0, 80.0, 1600.0),
    ]
    _make_notes_full(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    # 汇总数值验证
    assert kn["total_shop_home_count"] == 900.0
    assert kn["total_shop_home_gmv"] == 9000.0
    assert kn["total_live_count"] == 180.0
    assert kn["total_live_gmv"] == 3600.0

    # 承接率：进店 500+400=900, 阅读 5000+4000=9000 → 10%
    assert abs(kn["shop_home_carry_rate"] - 0.10) < 1e-9

    # 直播承接率：100+80=180, 阅读9000 → 2%
    assert abs(kn["live_carry_rate"] - 0.02) < 1e-9

    # 平均支付：进店9000/900=10
    assert abs(kn["avg_shop_home_payment"] - 10.0) < 1e-9
    # 直播3600/180=20
    assert abs(kn["avg_live_payment"] - 20.0) < 1e-9


def test_carry_rate_with_impressions_fallback(tmp_path):
    """reads 缺失时用 impressions 计算承接率。"""
    con, db_path = _con(tmp_path)
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          title VARCHAR,
          reads DOUBLE,
          impressions DOUBLE,
          to_shop_home_count DOUBLE,
          to_shop_home_gmv DOUBLE,
          to_live_count DOUBLE,
          to_live_gmv DOUBLE
        )
        """
    )
    # 只有 impressions，reads 为 NULL
    rows = [
        ("n1", "笔记1", None, 10000.0, 1000.0, 5000.0, 200.0, 2000.0),
    ]
    con.executemany("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    # 承接率应该用 impressions：1000/10000=10%
    assert abs(kn["shop_home_carry_rate"] - 0.10) < 1e-9
    assert any("impressions" in c for c in finding.caveats)


def test_carry_rate_none_when_both_reads_and_impressions_missing(tmp_path):
    """reads 和 impressions 都缺时承接率为 None."""
    con, db_path = _con(tmp_path)
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          to_shop_home_count DOUBLE,
          to_shop_home_gmv DOUBLE,
          to_live_count DOUBLE,
          to_live_gmv DOUBLE
        )
        """
    )
    rows = [("n1", 100.0, 1000.0, 50.0, 500.0)]
    con.executemany("INSERT INTO notes VALUES (?, ?, ?, ?, ?)", rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    assert kn["shop_home_carry_rate"] is None
    assert kn["live_carry_rate"] is None
    assert any("阅读" in c or "曝光" in c for c in finding.caveats)


def test_zero_counts_no_division_error(tmp_path):
    """0 次进店时平均支付为 None，不抛异常。"""
    con, db_path = _con(tmp_path)
    rows = [
        ("n1", "笔记1", 5000.0, 10000.0, 0.0, 0.0, 0.0, 0.0),
    ]
    _make_notes_full(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    assert kn["avg_shop_home_payment"] is None
    assert kn["avg_live_payment"] is None


def test_partial_missing_columns_with_caveat(tmp_path):
    """缺直播字段时只计算店铺指标，caveat 说明缺哪边。"""
    con, db_path = _con(tmp_path)
    rows = [
        ("n1", "笔记1", 5000.0, 10000.0, 500.0, 5000.0),
        ("n2", "笔记2", 4000.0, 8000.0, 400.0, 4000.0),
    ]
    _make_notes_partial_shop(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]

    # 店铺数据应该完整
    assert finding.key_numbers["total_shop_home_count"] == 900.0
    # 直播字段缺失，所以都是 0 或 None
    assert finding.key_numbers["total_live_count"] == 0.0

    # caveat 应说明缺直播
    assert any("直播" in c for c in finding.caveats)


def test_top_20_table_sorted_by_total_gmv(tmp_path):
    """明细表 note_carry 按 (to_shop_home_gmv + to_live_gmv) 降序，top 20。"""
    con, db_path = _con(tmp_path)
    rows = []
    for i in range(30):
        # 控制总支付金额，使排序可预测
        shop_gmv = float(3000 - i * 100)
        live_gmv = float(1000 - i * 30)
        rows.append((f"n{i}", f"笔记{i}", 1000.0, 2000.0, 100.0, shop_gmv, 20.0, live_gmv))

    _make_notes_full(con, rows)
    con.close()

    result = run(db_path)
    table = result.tables["note_carry"]

    # 应该有 20 行
    assert len(table) == 20

    # 按总 GMV 降序
    for i in range(len(table) - 1):
        cur_total = (table[i].get("to_shop_home_gmv") or 0) + (table[i].get("to_live_gmv") or 0)
        next_total = (table[i + 1].get("to_shop_home_gmv") or 0) + (table[i + 1].get("to_live_gmv") or 0)
        assert cur_total >= next_total


def test_table_includes_correct_columns(tmp_path):
    """明细表应包含 note_id/title、曝光/阅读、进店/直播各项数据。"""
    con, db_path = _con(tmp_path)
    rows = [
        ("n1", "笔记1", 5000.0, 10000.0, 500.0, 5000.0, 100.0, 2000.0),
    ]
    _make_notes_full(con, rows)
    con.close()

    result = run(db_path)
    table = result.tables["note_carry"]
    assert table

    row = table[0]
    # 验证关键列存在
    assert "note_id" in row or "note_title" in row
    assert "impressions" in row or "reads" in row
    assert "to_shop_home_count" in row
    assert "to_shop_home_gmv" in row
    assert "to_live_count" in row
    assert "to_live_gmv" in row
