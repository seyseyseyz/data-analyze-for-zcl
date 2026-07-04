"""Self-referential benchmark primitives (Phase 4 / C1).

No external industry data exists for this shop, so "good/bad" is anchored to the
account's *own* recent history: where does today's value sit in its own past
distribution. Pure-stdlib, never-raise.
"""
import math

from xhs_ceramics_analytics.analytics.benchmark import self_percentile


def test_self_percentile_ranks_within_history():
    hist = [1.0, 2.0, 3.0, 4.0]
    # 3.0 beats 1.0 and 2.0 (2 of 4) and ties itself → midrank percentile.
    p = self_percentile(3.0, hist)
    assert 0.5 <= p <= 0.75


def test_self_percentile_extremes():
    hist = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert self_percentile(5.0, hist) == 0.0  # below all
    assert self_percentile(100.0, hist) == 1.0  # above all


def test_self_percentile_midrank_handles_ties():
    hist = [2.0, 2.0, 2.0, 2.0]
    # Value equals every point → sits exactly in the middle of its own mass.
    assert self_percentile(2.0, hist) == 0.5


def test_self_percentile_ignores_none_and_nonnumeric():
    hist = [1.0, None, 3.0]
    p = self_percentile(3.0, hist)
    assert 0.0 <= p <= 1.0


def test_self_percentile_degrades_on_empty_history():
    assert self_percentile(5.0, []) is None
    assert self_percentile(5.0, [None]) is None


def test_self_percentile_never_raises_on_bad_value():
    assert self_percentile(None, [1.0, 2.0]) is None
    assert self_percentile(float("nan"), [1.0, 2.0]) is None
    assert not math.isnan(self_percentile(2.0, [1.0, 2.0, 3.0]) or 0.0)
