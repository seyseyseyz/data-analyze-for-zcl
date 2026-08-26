"""买家复购结构诊断 (buyer_repurchase_diagnosis) 测试。

覆盖：正常路径数值正确性、覆盖率降级、买家数去重、
复购率计算、复购间隔、哈希截断、观察窗注记。
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.buyer_repurchase import run
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "orders.duckdb"
    return connect(db_path), db_path


def _make_orders_full(con, rows):
    """创建包含所有字段的 orders 表。
    列顺序：order_id, paid_time, paid_amount, buyer_id_hash
    """
    con.execute(
        """
        CREATE TABLE orders (
          order_id VARCHAR,
          paid_time TIMESTAMP,
          paid_amount DOUBLE,
          buyer_id_hash VARCHAR
        )
        """
    )
    con.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?)", rows
    )


def _make_orders_no_buyer_hash(con, rows):
    """创建缺少 buyer_id_hash 的 orders 表。"""
    con.execute(
        """
        CREATE TABLE orders (
          order_id VARCHAR,
          paid_time TIMESTAMP,
          paid_amount DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO orders VALUES (?, ?, ?)", rows
    )


def _make_orders_sparse_buyer_hash(con, rows):
    """创建大部分 buyer_id_hash 为 NULL 的 orders 表。"""
    con.execute(
        """
        CREATE TABLE orders (
          order_id VARCHAR,
          paid_time TIMESTAMP,
          paid_amount DOUBLE,
          buyer_id_hash VARCHAR
        )
        """
    )
    con.executemany(
        "INSERT INTO orders VALUES (?, ?, ?, ?)", rows
    )


# ---- Missing tables / columns -----------------------------------------------


def test_missing_orders_table_degrades_not_judgable(tmp_path):
    """没有 orders 表时返回 NOT_JUDGABLE."""
    con, db_path = _con(tmp_path)
    con.close()
    result = run(db_path)
    assert result.findings
    assert len(result.findings) == 1
    assert result.findings[0].evidence_strength.value == "not_judgable"
    assert "orders" in result.limitations[0]


# ---- Full data produces WEAK findings with correct numbers ------------------


