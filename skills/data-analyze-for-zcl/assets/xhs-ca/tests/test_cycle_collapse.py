"""首购周期 windows are cumulative (180天 ⊂ 365天); when all first purchases fall
inside the narrower window the wider one repeats identical counts and the table
showed two duplicate rows. _collapse_identical_cycles merges adjacent equal-count
rows into one whose label joins both window names.
"""

from xhs_ceramics_analytics.analysis.audience_structure import (
    _collapse_identical_cycles,
)


def _row(cycle, visitors, payers, conv):
    return {
        "first_purchase_cycle": cycle,
        "visitors": visitors,
        "payers": payers,
        "conversion": conv,
        "ci_low": None,
        "ci_high": None,
    }


def test_identical_windows_merge_into_one_row():
    rows = [_row("180天", 100.0, 20.0, 0.2), _row("365天", 100.0, 20.0, 0.2)]
    out = _collapse_identical_cycles(rows)
    assert len(out) == 1
    assert out[0]["first_purchase_cycle"] == "180天/365天"
    assert out[0]["visitors"] == 100.0
    assert out[0]["payers"] == 20.0


def test_distinct_windows_are_kept_separate():
    rows = [_row("365天", 150.0, 30.0, 0.2), _row("180天", 100.0, 25.0, 0.25)]
    out = _collapse_identical_cycles(rows)
    assert [r["first_purchase_cycle"] for r in out] == ["365天", "180天"]


def test_same_visitors_but_different_payers_not_merged():
    rows = [_row("180天", 100.0, 20.0, 0.2), _row("365天", 100.0, 25.0, 0.25)]
    out = _collapse_identical_cycles(rows)
    assert len(out) == 2


def test_empty_input_is_empty():
    assert _collapse_identical_cycles([]) == []
