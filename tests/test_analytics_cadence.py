"""Posting-cadence primitives — best publish window net of note-age drift."""
from xhs_ceramics_analytics.analytics.cadence import posting_windows


def test_posting_windows_ranks_by_mean_and_guards_min_n():
    # Three groups; group A clearly outperforms. Group C has only 1 obs and must be
    # dropped by the min_n guard so a single lucky post never crowns a window.
    obs = [
        ("A", 0, 100.0), ("A", 1, 120.0), ("A", 2, 110.0),
        ("B", 0, 40.0), ("B", 1, 50.0), ("B", 2, 45.0),
        ("C", 0, 999.0),
    ]
    windows = posting_windows(obs, min_n=3, detrend=False)
    groups = [w["group"] for w in windows]
    assert groups == ["A", "B"]  # C dropped, A first
    assert windows[0]["n"] == 3
    assert windows[0]["mean"] == 110.0
    assert windows[0]["lift"] > 0  # above grand mean
    assert windows[1]["lift"] < 0


def test_posting_windows_detrend_removes_age_drift():
    # Reads accumulate with age: earlier posts (low order) have MORE reads purely
    # from having been live longer. Group EARLY is all early posts, LATE all late.
    # Raw means would crown EARLY; detrending against order must neutralize the
    # drift so neither window wins on age alone (lift ~ 0 for both).
    obs = [
        ("EARLY", 0, 300.0), ("EARLY", 1, 290.0), ("EARLY", 2, 280.0),
        ("LATE", 8, 120.0), ("LATE", 9, 110.0), ("LATE", 10, 100.0),
    ]
    raw = posting_windows(obs, min_n=3, detrend=False)
    raw_early = next(w for w in raw if w["group"] == "EARLY")
    assert raw_early["lift"] > 50  # raw view: EARLY looks far better

    detrended = posting_windows(obs, min_n=3, detrend=True)
    for w in detrended:
        assert abs(w["lift"]) < 20  # drift removed → windows near-tied


def test_posting_windows_ignores_non_finite_values():
    obs = [
        ("A", 0, 10.0), ("A", 1, None), ("A", 2, float("nan")), ("A", 3, 12.0),
        ("A", 4, 14.0),
    ]
    windows = posting_windows(obs, min_n=3, detrend=False)
    assert len(windows) == 1
    assert windows[0]["n"] == 3  # only the 3 finite values counted
    assert windows[0]["mean"] == 12.0


def test_posting_windows_degrades_on_empty():
    assert posting_windows([], min_n=3) == []
    assert posting_windows([("A", 0, None)], min_n=1) == []


def test_posting_windows_tuple_group_keys_sort_stably():
    # (weekday, slot) keys with equal means must fall back to a stable group sort.
    obs = [
        ((0, "晚"), 0, 50.0), ((0, "晚"), 1, 50.0),
        ((3, "早"), 0, 50.0), ((3, "早"), 1, 50.0),
    ]
    windows = posting_windows(obs, min_n=2, detrend=False)
    assert [w["group"] for w in windows] == [(0, "晚"), (3, "早")]
