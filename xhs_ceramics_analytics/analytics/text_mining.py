"""Text-mining primitives — emergent themes, lexicon polarity, objection hooks.

Chinese comments have no word boundaries, so a fixed keyword list only finds what
we already thought to look for. These pure-stdlib helpers surface *emergent*
themes (recurring character n-grams ranked by frequency × document coverage),
score sentiment against seed lexicons, and map known objections to content hooks.

Never raise — degenerate input (empty, whitespace, non-CJK, None) degrades to an
empty result or a neutral 0.0. No third-party NLP, no I/O.
"""
import re

# CJK ideograph run — everything outside is a boundary (spaces, punctuation,
# latin, digits). N-grams are only formed *within* a run so "好\n色差" never
# fabricates a cross-boundary "好色".
_CJK_RUN = re.compile(r"[一-鿿]+")

# Function characters/particles. An n-gram that starts or ends on one of these is
# almost always a grammatical fragment ("的了", "是我", "这个") rather than a
# content theme, so it is filtered before ranking. Kept deliberately small — over-
# stopping would swallow real themes.
_STOP_CHARS = frozenset(
    "的了是我你他她它们这那有在和就都也很啊吗呢吧呀哦嗯个不还会能要想说"
    "一之与而及或把被给让对从向到以为上下里外中等着过吧么什怎请问哪"
)


def emergent_themes(
    texts: list[str | None],
    top_k: int = 10,
    min_df: int = 2,
    ngram_range: tuple[int, int] = (2, 4),
    stopwords: frozenset[str] | None = None,
    seed_lexicon: dict[str, tuple[str, ...]] | None = None,
) -> list[dict]:
    """Rank emergent Chinese n-gram themes by frequency × document coverage.

    ``texts`` is one string per document. Character n-grams of length
    ``ngram_range`` are formed within each CJK run; an n-gram is kept only when it
    appears in at least ``min_df`` documents and does not start/end on a stop
    character. Each theme dict carries ``term``, ``count`` (total occurrences),
    ``doc_count`` (documents containing it), ``coverage`` (doc_count / n_docs),
    ``score`` (count × coverage) and ``source`` (``"mined"``). Returns the top
    ``top_k`` by score, then count, then term.

    ``seed_lexicon`` (group → seed terms) is a *cold-start* fallback only: when
    mining yields nothing (too few or too short comments), each seed group that
    appears in ≥1 document becomes a ``source="seed"`` theme keyed by the group
    name, so a sparse export still gets a demand read. Empty/degenerate input →
    ``[]``. Never raises.
    """
    stops = stopwords if stopwords is not None else _STOP_CHARS
    docs = [t for t in texts if isinstance(t, str) and t.strip()]
    n_docs = len(docs)
    if n_docs == 0:
        return []

    lo, hi = ngram_range
    counts: dict[str, int] = {}
    doc_counts: dict[str, int] = {}
    for text in docs:
        seen: set[str] = set()
        for run in _CJK_RUN.findall(text):
            for size in range(lo, hi + 1):
                for i in range(len(run) - size + 1):
                    gram = run[i : i + size]
                    if gram[0] in stops or gram[-1] in stops:
                        continue
                    counts[gram] = counts.get(gram, 0) + 1
                    seen.add(gram)
        for gram in seen:
            doc_counts[gram] = doc_counts.get(gram, 0) + 1

    themes = []
    for gram, doc_count in doc_counts.items():
        if doc_count < min_df:
            continue
        count = counts[gram]
        coverage = doc_count / n_docs
        themes.append(
            {
                "term": gram,
                "count": count,
                "doc_count": doc_count,
                "coverage": coverage,
                "score": count * coverage,
                "source": "mined",
            }
        )
    themes.sort(key=lambda t: (-t["score"], -t["count"], t["term"]))
    mined = _dedupe_substrings(themes)[:top_k]
    if mined or not seed_lexicon:
        return mined
    return _seed_themes(docs, n_docs, seed_lexicon, top_k)


def _seed_themes(
    docs: list[str], n_docs: int, seed_lexicon: dict[str, tuple[str, ...]], top_k: int
) -> list[dict]:
    """Cold-start fallback: count documents hitting each seed group's terms."""
    themes = []
    for group, terms in seed_lexicon.items():
        count = 0
        doc_count = 0
        for text in docs:
            hits = sum(text.count(w) for w in terms)
            if hits:
                count += hits
                doc_count += 1
        if doc_count:
            coverage = doc_count / n_docs
            themes.append(
                {
                    "term": group,
                    "count": count,
                    "doc_count": doc_count,
                    "coverage": coverage,
                    "score": count * coverage,
                    "source": "seed",
                }
            )
    themes.sort(key=lambda t: (-t["score"], -t["count"], t["term"]))
    return themes[:top_k]


