"""A user-view table column that is entirely 暂无数据 across every shown row is
noise — it widens the grid and tells the reader nothing. _table_view drops a
column whose displayed cells are all None, but never empties the table (an
all-blank table keeps its columns; a blank grid is worse than a sparse one).
"""

from xhs_ceramics_analytics.reporting.formatting import field_label
from xhs_ceramics_analytics.reporting.html import _table_view, user_table_columns


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


def test_all_blank_rendered_column_is_dropped():
    # A column whose RAW values are non-None but RENDER to a blank token (empty string,
    # a "—" placeholder) still tells the reader nothing — drop it like an all-None one.
    # The old raw `is not None` check kept these because "" / "—" are not None.
    rows = [
        {"sku": "A", "gmv": 1000.0, "note": "", "flag": "—"},
        {"sku": "B", "gmv": 800.0, "note": "", "flag": "—"},
    ]
    view = _table_view("uncurated_table", rows)
    names = [c["name"] for c in view["user_columns"]]
    assert "note" not in names
    assert "flag" not in names
    assert "sku" in names and "gmv" in names


def test_search_diagnostic_uses_merchant_facing_columns_and_labels():
    rows = [
        {
            "search_term": "陶瓷杯",
            "term_class": "机会词",
            "leak_type": "点击漏损",
            "impressions": 1000,
            "click_rate": 0.1,
            "click_to_pay_rate": 0.02,
            "effectiveness": 0.002,
            "gmv": 1200,
            "click_users_source": "真实计数",
        }
    ]

    columns = user_table_columns("search_term_opportunities", rows)

    assert columns == [
        "search_term",
        "term_class",
        "leak_type",
        "impressions",
        "click_rate",
        "click_to_pay_rate",
        "effectiveness",
        "gmv",
    ]
    assert [field_label(column) for column in columns] == [
        "搜索词",
        "搜索词分类",
        "漏损类型",
        "曝光数",
        "点击率",
        "点击支付率",
        "搜索成交效率",
        "销售额",
    ]


def test_sku_value_diagnostic_leads_with_product_identity_not_internal_flags():
    rows = [
        {
            "sku_name": "蓝花楹咖啡杯",
            "product_name": "蓝花楹系列",
            "gmv": 1200,
            "refund_amount_pay": 100,
            "net_gmv_pay": 1100,
            "net_retention_rate": 0.91,
            "refund_rate_pay": 0.08,
            "brand": "UNKNOWN",
            "is_channel_product": False,
            "product_id": "internal-id",
        }
    ]

    columns = user_table_columns("sku_net_value_fact", rows)

    assert columns == [
        "sku_name",
        "product_name",
        "gmv",
        "refund_amount_pay",
        "net_gmv_pay",
        "net_retention_rate",
        "refund_rate_pay",
    ]
    assert "brand" not in columns
    assert "is_channel_product" not in columns
    assert "product_id" not in columns


def test_refund_diagnostic_hides_caliber_and_internal_ids():
    rows = [
        {
            "caliber": "paytime",
            "sku_id": "internal-sku-id",
            "product_id": "internal-product-id",
            "sku_name": "粉盐地杯盘套装",
            "product_name": "粉盐地系列",
            "category_l1": "餐具",
            "category_l2": "杯碟",
            "gmv": 5000,
            "refund_amount_pay": 500,
            "net_gmv_pay": 4500,
            "refund_rate_pay": 0.1,
        }
    ]

    columns = user_table_columns("sku_refund_paytime", rows)

    assert columns == [
        "sku_name",
        "product_name",
        "category_l1",
        "category_l2",
        "gmv",
        "refund_amount_pay",
        "net_gmv_pay",
        "refund_rate_pay",
    ]
    assert "caliber" not in columns
    assert "sku_id" not in columns
    assert "product_id" not in columns
