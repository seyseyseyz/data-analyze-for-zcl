# tests/test_content_group_fdr.py
"""内容分组扫描的多重比较校正。

cover_style_effect / copy_angle_effect / content_portfolio_optimization 都按维度分组
排序：维度一多，总有组会碰巧排在前面。与 note_commercial 的退款扫描同一纪律 —— 对
每组阅读率做单侧二项检验（基线 = 全组合计阅读率），Benjamini-Hochberg 控制假阳性，
把"显著高于整体"与"只是碰巧排前面"区分开，直接标注在排序表的 read_rate_signal 列。
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.content_group_metrics import fetch_group_effects
from xhs_ceramics_analytics.analysis.registry import run_task
from xhs_ceramics_analytics.db.duck import connect


def _build_db(tmp_path: Path, notes_rows: list[tuple], features_rows: list[tuple]) -> Path:
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            "CREATE TABLE content_features (note_id VARCHAR, composition_type VARCHAR)"
        )
        con.executemany("INSERT INTO content_features VALUES (?, ?)", features_rows)
        con.execute(
            "CREATE TABLE notes (note_id VARCHAR, impressions DOUBLE, reads DOUBLE)"
        )
        con.executemany("INSERT INTO notes VALUES (?, ?, ?)", notes_rows)
    finally:
        con.close()
    return db_path


def _standard_rows():
    # 场景展示组阅读率 30%，人像组 5%，整体约 17.5% —— 前者显著、后者不显著。
    notes, features = [], []
    for i in range(10):
        notes.append((f"a{i}", 1000.0, 300.0))
        features.append((f"a{i}", "场景展示"))
        notes.append((f"b{i}", 1000.0, 50.0))
        features.append((f"b{i}", "人像出镜"))
    return notes, features


def _rows_by_group(rows):
    return {row["composition_type"]: row for row in rows}


def test_group_clearly_above_overall_is_marked_significant(tmp_path):
    notes, features = _standard_rows()
    db_path = _build_db(tmp_path, notes, features)
    con = connect(db_path)
    try:
        rows, _ = fetch_group_effects(con, "composition_type")
    finally:
        con.close()

    groups = _rows_by_group(rows)
    assert groups["场景展示"]["read_rate_signal"] == "显著高于整体"


def test_group_at_or_below_overall_is_not_flagged(tmp_path):
    notes, features = _standard_rows()
    db_path = _build_db(tmp_path, notes, features)
    con = connect(db_path)
    try:
        rows, _ = fetch_group_effects(con, "composition_type")
    finally:
        con.close()

    groups = _rows_by_group(rows)
    assert groups["人像出镜"]["read_rate_signal"] == "未见显著优势"


def test_untestable_group_keeps_null_signal(tmp_path):
    notes, features = _standard_rows()
    notes.append(("c0", None, None))  # 无曝光/阅读指标的组 → 不可检验
    features.append(("c0", "特写镜头"))
    db_path = _build_db(tmp_path, notes, features)
    con = connect(db_path)
    try:
        rows, _ = fetch_group_effects(con, "composition_type")
    finally:
        con.close()

    groups = _rows_by_group(rows)
    assert groups["特写镜头"]["read_rate_signal"] is None


def test_limitations_state_the_fdr_control(tmp_path):
    notes, features = _standard_rows()
    db_path = _build_db(tmp_path, notes, features)
    con = connect(db_path)
    try:
        _, limitations = fetch_group_effects(con, "composition_type")
    finally:
        con.close()

    assert any("BH-FDR" in item for item in limitations)


def test_signal_column_reaches_cover_style_task_table(tmp_path):
    notes, features = _standard_rows()
    db_path = _build_db(tmp_path, notes, features)

    result = run_task("cover_style_effect", db_path)

    rows = result.tables["cover_effects"]
    assert any(row.get("read_rate_signal") == "显著高于整体" for row in rows)


def test_metrics_unavailable_build_carries_no_signal_column_noise(tmp_path):
    # 无 notes 表 → 特征计数模式：不可检验，也不该宣称做了校正。
    db_path = tmp_path / "analytics.duckdb"
    con = connect(db_path)
    try:
        con.execute(
            "CREATE TABLE content_features (note_id VARCHAR, composition_type VARCHAR)"
        )
        con.execute("INSERT INTO content_features VALUES ('n1', '场景展示')")
        rows, limitations = fetch_group_effects(con, "composition_type")
    finally:
        con.close()

    assert all(row.get("read_rate_signal") is None for row in rows)
    assert not any("BH-FDR" in item for item in limitations)
