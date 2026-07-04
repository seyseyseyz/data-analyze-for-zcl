"""comment_demand emergent-theme upgrade (Phase 3 / B2).

The seed-lexicon grouping (Finding 1) stays intact; these tests pin the new
emergent-theme finding: n-gram themes + polarity + objection→hook, all
observational.
"""
from pathlib import Path

from xhs_ceramics_analytics.analysis.comment_demand import run
from xhs_ceramics_analytics.db.duck import connect


def _con(tmp_path: Path):
    db_path = tmp_path / "comments.duckdb"
    return connect(db_path), db_path


def _make_comments(con, texts):
    con.execute("CREATE TABLE comments (note_id VARCHAR, comment_text VARCHAR)")
    con.executemany(
        "INSERT INTO comments VALUES (?, ?)",
        [(f"n{i}", t) for i, t in enumerate(texts)],
    )


def _make_dated_comments(con, dated):
    con.execute(
        "CREATE TABLE comments (note_id VARCHAR, comment_time VARCHAR, comment_text VARCHAR)"
    )
    con.executemany(
        "INSERT INTO comments VALUES (?, ?, ?)",
        [(f"n{i}", ts, t) for i, (ts, t) in enumerate(dated)],
    )


def test_emergent_themes_finding_surfaces_recurring_theme(tmp_path):
    con, db_path = _con(tmp_path)
    texts = [
        "这个容量多大呀",
        "请问容量是多少毫升",
        "容量够用吗想买",
        "有没有色差担心",
        "会不会有色差呢",
        "颜色好看喜欢",
    ]
    _make_comments(con, texts)
    con.close()

    result = run(db_path)

    # Finding 1 (seed grouping) is preserved as the first finding.
    assert result.findings[0].title == "评论需求分组已提取"
    assert "comment_demands" in result.tables

    theme_finding = next(f for f in result.findings if f.title == "涌现需求主题与异议")
    rows = result.tables["comment_emergent_themes"]
    terms = {r["term"] for r in rows}
    assert "容量" in terms
    assert "色差" in terms
    # Objection themes carry a content hook; demand themes do not.
    color = next(r for r in rows if r["term"] == "色差")
    assert color["content_hook"]  # non-empty
    capacity = next(r for r in rows if r["term"] == "容量")
    assert not capacity["content_hook"]
    # Every theme row carries a polarity in [-1, 1].
    assert all(-1.0 <= r["polarity"] <= 1.0 for r in rows)
    assert theme_finding.key_numbers["objection_theme_count"] >= 1


def test_emergent_themes_carry_frequency_trend(tmp_path):
    con, db_path = _con(tmp_path)
    # "色差" complaints climb week over week; every theme row must carry a trend
    # label, and a rising objection is escalated in the conclusion.
    dated = []
    weeks = ["2026-01-05", "2026-01-12", "2026-01-19", "2026-01-26", "2026-02-02"]
    # Vary the phrasing so "色差" (not a longer 4-gram) is the recurring span.
    variants = ["有色差", "色差明显吗", "担心色差", "会不会色差", "色差严重"]
    for w_i, day in enumerate(weeks):
        for k in range(w_i + 1):
            dated.append((day, variants[k % len(variants)]))
        dated.append((day, "颜色好看很喜欢"))
    _make_dated_comments(con, dated)
    con.close()

    result = run(db_path)
    rows = result.tables["comment_emergent_themes"]
    assert all("trend" in r for r in rows)
    color = next(r for r in rows if r["term"] == "色差")
    assert color["trend"] == "上升"
    theme_finding = next(f for f in result.findings if f.title == "涌现需求主题与异议")
    assert theme_finding.key_numbers["rising_objection_count"] >= 1
    assert "上升" in theme_finding.conclusion


def test_emergent_themes_trend_unknown_without_comment_time(tmp_path):
    con, db_path = _con(tmp_path)
    # No comment_time column → trend degrades to 趋势不明, never raises.
    _make_comments(con, ["有色差担心", "会不会有色差呢", "颜色好看喜欢"])
    con.close()
    result = run(db_path)
    rows = result.tables["comment_emergent_themes"]
    assert all(r["trend"] == "趋势不明" for r in rows)


def test_emergent_themes_finding_absent_without_comments(tmp_path):
    con, db_path = _con(tmp_path)
    con.execute("CREATE TABLE comments (note_id VARCHAR, comment_text VARCHAR)")
    con.close()
    result = run(db_path)
    titles = {f.title for f in result.findings}
    assert "涌现需求主题与异议" not in titles
    # Seed grouping finding still emitted (degraded).
    assert result.findings[0].title == "评论需求分组已提取"


def test_emergent_themes_cold_start_uses_seed_fallback(tmp_path):
    con, db_path = _con(tmp_path)
    # Two short, non-overlapping comments → nothing to mine, but seed lexicon
    # rescues a demand read.
    _make_comments(con, ["价格多少", "怎么下单"])
    con.close()
    result = run(db_path)
    theme_finding = next(
        (f for f in result.findings if f.title == "涌现需求主题与异议"), None
    )
    assert theme_finding is not None
    rows = result.tables["comment_emergent_themes"]
    assert all(r["source"] == "seed" for r in rows)
