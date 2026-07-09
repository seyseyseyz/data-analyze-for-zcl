"""A user-view table column that is entirely 暂无数据 across every shown row is
noise — it widens the grid and tells the reader nothing. _table_view drops a
column whose displayed cells are all None, but never empties the table (an
all-blank table keeps its columns; a blank grid is worse than a sparse one).
"""

from xhs_ceramics_analytics.reporting.html import _table_view


def test_all_none_column_is_dropped():
    rows = [
        {"sku": "A", "gmv": 1000.0, "refund_amount_pay": None},
        {"sku": "B", "gmv": 800.0, "refund_amount_pay": None},
    ]
    view = _table_view("sku_structure", rows)
    names = [c["name"] for c in view["user_columns"]]
    assert "refund_amount_pay" not in names
    assert "sku" in names and "gmv" in names


def test_partially_filled_column_is_kept():
    rows = [
        {"sku": "A", "gmv": 1000.0, "refund_amount_pay": None},
        {"sku": "B", "gmv": 800.0, "refund_amount_pay": 50.0},
    ]
    view = _table_view("sku_structure", rows)
    names = [c["name"] for c in view["user_columns"]]
    assert "refund_amount_pay" in names


def test_never_empties_the_table():
    # Every user column blank → keep them rather than render a column-less grid.
    rows = [{"a": None, "b": None}, {"a": None, "b": None}]
    view = _table_view("whatever", rows)
    names = [c["name"] for c in view["user_columns"]]
    assert names  # not empty