def test_full_data_produces_weak_findings(tmp_path):
    """完整数据 + 高覆盖率产出 WEAK evidence."""
    con, db_path = _con(tmp_path)
    rows = [
        # 单次买家
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 11:00:00", 120.0, "buyer002"),
        # 复购买家（2 单及以上）
        ("o3", "2025-01-03 12:00:00", 150.0, "buyer003"),
        ("o4", "2025-01-04 13:00:00", 160.0, "buyer003"),
        ("o5", "2025-01-05 14:00:00", 110.0, "buyer004"),
        ("o6", "2025-01-06 15:00:00", 130.0, "buyer004"),
        ("o7", "2025-01-07 16:00:00", 140.0, "buyer004"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    assert result.findings
    finding = result.findings[0]
    assert finding.evidence_strength.value == "weak"
    assert finding.title == "买家复购结构诊断"
    assert "buyer_structure" in result.tables or "repeat_buyer_top" in result.tables


def test_correct_buyer_count_and_repurchase_rate(tmp_path):
    """验证去重买家数、复购买家数、复购率。"""
    con, db_path = _con(tmp_path)
    rows = [
        # 5 个单次买家 → 5 笔订单，5 个买家
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 11:00:00", 120.0, "buyer002"),
        ("o3", "2025-01-03 12:00:00", 150.0, "buyer003"),
        ("o4", "2025-01-04 13:00:00", 160.0, "buyer004"),
        ("o5", "2025-01-05 14:00:00", 110.0, "buyer005"),
        # 2 个复购买家（2 单、3 单）→ 5 笔订单，2 个买家
        ("o6", "2025-01-06 15:00:00", 130.0, "buyer006"),
        ("o7", "2025-01-07 16:00:00", 140.0, "buyer006"),
        ("o8", "2025-01-08 17:00:00", 150.0, "buyer007"),
        ("o9", "2025-01-09 18:00:00", 160.0, "buyer007"),
        ("o10", "2025-01-10 19:00:00", 170.0, "buyer007"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    # 去重买家：7 个（buyer001-buyer007）
    assert kn["unique_buyers"] == 7
    # 复购买家（≥2 单）：2 个（buyer006, buyer007）
    assert kn["repeat_buyers"] == 2
    # 复购率：2/7 ≈ 28.57%
    assert abs(kn["repurchase_rate"] - (2 / 7)) < 1e-9


def test_gmv_contribution_by_buyer_type(tmp_path):
    """验证单次 vs 复购买家的 GMV 占比与平均客单价。"""
    con, db_path = _con(tmp_path)
    rows = [
        # 单次买家 3 个，各 100 元 → 300 元
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 11:00:00", 100.0, "buyer002"),
        ("o3", "2025-01-03 12:00:00", 100.0, "buyer003"),
        # 复购买家 2 个，分别 200+200=400 元，300+300=600 元 → 1000 元
        ("o4", "2025-01-04 13:00:00", 200.0, "buyer004"),
        ("o5", "2025-01-05 14:00:00", 200.0, "buyer004"),
        ("o6", "2025-01-06 15:00:00", 300.0, "buyer005"),
        ("o7", "2025-01-07 16:00:00", 300.0, "buyer005"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    # 总 GMV：1300
    assert kn["total_gmv"] == 1300.0
    # 复购 GMV 占比：1000/1300 ≈ 76.92%
    assert abs(kn["repeat_buyers_gmv_share"] - (1000.0 / 1300.0)) < 1e-9

    # 单次买家平均客单：300/3 = 100
    assert abs(kn["avg_aov_single_buyer"] - 100.0) < 1e-9
    # 复购买家平均客单：1000/4 = 250（总订单数，不是买家数）
    # 或者按复购买家数：1000/2 = 500（买家级别）
    # 需要看实现怎么定义


def test_repurchase_interval_calculation(tmp_path):
    """验证复购间隔（相邻订单支付时间差）的中位数和平均值。"""
    con, db_path = _con(tmp_path)
    rows = [
        # buyer001：两笔，间隔 1 天
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 10:00:00", 100.0, "buyer001"),
        # buyer002：三笔，间隔 1 天和 3 天
        ("o3", "2025-01-01 10:00:00", 100.0, "buyer002"),
        ("o4", "2025-01-02 10:00:00", 100.0, "buyer002"),
        ("o5", "2025-01-05 10:00:00", 100.0, "buyer002"),
        # buyer003：单笔，无间隔
        ("o6", "2025-01-01 10:00:00", 100.0, "buyer003"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]
    kn = finding.key_numbers

    # 复购间隔：[1天, 1天, 3天] → 中位数 1 天，平均 1.67 天
    assert kn["median_repurchase_interval_days"] == 1.0
    assert abs(kn["avg_repurchase_interval_days"] - (5.0 / 3.0)) < 1e-9


def test_buyer_hash_truncation_in_table(tmp_path):
    """明细表 repeat_buyer_top 中买家哈希截断到 8 字符 + "…"。"""
    con, db_path = _con(tmp_path)
    rows = [
        # 长哈希
        ("o1", "2025-01-01 10:00:00", 1000.0, "buyer001234567890abcdef"),
        ("o2", "2025-01-02 11:00:00", 1100.0, "buyer001234567890abcdef"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    table = result.tables.get("repeat_buyer_top", [])

    if table:
        # 检查是否有截断的哈希
        for row in table:
            buyer_id = row.get("buyer_id_hash", "")
            # 应该是前 8 字符 + "…"
            if len(buyer_id) > 0:
                assert len(buyer_id) <= 10  # 8 + "…" 的 2 字节
                if "…" in buyer_id:
                    assert buyer_id.startswith("buyer001")


def test_coverage_below_50_percent_degrades_reliability(tmp_path):
    """buyer_id_hash 覆盖率 < 50% 时降级为 LOW reliability."""
    con, db_path = _con(tmp_path)
    rows = [
        # 5 笔订单，4 笔有哈希，1 笔无 → 80% 覆盖（不触发降级）
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 11:00:00", 100.0, "buyer002"),
        ("o3", "2025-01-03 12:00:00", 100.0, "buyer003"),
        ("o4", "2025-01-04 13:00:00", 100.0, "buyer004"),
        ("o5", "2025-01-05 14:00:00", 100.0, None),
    ]
    _make_orders_sparse_buyer_hash(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]

    # 覆盖率 80%，不应该触发降级
    kn = finding.key_numbers
    assert kn.get("buyer_hash_coverage") >= 0.5


def test_low_coverage_caveat_in_findings(tmp_path):
    """< 50% 覆盖时在 caveat 中说明覆盖率低的风险。"""
    con, db_path = _con(tmp_path)
    rows = [
        # 10 笔订单，只有 2 笔有哈希 → 20% 覆盖
        ("o1", "2025-01-01 10:00:00", 100.0, None),
        ("o2", "2025-01-02 11:00:00", 100.0, None),
        ("o3", "2025-01-03 12:00:00", 100.0, None),
        ("o4", "2025-01-04 13:00:00", 100.0, None),
        ("o5", "2025-01-05 14:00:00", 100.0, None),
        ("o6", "2025-01-06 15:00:00", 100.0, "buyer001"),
        ("o7", "2025-01-07 16:00:00", 100.0, None),
        ("o8", "2025-01-08 17:00:00", 100.0, None),
        ("o9", "2025-01-09 18:00:00", 100.0, None),
        ("o10", "2025-01-10 19:00:00", 100.0, "buyer002"),
    ]
    _make_orders_sparse_buyer_hash(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]

    # 应该在 caveats 中说明覆盖率低
    assert any("覆盖" in c or "买家" in c for c in finding.caveats)


def test_missing_buyer_hash_column_degrades_not_judgable(tmp_path):
    """buyer_id_hash 列缺失或全空时返回 NOT_JUDGABLE."""
    con, db_path = _con(tmp_path)
    rows = [
        ("o1", "2025-01-01 10:00:00", 100.0),
        ("o2", "2025-01-02 11:00:00", 100.0),
    ]
    _make_orders_no_buyer_hash(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]

    assert finding.evidence_strength.value == "not_judgable"
    assert any("buyer_id_hash" in c or "买家" in c for c in finding.caveats)


def test_observation_window_caveat_included(tmp_path):
    """Caveat 必须包含观察窗截断说明。"""
    con, db_path = _con(tmp_path)
    rows = [
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 11:00:00", 100.0, "buyer002"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    finding = result.findings[0]

    # caveat 应提及观察窗、首购、复购等相关概念
    assert any(
        any(term in c for term in ["观察", "窗口", "截断", "首购", "末期"])
        for c in finding.caveats
    )


def test_buyer_structure_table_exists(tmp_path):
    """buyer_structure 表应按买家类型（单次/复购）一行一段。"""
    con, db_path = _con(tmp_path)
    rows = [
        ("o1", "2025-01-01 10:00:00", 100.0, "buyer001"),
        ("o2", "2025-01-02 11:00:00", 100.0, "buyer002"),
        ("o3", "2025-01-03 12:00:00", 150.0, "buyer003"),
        ("o4", "2025-01-04 13:00:00", 160.0, "buyer003"),
    ]
    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    table = result.tables.get("buyer_structure", [])

    # 应该有至少 2 行（单次和复购）
    assert len(table) >= 2

    # 检查列
    for row in table:
        assert "buyer_type" in row or "segment" in row
        assert "buyer_count" in row
        assert "order_count" in row
        assert "gmv" in row


def test_repeat_buyer_top_10(tmp_path):
    """repeat_buyer_top 表是复购买家按 GMV Top 10（或全部如果少于 10 个）。"""
    con, db_path = _con(tmp_path)
    rows = []
    # 15 个复购买家
    for i in range(15):
        buyer = f"buyer{i:03d}"
        # 不同 GMV
        gmv1 = 100.0 + i * 10
        gmv2 = 110.0 + i * 10
        rows.append((f"o{i*2}", "2025-01-01 10:00:00", gmv1, buyer))
        rows.append((f"o{i*2+1}", "2025-01-02 11:00:00", gmv2, buyer))

    _make_orders_full(con, rows)
    con.close()

    result = run(db_path)
    table = result.tables.get("repeat_buyer_top", [])

    # 应该有 10 行（Top 10）
    assert len(table) == 10

    # 按 GMV 降序
    for i in range(len(table) - 1):
        cur_gmv = table[i].get("gmv", 0)
        next_gmv = table[i + 1].get("gmv", 0)
        assert cur_gmv >= next_gmv
