"""Text-mining primitives — emergent themes, polarity, objection→hook.

Pure-stdlib, never-raise. Covers normal + degenerate + never-raise per the spec.
"""
from xhs_ceramics_analytics.analytics.text_mining import (
    emergent_themes,
    objection_to_hook,
    polarity,
    theme_period_series,
)


# ---- emergent_themes --------------------------------------------------------


def test_emergent_themes_ranks_recurring_ngram():
    texts = [
        "这个容量多大呀",
        "请问容量是多少",
        "容量够用吗",
        "颜色很好看",
    ]
    themes = emergent_themes(texts, top_k=5, min_df=2)
    terms = {t["term"] for t in themes}
    # "容量" recurs across 3 of 4 docs → must surface as an emergent theme.
    assert "容量" in terms
    top = next(t for t in themes if t["term"] == "容量")
    assert top["doc_count"] == 3
    assert top["coverage"] == 3 / 4
    assert top["score"] > 0


def test_emergent_themes_filters_stopword_ngrams():
    # Particle-led bigrams like "的了"/"是我" must not out-rank content themes.
    texts = ["这个是我的了啊", "这个是我的了啊", "釉面很细腻", "釉面手感好"]
    themes = emergent_themes(texts, top_k=10, min_df=2)
    terms = {t["term"] for t in themes}
    assert "釉面" in terms
    assert all(t["term"][0] not in "的了是我这个啊" for t in themes)


def test_emergent_themes_drops_substring_at_equal_coverage():
    # "微波" appears only ever inside "微波炉" → same documents, same doc_count.
    # The shorter span carries no extra information and must not co-survive,
    # regardless of the score-tie sort order (bigram sorts before its trigram).
    texts = ["能进微波炉吗", "可以微波炉加热吗"]
    themes = emergent_themes(texts, top_k=10, min_df=2)
    terms = {t["term"] for t in themes}
    assert "微波炉" in terms
    assert "微波" not in terms


def test_emergent_themes_keeps_substring_with_extra_coverage():
    # "微波" reaches a doc "微波加热" that "微波炉" does not → higher doc_count,
    # so it carries independent coverage and must be kept alongside "微波炉".
    texts = ["能进微波炉吗", "可以微波炉加热吗", "支持微波加热"]
    themes = emergent_themes(texts, top_k=10, min_df=2)
    terms = {t["term"] for t in themes}
    assert "微波" in terms
    assert "微波炉" in terms


def test_emergent_themes_respects_min_df():
    texts = ["磕碰了一下", "包装很好"]
    # Nothing recurs in ≥2 docs → empty at min_df=2.
    assert emergent_themes(texts, min_df=2) == []


def test_emergent_themes_never_raises_on_degenerate():
    assert emergent_themes([]) == []
    assert emergent_themes(["", "   ", None]) == []
    assert emergent_themes(["!!!", "123 abc"]) == []


def test_emergent_themes_cold_start_falls_back_to_seed_lexicon():
    # Too sparse to mine (nothing recurs), but a seed lexicon rescues cold start:
    # each seed term that appears in ≥1 doc becomes a fallback theme.
    texts = ["价格多少", "怎么下单"]
    seed = {"price": ("价格", "多少钱"), "link": ("下单", "链接")}
    themes = emergent_themes(texts, min_df=2, seed_lexicon=seed)
    terms = {t["term"] for t in themes}
    assert "price" in terms and "link" in terms
    assert all(t["source"] == "seed" for t in themes)


def test_emergent_themes_prefers_mined_over_seed():
    texts = ["容量多大", "容量多少", "容量够吗"]
    seed = {"price": ("价格",)}
    themes = emergent_themes(texts, min_df=2, seed_lexicon=seed)
    # Real mined themes exist → seed fallback stays dormant.
    assert any(t["term"] == "容量" for t in themes)
    assert all(t["source"] == "mined" for t in themes)


# ---- theme_period_series ----------------------------------------------------


def test_theme_period_series_counts_docs_per_period_sorted():
    dated = [
        ("2026-W01", "问一下容量"),
        ("2026-W01", "容量多大"),
        ("2026-W01", "颜色好看"),
        ("2026-W02", "容量够吗"),
        ("2026-W03", "包装好"),
    ]
    series = theme_period_series(dated, "容量")
    # One (period, doc_count) point per period, sorted; zero-mention periods
    # still emit 0.0 so a fading theme reads as decline, not absence.
    assert series == [("2026-W01", 2.0), ("2026-W02", 1.0), ("2026-W03", 0.0)]


def test_theme_period_series_degrades_on_empty_or_missing():
    assert theme_period_series([], "容量") == []
    assert theme_period_series([("2026-W01", "容量")], "") == []
    # None/blank periods are skipped; None text counts as no-mention, never raises.
    series = theme_period_series([(None, "容量"), ("2026-W01", None)], "容量")
    assert series == [("2026-W01", 0.0)]


# ---- polarity ---------------------------------------------------------------


_POS = ("好", "喜欢", "精致", "超值")
_NEG = ("色差", "磕碰", "破损", "失望")


def test_polarity_positive_and_negative():
    assert polarity("质量很好我喜欢", _POS, _NEG) > 0
    assert polarity("有色差还磕碰了很失望", _POS, _NEG) < 0


def test_polarity_neutral_and_empty_are_zero():
    assert polarity("请问什么时候发货", _POS, _NEG) == 0.0
    assert polarity("", _POS, _NEG) == 0.0
    assert polarity(None, _POS, _NEG) == 0.0


def test_polarity_bounded_between_minus_one_and_one():
    p = polarity("好好好色差", _POS, _NEG)
    assert -1.0 <= p <= 1.0


# ---- objection_to_hook ------------------------------------------------------


def test_objection_to_hook_maps_known_objections():
    assert objection_to_hook("色差") is not None
    assert objection_to_hook("担心磕碰") is not None  # substring match
    assert objection_to_hook("能进微波炉吗") is not None


def test_objection_to_hook_unknown_returns_none():
    assert objection_to_hook("容量") is None
    assert objection_to_hook("") is None
    assert objection_to_hook(None) is None