def _dedupe_substrings(themes: list[dict]) -> list[dict]:
    """Drop a shorter theme when a longer theme covering the same documents exists
    — "微波" carries no information once "微波炉" is present at equal doc_count.

    Compared against the *whole* set, not just already-kept themes: on a score
    tie the shorter n-gram sorts first, so an already-kept-only check would let
    the bigram outlive its trigram. Equal-length spans never eliminate each
    other (strict ``<``), and a shorter span with extra coverage (higher
    doc_count) is kept as independent signal. Survivor order is preserved
    (themes arrive pre-sorted by score)."""
    return [
        t
        for t in themes
        if not any(
            other is not t
            and t["term"] in other["term"]
            and len(t["term"]) < len(other["term"])
            and t["doc_count"] == other["doc_count"]
            for other in themes
        )
    ]


def theme_period_series(
    dated_texts: list[tuple[str | None, str | None]],
    term: str,
) -> list[tuple[str, float]]:
    """Per-period document frequency of ``term`` as a ``(period, doc_count)`` series.

    ``dated_texts`` is ``(period_key, text)`` pairs — the caller buckets comment
    timestamps into whatever period key it wants (ISO week, month, …); this
    primitive stays time-representation agnostic. Every period that has *any*
    comment emits a point, so a period where the theme vanishes emits ``0.0``
    rather than dropping out — that lets a fading theme read as decline instead
    of absence. Points are sorted by period key, ready for
    :func:`analytics.trends.trend_summary`. Empty input or empty ``term`` →
    ``[]``. Never raises.
    """
    if not isinstance(term, str) or not term:
        return []
    buckets: dict[str, int] = {}
    for period, text in dated_texts:
        if not isinstance(period, str) or not period:
            continue
        hit = 1 if isinstance(text, str) and term in text else 0
        buckets[period] = buckets.get(period, 0) + hit
    return [(period, float(buckets[period])) for period in sorted(buckets)]


def polarity(
    text: str | None,
    pos_lexicon: tuple[str, ...],
    neg_lexicon: tuple[str, ...],
) -> float:
    """Lexicon polarity in ``[-1, 1]``: ``(pos - neg) / (pos + neg)`` over lexicon
    hits. Returns ``0.0`` when the text is empty/None or hits no lexicon term
    (neutral). Never raises."""
    if not isinstance(text, str) or not text:
        return 0.0
    pos = sum(text.count(w) for w in pos_lexicon)
    neg = sum(text.count(w) for w in neg_lexicon)
    total = pos + neg
    if total == 0:
        return 0.0
    return (pos - neg) / total


# Known ceramics objections → the content hook that pre-empts them. Substring
# match on the theme, longest-key-first so "微波炉" beats a hypothetical "微波".
_OBJECTION_HOOKS: dict[str, str] = {
    "色差": "拍摄标注自然光/影棚色温，附实物对比图，说明批次釉色差异属正常。",
    "磕碰": "展示加厚防震包装与破损包赔承诺，出镜开箱验货环节。",
    "破损": "展示加厚防震包装与破损包赔承诺，出镜开箱验货环节。",
    "尺寸": "口径/高度/容量三视图标注，附与常见物品同框比例参照。",
    "釉面": "特写釉面工艺与手感，说明开片/针眼属手工釉正常特征。",
    "微波炉": "标注是否可微波，附材质与耐温说明。",
    "洗碗机": "标注是否可进洗碗机，说明日常清洗与保养方式。",
    "掉色": "说明釉下彩工艺不掉色，附洗涤前后对比。",
    "重量": "标注单件净重，说明手感与日常使用的关系。",
}


def objection_to_hook(theme: str | None) -> str | None:
    """Content hook that answers a known objection ``theme`` (substring match).
    Returns ``None`` when the theme maps to no known objection or is empty. Never
    raises."""
    if not isinstance(theme, str) or not theme:
        return None
    for key in sorted(_OBJECTION_HOOKS, key=len, reverse=True):
        if key in theme:
            return _OBJECTION_HOOKS[key]
    return None
