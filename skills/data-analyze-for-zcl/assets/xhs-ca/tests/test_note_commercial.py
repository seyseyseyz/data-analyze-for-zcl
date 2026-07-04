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


# ---- Conversion zero-inflation regression (A2) ------------------------------


def test_conversion_zero_inflation_uses_positive_baseline(tmp_path):
    con, db_path = _con(tmp_path)
    rows = []
    # 3 star converters (10% conversion).
    for i in range(3):
        rows.append((f"s{i}", f"star{i}", "种草", "碗", 1000.0, 5000.0, 100.0, 100.0, 0.0, 0.0))
    # 1 high-traffic low-conversion note (0.1% on 100k reads → confidently low).
    rows.append(("low", "低转化", "种草", "碗", 100000.0, 2000.0, 100.0, 100.0, 0.0, 0.0))
    # 6 zero-conversion notes that still drew reads (the zero-inflation mass).
    for i in range(6):
        rows.append((f"z{i}", f"zero{i}", "种草", "碗", 500.0, 0.0, 0.0, 0.0, 0.0, 0.0))
    _make_notes_full(con, rows)
    con.close()
    result = run(db_path)

    conv = next(f for f in result.findings if f.title == "转化效率分布")
    kn = conv.key_numbers
    assert kn["notes_with_orders"] == 4
    assert kn["notes_with_reads"] == 10
    assert abs(kn["converting_share"] - 0.4) < 1e-9
    # Baseline is the positive traffic-weighted rate, never the zero median.
    assert kn["baseline_conversion"] is not None and kn["baseline_conversion"] > 0
    # The high-traffic-low-conversion rule now actually fires (was always 0).
    assert kn["high_traffic_low_conv_count"] == 1
    outliers = result.tables["note_conversion_outliers"]
    assert any(
        r["note_id"] == "low" and r["outlier_type"] == "high_traffic_low_conv"
        for r in outliers
    )
    assert "仅" in conv.conclusion


def test_refund_fdr_flags_only_strong_outliers(tmp_path):
    con, db_path = _con(tmp_path)
    rows = []
    # 10 baseline notes at 10% refund.
    for i in range(10):
        rows.append((f"b{i}", f"base{i}", "种草", "碗", 1000.0, 5000.0, 100.0, 100.0, 0.10, 10.0))
    # One genuinely high-refund note: 50% on 200 orders → strongly significant.
    rows.append(("hot", "高退款", "种草", "碗", 2000.0, 8000.0, 200.0, 200.0, 0.50, 100.0))
    # One borderline note just above baseline on a tiny sample → not significant.
    rows.append(("bl", "临界", "种草", "碗", 200.0, 400.0, 10.0, 10.0, 0.20, 2.0))
    _make_notes_full(con, rows)
    con.close()
    result = run(db_path)

    refund = next(f for f in result.findings if f.title == "笔记级退款异常")
    kn = refund.key_numbers
    assert "fdr_survivors" in kn
    assert "expected_false_positives" in kn
    assert kn["fdr_survivors"] <= kn["high_refund_note_count"]
    outliers = result.tables["note_refund_outliers"]
    hot = next(r for r in outliers if r["note_id"] == "hot")
    assert hot["fdr_significant"] is True
    assert kn["fdr_survivors"] >= 1
    # BH excludes the borderline tiny-sample note.
    bl = next(r for r in outliers if r["note_id"] == "bl")
    assert bl["fdr_significant"] is False


# ---- Off-note referral attribution (shop-page / live-room) ------------------


def _make_notes_with_referral(con, rows):
    con.execute(
        """
        CREATE TABLE notes (
          note_id VARCHAR,
          title VARCHAR,
          reads DOUBLE,
          note_gmv DOUBLE,
          note_paid_orders DOUBLE,
          引流店铺主页次数 DOUBLE,
          引流店铺主页支付金额 DOUBLE,
          引流直播间次数 DOUBLE,
          引流直播间支付金额 DOUBLE
        )
        """
    )
    con.executemany(
        "INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows
    )


def test_referral_finding_surfaces_off_note_gmv(tmp_path):
    con, db_path = _con(tmp_path)
    rows = [
        # note_id, title, reads, note_gmv, note_paid_orders,
        # 店铺主页次数, 店铺主页支付金额, 直播间次数, 直播间支付金额
        ("n1", "引流强笔记", 5000.0, 10000.0, 40.0, 1200.0, 6000.0, 0.0, 0.0),
        ("n2", "引流中笔记", 4000.0, 8000.0, 30.0, 800.0, 4000.0, 0.0, 0.0),
        ("n3", "无引流笔记", 3000.0, 2000.0, 10.0, 0.0, 0.0, 0.0, 0.0),
    ]
    _make_notes_with_referral(con, rows)
    con.close()
    result = run(db_path)

    referral = next(f for f in result.findings if f.title == "笔记站外引流成交")
    kn = referral.key_numbers
    assert abs(kn["direct_note_gmv"] - 20000.0) < 1e-9
    assert abs(kn["shop_referral_gmv"] - 10000.0) < 1e-9
    # 10000 / 20000 = 0.5 of the direct caliber, surfaced as a separate lens.
    assert abs(kn["shop_referral_share"] - 0.5) < 1e-9
    assert kn["live_referral_gmv"] == 0.0
    # Table ranks notes by shop-page-referral GMV; the zero-referral note is excluded.
    table = result.tables["note_referral_attribution"]
    assert [r["note_id"] for r in table] == ["n1", "n2"]
    # Caliber caveat must warn against summing the two lenses.
    assert any("不" in c and ("相加" in c or "重复" in c) for c in referral.caveats)


def test_referral_finding_skipped_when_columns_absent(tmp_path):
    con, db_path = _con(tmp_path)
    # _make_notes_full has no referral columns → finding degrades away silently.
    _make_notes_full(
        con,
        [("n1", "t1", "种草", "碗", 1000.0, 5000.0, 40.0, 40.0, 0.05, 2.0)],
    )
    con.close()
    result = run(db_path)
    assert "笔记站外引流成交" not in {f.title for f in result.findings}
    assert "note_referral_attribution" not in result.tables


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
